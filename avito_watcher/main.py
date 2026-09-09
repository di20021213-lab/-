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

# Пока Авито нас блокирует, обычная пауза делает только хуже: 429 — это лимит по
# IP, он снимается временем БЕЗ запросов. Продолжать долбить каждые 2 минуты —
# значит держать бан бесконечно. Поэтому уходим в долгую паузу, которая
# удваивается с каждым подряд заблокированным циклом.
BLOCKED_COOLDOWN_S = 900        # 15 минут после первого заблокированного цикла
BLOCKED_COOLDOWN_MAX_S = 3600   # дольше часа не ждём

# После скольких заблокированных циклов подряд написать об этом в Telegram:
# молча простаивать полчаса — хуже, чем одно сообщение.
BLOCKED_ALERT_AFTER = 3

_stop = False


def _handle_signal(signum, frame):  # noqa: ARG001
    global _stop
    _stop = True
    log.info("Получен сигнал остановки, завершаюсь после текущего цикла...")


def _fetch_details_safe(scraper: AvitoScraper, url: str, label: str) -> tuple[Optional[str], bool]:
    """Описание объявления и флаг «проверка состоялась».

    Флаг важен: без него сбой сети выглядел бы так же, как чистое описание, и
    объявление уходило бы без пометки, будто его проверили и всё в порядке.
    """
    # Пауза перед второй страницей. На четырёх поисках объявлений-финалистов
    # больше, и короткая пауза приводила к антиботу на странице объявления —
    # тогда описание не читается и карта уходит без проверки на неисправность.
    time.sleep(random.uniform(3.0, 7.0))
    try:
        return scraper.fetch_details(url), True
    except AntibotError as e:
        log.warning("[%s] описание не проверено (антибот): %s", label, e)
    except Exception as e:  # noqa: BLE001
        log.warning("[%s] описание не проверено: %s", label, e)
    return None, False


def process_search(
    search: SearchConfig,
    scraper: AvitoScraper,
    store: SeenStore,
    notifier: TelegramNotifier,
    max_notifications: int,
) -> None:
    listings = scraper.fetch(search.url, search.max_age_minutes)
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
            unchecked = False
            if search.on_broken != "ignore":
                reason = quality.broken_reason(lst.title, extra=search.extra_broken_markers)
                if reason is None and search.check_description and lst.url:
                    details, ok = _fetch_details_safe(scraper, lst.url, search.label)
                    reason = quality.broken_reason(details, extra=search.extra_broken_markers)
                    unchecked = not ok
                if reason and search.on_broken == "skip":
                    log.info("[%s] пропуск, похоже нерабочая («%s»): %s | %s",
                             search.label, reason, lst.title, lst.price)
                    store.mark_seen(search.label, lst.id, notified=False,
                                    title=lst.title, price=lst.price)
                    continue
                warning = reason  # режим flag: покажем с пометкой ⚠️
            ok = notifier.send_listing(lst, search.label, warning=warning, unchecked=unchecked)
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
    listings = scraper.fetch(search.url, search.max_age_minutes)
    print(f"\n=== [{search.label}] найдено на странице: {len(listings)} ===")
    if not listings:
        print("  Ничего не найдено. Проверь URL (открой его в браузере) — "
              "или Авито отдал антибот-страницу.")
        return 0

    good = 0
    for lst in listings[:25]:
        price = f"{lst.price_value} ₽" if lst.price_value is not None else "цена не указана"
        age = format_age(lst.age_minutes)
        if lst.age_minutes is None:
            if lst.min_age_minutes is not None:
                age = f"старше {format_age(lst.min_age_minutes)}"
            elif lst.date_text:
                # Дата есть, но мы её не разобрали — вот это уже наша проблема.
                age += f" (дата: {lst.date_text!r})"
            else:
                age += " (даты в карточке нет)"
        head = f"{lst.title} | {price} | {age}"

        reason = filters.explain(lst, search)
        if reason:
            print(f"  ✗ {head}\n      — {reason}")
            continue

        broken = None
        checked = True
        if search.on_broken != "ignore":
            broken = quality.broken_reason(lst.title, extra=search.extra_broken_markers)
            if broken is None and search.check_description and lst.url:
                details, checked = _fetch_details_safe(scraper, lst.url, search.label)
                broken = quality.broken_reason(details, extra=search.extra_broken_markers)
        if broken and search.on_broken == "skip":
            print(f"  ✗ {head}\n      — похоже нерабочая («{broken}»)")
            continue

        good += 1
        if broken:
            print(f"  ⚠ {head}\n      — прошло, но похоже нерабочая («{broken}»)")
        elif not checked:
            print(f"  ⚠ {head}\n      — прошло, но описание прочитать не удалось")
        else:
            print(f"  ✓ {head}")
        print(f"      {'📷 ' if lst.image_url else ''}{lst.url}")

    if len(listings) > 25:
        print(f"  … и ещё {len(listings) - 25} (показаны первые 25)")

    # Считаем по ВСЕЙ выдаче, а не только по прошедшим фильтр: иначе при строгом
    # max_age проверить, извлекаются ли фото, было бы попросту не на чем.
    with_photo = [lst.image_url for lst in listings if lst.image_url]
    print(f"  ИТОГО подходящих: {good}")
    print(f"  📷 картинка найдена у {len(with_photo)} из {len(listings)}")
    if with_photo:
        # Показываем саму ссылку: именно её мы отдаём Telegram, и если фото не
        # уходит, по ней сразу видно почему (например, адрес без протокола).
        print(f"     пример ссылки: {with_photo[0]}")
    else:
        print("     Фото не извлекаются — уведомления придут текстом. Пришли этот вывод.")

    # Неразобранная дата не отсеивается по max_age — значит фильтр свежести
    # для таких объявлений просто не работает, и молчать об этом нельзя.
    no_age = [lst for lst in listings if lst.age_minutes is None]
    dated = [lst for lst in listings if lst.age_minutes is not None]
    if no_age and search.max_age_minutes is not None:
        oldest = max((lst.age_minutes for lst in dated), default=None)
        if oldest is not None:
            # Норма, а не поломка: Авито показывает относительную дату примерно
            # неделю, дальше её в карточке просто нет. Раз выдача по дате,
            # всё недатированное лежит ниже датированного — значит оно старше.
            print(f"  · без даты: {len(no_age)} из {len(listings)} — все они идут ниже "
                  f"датированных, то есть старше {format_age(oldest)}")
            if search.require_age:
                print("    и отсеяны как заведомо не подходящие по свежести")
        elif search.require_age:
            print(f"  ⚠ даты нет НИ У ОДНОГО из {len(listings)} — все отсеяны "
                  "из-за require_age: true. Поставь require_age: false "
                  "и пришли этот вывод.")
        else:
            print(f"  ⚠ даты нет ни у одного из {len(listings)} — "
                  "фильтр свежести не работает. Пришли этот вывод.")
    # Дата в карточке есть, но мы её не поняли — вот это уже наша поломка.
    unparsed = sum(1 for lst in no_age if lst.date_text)
    if unparsed:
        print(f"  ⚠ дата есть, но не разобрана у {unparsed} — пришли этот вывод")

    # Самое свежее в выдаче: сразу видно, дело в фильтрах или объявлений просто нет.
    ages = [lst.age_minutes for lst in listings if lst.age_minutes is not None]
    if ages:
        print(f"  🕒 самое свежее объявление: {format_age(min(ages))}")
        if search.max_age_minutes is not None and min(ages) > search.max_age_minutes:
            print(f"     Это старше твоего max_age ({format_age(search.max_age_minutes)}) — "
                  "поэтому присылать сейчас нечего. Бот исправен, объявлений нет.")
    return good


def run_check(settings: Settings) -> int:
    """Режим --check: проверить конфиг, Telegram и каждый поиск. Ничего не отправляя."""
    print("\n### Проверка настройки ###")

    notifier = TelegramNotifier(settings.telegram_token, settings.telegram_chat_id,
                                proxy=settings.telegram_proxy, api_base=settings.telegram_api_base,
                                image_proxy=settings.proxy)
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


def _sleep_interruptibly(delay: float) -> None:
    """Спит короткими кусками, чтобы быстро реагировать на сигнал остановки."""
    slept = 0.0
    while slept < delay and not _stop:
        time.sleep(min(1.0, delay - slept))
        slept += 1.0


def _loop(scraper, settings: Settings, store: SeenStore,
          notifier: TelegramNotifier, once: bool = False) -> None:
    """Основной цикл: проверить все поиски, поспать, повторить.

    Отдельно от run(), чтобы цикл можно было прогнать в тестах с подменённым
    скрапером — иначе логика пауз при блокировке ничем не проверяется.
    """
    blocked_streak = 0   # сколько циклов подряд Авито нас не пустил
    alerted = False      # уже писали в Telegram про блокировку?

    while not _stop:
        ok_count = 0
        blocked_count = 0
        for search in settings.searches:
            if _stop:
                break
            try:
                process_search(
                    search, scraper, store, notifier,
                    settings.max_notifications_per_cycle,
                )
                ok_count += 1
            except AntibotError as e:
                blocked_count += 1
                log.warning("[%s] %s", search.label, e)
            except Exception as e:  # noqa: BLE001 - один сбойный поиск не должен ронять цикл
                log.exception("[%s] ошибка при обработке: %s", search.label, e)
            time.sleep(random.uniform(2, 5))  # пауза между разными поисками

        if _stop or once:
            break

        # Считаем цикл заблокированным, только если не прошёл НИ ОДИН поиск:
        # иначе IP живой, а конкретный поиск сломался по своей причине.
        if blocked_count and not ok_count:
            blocked_streak += 1
        else:
            if alerted:
                notifier.send_message("✅ Авито снова открывается, продолжаю следить.")
                alerted = False
            blocked_streak = 0

        if blocked_streak:
            delay = BLOCKED_COOLDOWN_S * 2 ** (blocked_streak - 1)
            # Джиттер добавляем ДО ограничения, иначе потолок в час превращается
            # в час двенадцать: сначала разброс, потом жёсткий предел.
            delay = min(delay + random.uniform(0, delay * 0.2), BLOCKED_COOLDOWN_MAX_S)
            log.warning(
                "Авито блокирует наш IP (циклов подряд: %d). Пауза %.0f мин: "
                "лимит снимается только временем без запросов.",
                blocked_streak, delay / 60,
            )
            if blocked_streak == BLOCKED_ALERT_AFTER and not alerted:
                alerted = True
                notifier.send_message(
                    "⚠️ Авито блокирует запросы с этого IP. Жду, пока лимит спадёт — "
                    "объявления пока не приходят. Напишу, когда восстановится."
                )
        else:
            delay = random.uniform(settings.poll_interval_min, settings.poll_interval_max)
            log.info("Пауза %.0f сек до следующей проверки...", delay)

        _sleep_interruptibly(delay)


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
        # Картинки лежат на CDN Авито — качаем их тем же маршрутом, что и выдачу.
        image_proxy=settings.proxy,
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
            _loop(scraper, settings, store, notifier, once=args.once)
    finally:
        store.close()
        log.info("Остановлен.")

    return 0


if __name__ == "__main__":
    sys.exit(run())
