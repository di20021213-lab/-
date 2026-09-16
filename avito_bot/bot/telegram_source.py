"""Слушатель Telegram: ловит сообщения в заданных чатах и достаёт ссылки Авито.

Используется userbot-сессия (Telethon) — потому что объявления обычно приходят
в каналы, где вы просто подписчик и куда обычного бота не добавить.
"""
from __future__ import annotations

import logging

from telethon import TelegramClient, events

from .links import extract_links
from .runner import Runner

log = logging.getLogger("telegram")

HELP = (
    "Команды (пишите сюда же):\n"
    "/stats — что в базе и сколько отправлено\n"
    "/pause — остановить отправку\n"
    "/resume — продолжить\n"
    "/dry on|off — режим «только показать, не отправлять»\n"
    "/send <ссылка> — поставить объявление в очередь вручную"
)


def _normalize_sources(raw) -> list:
    out = []
    for item in raw or []:
        if isinstance(item, str) and item.lstrip("-").isdigit():
            out.append(int(item))
        else:
            out.append(item)
    return out


async def build_client(cfg) -> TelegramClient:
    client = TelegramClient(
        cfg.get_path("telegram.session", "data/tg.session"),
        int(cfg.get_path("telegram.api_id")),
        str(cfg.get_path("telegram.api_hash")),
    )
    await client.start()
    return client


def attach_handlers(client: TelegramClient, cfg, runner: Runner) -> None:
    sources = _normalize_sources(cfg.get_path("telegram.sources"))
    report_to = cfg.get_path("telegram.report_to", "me")

    @client.on(events.NewMessage(chats=sources or None))
    async def on_message(event) -> None:                    # noqa: ANN001
        text = f"{event.raw_text or ''}\n{_entity_urls(event)}"
        links = extract_links(text)
        if not links:
            return
        chat = getattr(event.chat, "username", None) or str(event.chat_id)
        for link in links:
            await runner.offer(link, source=chat)

    @client.on(events.NewMessage(chats=report_to, pattern=r"^/"))
    async def on_command(event) -> None:                    # noqa: ANN001
        parts = (event.raw_text or "").split()
        cmd, args = parts[0].lower(), parts[1:]

        if cmd == "/stats":
            stats = runner.storage.stats()
            body = "\n".join(f"{k}: {v}" for k, v in sorted(stats.items()))
            await event.respond(
                f"В очереди сейчас: {runner.queue.qsize()}\n"
                f"Пауза: {'да' if runner.paused else 'нет'}\n"
                f"dry_run: {'да' if runner.dry_run else 'нет'}\n{body}"
            )
        elif cmd == "/pause":
            runner.paused = True
            await event.respond("⏸ Пауза. Очередь копится, отправки нет.")
        elif cmd == "/resume":
            runner.paused = False
            await event.respond("▶️ Продолжаю.")
        elif cmd == "/dry":
            if args and args[0] in ("on", "off"):
                runner.dry_run = args[0] == "on"
                await event.respond(
                    f"dry_run = {'вкл — ничего не отправляется' if runner.dry_run else 'выкл — сообщения уходят по-настоящему'}"
                )
            else:
                await event.respond("Использование: /dry on | /dry off")
        elif cmd == "/send":
            links = extract_links(" ".join(args))
            if not links:
                await event.respond("Не вижу ссылки на объявление Авито.")
                return
            added = [l for l in links if await runner.offer(l, source="ручное")]
            await event.respond(f"Добавлено в очередь: {len(added)} из {len(links)}")
        elif cmd in ("/help", "/start"):
            await event.respond(HELP)


def _entity_urls(event) -> str:                             # noqa: ANN001
    """Ссылки, спрятанные под текстом (гиперссылки в кнопках/разметке)."""
    urls = []
    for _, entity in (event.get_entities_text() or []):
        url = getattr(entity, "url", None)
        if url:
            urls.append(url)
    for row in (getattr(event, "buttons", None) or []):
        for button in row:
            url = getattr(button, "url", None)
            if url:
                urls.append(url)
    return "\n".join(urls)


def make_notifier(client: TelegramClient, cfg):
    target = cfg.get_path("telegram.report_to", "me")

    async def notify(text: str) -> None:
        try:
            await client.send_message(target, text[:4000], link_preview=False)
        except Exception:                                    # noqa: BLE001
            log.exception("не смог отправить отчёт в Telegram")

    return notify
