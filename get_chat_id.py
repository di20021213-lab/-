"""Помощник: узнать свой TELEGRAM_CHAT_ID.

Как пользоваться:
  1. Создай бота у @BotFather, получи токен.
  2. Положи токен в .env (TELEGRAM_BOT_TOKEN=...), либо экспортируй в окружение.
  3. Напиши что-нибудь СВОЕМУ боту в Telegram (например, /start).
  4. Запусти:  python get_chat_id.py
  5. Скопируй показанный chat_id в .env (TELEGRAM_CHAT_ID=...).
"""

from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Не найден TELEGRAM_BOT_TOKEN. Задай его в .env или в переменных окружения.")
        return 2

    # Те же настройки, что и у бота: за туннелем/прокси иначе не достучаться.
    api_base = (os.getenv("TELEGRAM_API_BASE") or "https://api.telegram.org").rstrip("/")
    proxy = (os.getenv("TELEGRAM_PROXY") or os.getenv("PROXY") or "").strip()
    proxies = {"http": proxy, "https": proxy} if proxy else None
    if proxy:
        print(f"(через прокси {proxy})")

    url = f"{api_base}/bot{token}/getUpdates"
    try:
        resp = requests.get(url, timeout=30, proxies=proxies)
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"Ошибка запроса к Telegram: {e}")
        print("Если ты за туннелем — проверь, что он поднят и задан TELEGRAM_PROXY.")
        return 1

    if not data.get("ok"):
        print(f"Telegram вернул ошибку: {data.get('description')}")
        return 1

    updates = data.get("result", [])
    if not updates:
        print(
            "Апдейтов нет. Напиши своему боту любое сообщение (например, /start) "
            "и запусти скрипт снова."
        )
        return 1

    seen = {}
    for upd in updates:
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is not None and chat_id not in seen:
            name = chat.get("title") or (
                f"{chat.get('first_name', '')} {chat.get('last_name', '')}".strip()
            ) or chat.get("username") or "?"
            seen[chat_id] = name

    print("Найденные chat_id:")
    for chat_id, name in seen.items():
        print(f"  {chat_id}  ({name})")
    print("\nВставь нужный в .env:  TELEGRAM_CHAT_ID=<число выше>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
