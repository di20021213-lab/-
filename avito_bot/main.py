"""Точка входа: Telegram -> очередь -> отклик на Авито."""
from __future__ import annotations

import asyncio
import logging
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from bot.avito import AvitoBrowser
from bot.config import load_config
from bot.runner import Runner
from bot.storage import Storage
from bot.telegram_source import attach_handlers, build_client, make_notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-8s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


async def amain() -> None:
    cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")
    storage = Storage(cfg.get_path("storage.db", "data/state.sqlite3"))
    browser = AvitoBrowser(cfg)
    await browser.start()

    if not await browser.check_logged_in():
        log.error("Браузер не залогинен на Авито. Запустите: python login.py")
        await browser.close()
        return

    client = await build_client(cfg)
    notify = make_notifier(client, cfg)
    runner = Runner(cfg, storage, browser, notify)
    attach_handlers(client, cfg, runner)

    worker = asyncio.create_task(runner.worker())
    mode = "DRY-RUN (ничего не отправляется)" if runner.dry_run else "БОЕВОЙ режим"
    log.info("Запущен, режим: %s", mode)
    await notify(f"🤖 Бот запущен. Режим: {mode}. /help — команды.")

    try:
        await client.run_until_disconnected()
    finally:
        worker.cancel()
        await browser.close()
        storage.close()


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
