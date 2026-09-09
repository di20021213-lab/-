#!/usr/bin/env python3
"""Проверяет, КУДА бот шлёт сообщения, и шлёт одно контрольное.

Нужен, когда в логе бота стоит «уведомление: …» — то есть Telegram ответил
«принято», — а в телефоне пусто. Такое бывает, когда TELEGRAM_CHAT_ID указывает
на другой чат: для Bot API это успешная отправка, просто не туда.

Печатает, кто бот и что за чат стоит в настройках, и отправляет туда сообщение
с текущим временем — его видно сразу.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv

from avito_watcher.notifier import DEFAULT_API_BASE, TelegramNotifier

load_dotenv()


def main() -> int:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        print("Нет TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID в .env", file=sys.stderr)
        return 2

    proxy = (os.getenv("TELEGRAM_PROXY") or os.getenv("PROXY") or "").strip() or None
    api_base = (os.getenv("TELEGRAM_API_BASE") or "").strip() or None

    print(f"chat_id из .env : {chat_id}")
    print(f"прокси         : {proxy or 'нет (напрямую)'}")
    print(f"адрес API      : {api_base or DEFAULT_API_BASE}")

    notifier = TelegramNotifier(token, chat_id, proxy=proxy, api_base=api_base)

    bot = notifier.check()
    print(f"бот            : {'@' + bot if bot else 'ТОКЕН НЕ ПРИНЯТ'}")
    if not bot:
        return 1

    # getChat отвечает, что это за чат на самом деле, — по нему сразу видно,
    # твой это диалог или, например, посторонняя группа.
    session = requests.Session()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    try:
        data = session.post(f"{(api_base or DEFAULT_API_BASE).rstrip('/')}/bot{token}/getChat",
                            data={"chat_id": chat_id}, timeout=30).json()
    except (requests.RequestException, ValueError) as e:
        print(f"чат            : не смог спросить ({e})")
        data = {}

    if data.get("ok"):
        c = data["result"]
        who = c.get("username") or c.get("title") or "?"
        name = " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x)
        print(f"чат            : {c.get('type')} «{name or who}»"
              + (f" (@{c['username']})" if c.get("username") else ""))
    elif data:
        print(f"чат            : Telegram не признаёт этот chat_id — {data.get('description')}")
        print("                 Запусти `python get_chat_id.py`, напиши боту и вставь новый.")

    stamp = f"{datetime.now():%H:%M:%S}"
    if notifier.send_message(f"🔧 Проверка связи в {stamp}. Если видишь это — канал жив."):
        print(f"\nОтправлено в {stamp}. Смотри в Telegram:")
        print("  · пришло       — канал в порядке, ищем пропажу в другом месте;")
        print("  · не пришло    — сообщения уходят в чат выше, а не к тебе.")
        return 0
    print("\nОтправить не удалось — смотри предупреждение выше.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
