"""Точка входа: цикл мониторинга Авито -> уведомления в Telegram."""

from __future__ import annotations

import argparse
import logging
import random
import signal
import sys
import time
from typing import Optional

from . import filters, quality
from .config import ConfigError, SearchConfig, Settings, load_settings
from .dates import format_age
from .notifier import TelegramNotifier
from .scraper import AntibotError, AvitoScraper
from .storage import SeenStore

log = logging.getLogger("avito_watcher")

_stop = False


def _handle_signal(signum, frame):  # noqa: ARG001
    global _stop
    _stop = True
    log.info("Получен сигнал остановки, завершаюсь после текущего цикла...")


def _fetch_details_safe(scraper: AvitoScraper, url: str, label: str) -> Optional[str]:
    """Описание объявления. При любом сбое — None: не теряем объявление из-за ошибки сети."""
    time.sleep(random.uniform(1.0, 3.0))  # не долбим сайт: пауза перед второй страницей
    try:
        return scraper.fetch_details(url)
    except AntibotError as e:
        log.warning("[%s] описание не проверено (антибот): %s", label, e)
    except Exception as e:  # noqa: BLE001
        log.warning("[%s] описание не проверено: %s", label, e)
    return None


def process_search(
    search: SearchConfig,
    scraper: AvitoScraper,
    store: SeenStore,
    notifier: TelegramNotifier,
    max_notifications: int,
) -> None:
    listings = scraper.fetch(search.url)
    log.info("[%s] получено объявлений: %d", search.label, len(listings))
    if not listings:
        return

    first_run = not store.has_any(search.label)

    # Первичный посев БЕЗ фильтра свежести: молча запоминаем всё, чтобы не завалить
    # пользователя старьём на старте. Если задан max_age — наоборот, сразу шлём то,
    # что подходит по свежести (ради этого его и ставят), остальное просто запоминаем.
    if first_run and search.max_age_minutes is None:
        for lst in listings:
            store.mark_seen(search.label, lst.id, notified=True, title=lst.title, price=lst.price)
        log.info("[%s] первичный посев: запомнил %d объявлений (без уведомлений)",
                 search.label, len(listings))
        return
    if first_run:
        log.info("[%s] первый запуск с max_age: пришлю то, что не старше %d мин",
                 search.label, search.max_age_minutes)

    # Новые = те, которых ещё нет в базе. Выдача отсортирована «по дате» (новые сверху),
    # поэтому разворачиваем, чтобы уведомлять в хронологическом порядке.
    new_listings = [lst for lst in listings if not store.is_seen(search.label, lst.id)]
    new_listings.reverse()

    if not new_listings:
        return

    sent = 0
    for lst in new_listings:
        # Запоминаем всё новое, чтобы не переоценивать в следующем цикле.
        matched = filters.passes(lst, search)
        if matched and sent < max_notifications:
            # Признаки неисправности: сначала заголовок (бесплатно), потом — если чисто —
            # само объявление: описание и параметры. Только для финалистов, их мало.
            warning = None
            if search.on_broken != "ignore":
                reason = quality.broken_reason(lst.title, extra=search.extra_broken_markers)
                if reason is None and search.check_description and lst.url:
                    details = _fetch_details_safe(scraper, lst.url, search.label)
                    reason = quality.broken_reason(details, extra=search.extra_broken_markers)
                if reason and search.on_broken == "skip":
                    log.info("[%s] пропуск, похоже нерабочая («%s»): %s | %s",
                             search.label, reason, lst.title, lst.price)
                    store.mark_seen(search.label, lst.id, notified=False,
                                    title=lst.title, price=lst.price)
                    continue
                warning = reason  # режим flag: покажем с пометкой ⚠️
            ok = notifier.send_listing(lst, search.label, warning=warning)
            if ok:
                store.mark_seen(search.label, lst.id, notified=True,
                                title=lst.title, price=lst.price)
                sent += 1
                log.info("[%s] уведомление: %s | %s", search.label, lst.title, lst.price)
            else:
                # НЕ помечаем виденным: Telegram мог быть временно недоступен
                # (моргнул туннель/сеть). Иначе объявление потеряется навсегда.
                # Останется «новым» и уйдёт в следующем цикле.
                log.warning("[%s] не отправилось, повторю в следующем цикле: %s | %s",
                            search.label, lst.title, lst.price)
            time.sleep(0.5)  # мягкий троттлинг Telegram
        else:
            store.mark_seen(search.label, lst.id, notified=False, title=lst.title, price=lst.price)

    if sent >= max_notifications and len(new_listings) > max_notifications:
        log.warning("[%s] достигнут лимит %d уведомлений за цикл, остальное помечено без отправки",
                    search.label, max_notifications)


def check_search(search: SearchConfig, scraper: AvitoScraper, settings: Settings) -> int:
    """Разовая проверка: показать, что бот видит и как отработали фильтры.

    Ничего не шлёт и не пишет в базу — безопасно гонять сколько угодно.
    Возвращает число подходящих объявлений.
    """
    listings = scraper.fetch(search.url)
    print(f"\n=== [{search.label}] найдено на странице: {len(listings)} ===")
    if not listings:
        print("  Ничего не найдено. Проверь URL (открой его в браузере) — "
              "или Авито отдал антибот-страницу.")
        return 0

    good = 0
    for lst in listings[:25]:
        price = f"{lst.price_value} ₽" if lst.price_value is not None else "цена не указана"
        age = format_age(lst.age_minutes)
        head = f"{lst.title} | {price} | {age}"

        reason = filters.explain(lst, search)
        if reason:
            print(f"  ✗ {head}\n      — {reason}")
            continue

        broken = None
        if search.on_broken != "ignore":
            broken = quality.broken_reason(lst.title, extra=search.extra_broken_markers)
            if broken is None and search.check_description and lst.url:
                broken = quality.broken_reason(
                    _fetch_details_safe(scraper, lst.url, search.label),
                    extra=search.extra_broken_markers,
                )
        if broken and search.on_broken == "skip":
            print(f"  ✗ {head}\n      — похоже нерабочая («{broken}»)")
            continue

        good += 1
        mark = f"  ⚠ {head}\n      — прошло, но похоже нерабочая («{broken}»)" if broken else f"  ✓ {head}"
        print(mark)
        print(f"      {lst.url}")

    if len(listings) > 25:
        print(f"  … и ещё {len(listings) - 25} (показаны первые 25)")
    print(f"  ИТОГО подходящих: {good}")
    return good


def run_check(settings: Settings) -> int:
    """Режим --check: проверить конфиг, Telegram и каждый поиск. Ничего не отправляя."""
    print("\n### Проверка настройки ###")

    notifier = TelegramNotifier(settings.telegram_token, settings.telegram_chat_id,
                                proxy=settings.telegram_proxy, api_base=settings.telegram_api_base)
    bot = notifier.check()
    if bot:
        print(f"  ✓ Telegram: токен рабочий, бот @{bot}")
    else:
        print("  ✗ Telegram: токен не принят. Проверь TELEGRAM_BOT_TOKEN в .env "
              "(и доступность api.telegram.org — при блокировках задай TELEGRAM_API_BASE).")

    print(f"  · Поисков в конфиге: {len(settings.searches)}")
    print(f"  · База виденных: {settings.db_path}")
    print(f"  · Прокси для Авито: {settings.proxy or 'нет (напрямую)'}")
    print(f"  · Прокси для Telegram: {settings.telegram_proxy or 'нет (напрямую)'}")

    total = 0
    try:
        with AvitoScraper(headless=settings.headless, proxy=settings.proxy,
                          user_agent=settings.user_agent, timeout_ms=settings.request_timeout_ms,
                          executable_path=settings.executable_path) as scraper:
            for search in settings.searches:
                try:
                    total += check_search(search, scraper, settings)
                except AntibotError as e:
                    print(f"\n=== [{search.label}] ===\n  ✗ {e}\n"
                          "     Нужен российский IP или PROXY в .env.")
                except Exception as e:  # noqa: BLE001
                    print(f"\n=== [{search.label}] ===\n  ✗ ошибка: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"\n✗ Не удалось запустить браузер: {e}\n"
              "  Скорее всего не установлен Chromium: выполни `playwright install chromium`.")
        return 1

    print(f"\nГотово. Подходящих объявлений сейчас: {total}.")
    print("Если всё выглядит правильно — запускай без флагов: python -m avito_watcher.main\n")
    return 0


def run(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="avito_watcher",
        description="Мониторинг новых объявлений на Авито с уведомлениями в Telegram.",
    )
    parser.add_argument("--check", action="store_true",
                        help="разовая проверка настройки: что бот видит и как отработали "
                             "фильтры. Ничего не шлёт и не пишет в базу")
    parser.add_argument("--once", action="store_true",
                        help="один проход по всем поискам и выход (удобно для cron)")
    parser.add_argument("--config", default="config.yaml",
                        help="путь к config.yaml (по умолчанию ./config.yaml)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        settings: Settings = load_settings(args.config)
    except ConfigError as e:
        log.error("Ошибка конфигурации: %s", e)
        return 2

    if args.check:
        return run_check(settings)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    store = SeenStore(settings.db_path)
    notifier = TelegramNotifier(
        settings.telegram_token,
        settings.telegram_chat_id,
        proxy=settings.telegram_proxy,
        api_base=settings.telegram_api_base,
    )

    labels = ", ".join(s.label for s in settings.searches)
    if args.once:
        log.info("Разовый проход. Поисков: %d (%s).", len(settings.searches), labels)
    else:
        log.info("Старт мониторинга. Поисков: %d (%s). Интервал: %d-%d сек.",
                 len(settings.searches), labels,
                 settings.poll_interval_min, settings.poll_interval_max)
        notifier.send_message(
            f"✅ Бот запущен. Слежу за {len(settings.searches)} поиском(ами): {labels}"
        )

    try:
        with AvitoScraper(
            headless=settings.headless,
            proxy=settings.proxy,
            user_agent=settings.user_agent,
            timeout_ms=settings.request_timeout_ms,
            executable_path=settings.executable_path,
        ) as scraper:
            while not _stop:
                for search in settings.searches:
                    if _stop:
                        break
                    try:
                        process_search(
                            search, scraper, store, notifier,
                            settings.max_notifications_per_cycle,
                        )
                    except AntibotError as e:
                        log.warning("[%s] %s", search.label, e)
                    except Exception as e:  # noqa: BLE001 - один сбойный поиск не должен ронять цикл
                        log.exception("[%s] ошибка при обработке: %s", search.label, e)
                    time.sleep(random.uniform(2, 5))  # пауза между разными поисками

                if _stop or args.once:
                    break

                delay = random.uniform(settings.poll_interval_min, settings.poll_interval_max)
                log.info("Пауза %.0f сек до следующей проверки...", delay)
                # Спим короткими интервалами, чтобы быстро реагировать на сигнал остановки.
                slept = 0.0
                while slept < delay and not _stop:
                    time.sleep(min(1.0, delay - slept))
                    slept += 1.0
    finally:
        store.close()
        log.info("Остановлен.")

    return 0


if __name__ == "__main__":
    sys.exit(run())
