"""Точка входа: цикл мониторинга Авито -> уведомления в Telegram."""

from __future__ import annotations

import logging
import random
import signal
import sys
import time

from . import filters
from .config import ConfigError, SearchConfig, Settings, load_settings
from .notifier import TelegramNotifier
from .scraper import AntibotError, AvitoScraper
from .storage import SeenStore

log = logging.getLogger("avito_watcher")

_stop = False


def _handle_signal(signum, frame):  # noqa: ARG001
    global _stop
    _stop = True
    log.info("Получен сигнал остановки, завершаюсь после текущего цикла...")


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
            ok = notifier.send_listing(lst, search.label)
            store.mark_seen(search.label, lst.id, notified=ok, title=lst.title, price=lst.price)
            if ok:
                sent += 1
                log.info("[%s] уведомление: %s | %s", search.label, lst.title, lst.price)
            time.sleep(0.5)  # мягкий троттлинг Telegram
        else:
            store.mark_seen(search.label, lst.id, notified=False, title=lst.title, price=lst.price)

    if sent >= max_notifications and len(new_listings) > max_notifications:
        log.warning("[%s] достигнут лимит %d уведомлений за цикл, остальное помечено без отправки",
                    search.label, max_notifications)


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        settings: Settings = load_settings()
    except ConfigError as e:
        log.error("Ошибка конфигурации: %s", e)
        return 2

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    store = SeenStore(settings.db_path)
    notifier = TelegramNotifier(
        settings.telegram_token,
        settings.telegram_chat_id,
        proxy=settings.proxy,
        api_base=settings.telegram_api_base,
    )

    labels = ", ".join(s.label for s in settings.searches)
    log.info("Старт мониторинга. Поисков: %d (%s). Интервал: %d-%d сек.",
             len(settings.searches), labels, settings.poll_interval_min, settings.poll_interval_max)
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

                if _stop:
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
