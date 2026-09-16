"""Очередь откликов: лимиты, паузы, тихие часы, отправка."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import random

from .avito import AvitoBrowser, Card, NeedsHuman, NeedsLogin
from .links import AvitoLink
from .storage import Storage
from .templates import render

log = logging.getLogger("runner")


def in_quiet_hours(window, now: dt.datetime | None = None) -> bool:
    if not window:
        return False
    start, end = int(window[0]), int(window[1])
    hour = (now or dt.datetime.now()).hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end       # интервал через полночь


class Runner:
    def __init__(self, cfg, storage: Storage, browser: AvitoBrowser, notify) -> None:
        self.cfg = cfg
        self.storage = storage
        self.browser = browser
        self.notify = notify                  # async callable(text)
        self.queue: asyncio.Queue[AvitoLink] = asyncio.Queue()
        self.paused = False
        self.dry_run = bool(cfg.get_path("sending.dry_run", True))

    # -- приём ------------------------------------------------------------
    async def offer(self, link: AvitoLink, source: str = "") -> bool:
        """Кладёт объявление в очередь, если раньше не видели."""
        if self.cfg.get_path("sending.skip_duplicates", True):
            if not self.storage.add_queued(link.key, link.url):
                log.info("дубль, пропуск: %s", link.url)
                return False
        else:
            self.storage.add_queued(link.key, link.url)
        await self.queue.put(link)
        log.info("в очереди (%s): %s", source, link.url)
        return True

    # -- лимиты -----------------------------------------------------------
    def _limit_block(self) -> str | None:
        per_hour = int(self.cfg.get_path("sending.max_per_hour", 10))
        per_day = int(self.cfg.get_path("sending.max_per_day", 50))
        if self.storage.sent_since(3600) >= per_hour:
            return f"лимит в час исчерпан ({per_hour})"
        if self.storage.sent_since(86400) >= per_day:
            return f"лимит в сутки исчерпан ({per_day})"
        if in_quiet_hours(self.cfg.get_path("sending.quiet_hours")):
            return "тихие часы"
        return None

    async def _wait_until_allowed(self) -> None:
        announced = None
        while True:
            if self.paused:
                if announced != "paused":
                    announced = "paused"
                    log.info("на паузе, жду возобновления")
                await asyncio.sleep(10)
                continue
            reason = self._limit_block()
            if reason is None:
                return
            if announced != reason:
                announced = reason
                log.info("жду: %s", reason)
            await asyncio.sleep(60)

    # -- рабочий цикл ------------------------------------------------------
    async def worker(self) -> None:
        while True:
            link = await self.queue.get()
            try:
                await self._wait_until_allowed()
                await self._handle(link)
            except NeedsHuman as exc:
                self.paused = True
                self.storage.mark(link.key, "failed", error=str(exc))
                await self.notify(
                    f"⏸ Пауза: {exc}\nОткройте браузер, пройдите проверку руками, "
                    f"затем пришлите /resume.\n{link.url}"
                )
            except NeedsLogin as exc:
                self.paused = True
                self.storage.mark(link.key, "failed", error=str(exc))
                await self.notify(
                    f"⏸ Пауза: {exc}\nЗапустите `python login.py`, войдите, "
                    f"затем /resume."
                )
            except Exception as exc:                       # noqa: BLE001
                log.exception("ошибка на %s", link.url)
                self.storage.mark(link.key, "failed", error=repr(exc))
                await self.notify(f"⚠️ Ошибка по {link.url}\n{exc}")
            finally:
                self.queue.task_done()

    async def _handle(self, link: AvitoLink) -> None:
        card: Card = await self.browser.open_card(link.url)
        text = render(
            self.cfg.get_path("templates", []),
            title=card.title,
            price=card.price,
            seller=card.seller,
            url=link.url,
        )
        result = await self.browser.send_message(link.url, text, dry_run=self.dry_run)

        if result == "no_chat":
            self.storage.mark(
                link.key, "skipped", title=card.title, price=card.price,
                error="чат недоступен",
            )
            log.info("чат недоступен: %s", link.url)
            return

        self.storage.mark(
            link.key,
            "dry_run" if result == "dry_run" else "sent",
            title=card.title,
            price=card.price,
            message=text,
        )

        if result == "sent":
            self.storage.record_send(link.key)
            await self.notify(f"✅ Отправлено: {card.title or link.url}\n«{text}»")
        else:
            await self.notify(
                f"🧪 DRY-RUN (не отправлено): {card.title or link.url}\n«{text}»"
            )

        pause = random.uniform(
            float(self.cfg.get_path("sending.delay_min_s", 40)),
            float(self.cfg.get_path("sending.delay_max_s", 180)),
        )
        log.info("пауза %.0f c", pause)
        await asyncio.sleep(pause)
