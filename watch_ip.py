"""Сторож: ждёт, когда Авито снимет лимит с нашего IP.

Делает РОВНО ОДИН простой HTTP-запрос за вызов — без браузера и без повторов.
Смысл в этом: 429 снимается только временем без запросов, поэтому частая
проверка сама держала бы бан. Запускать раз в час (systemd-таймер).

Пишет строку в лог и, когда Авито впервые открывается после блокировки,
шлёт сообщение в Telegram. Повторно об одном и том же не пишет.

Запуск вручную:  python watch_ip.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from avito_watcher.notifier import TelegramNotifier
from avito_watcher.probe import probe, url_from_config

load_dotenv()

LOG_PATH = Path(os.getenv("IP_WATCH_LOG") or "ip_watch.log")
# Помним прошлый результат, чтобы не слать одно и то же сообщение каждый час.
STATE_PATH = Path(os.getenv("IP_WATCH_STATE") or ".ip_watch_state")


def _log(line: str) -> None:
    stamp = datetime.now().strftime("%d.%m %H:%M")
    text = f"{stamp}  {line}"
    print(text)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError as e:
        print(f"(не смог записать лог {LOG_PATH}: {e})")


def _read_state() -> str:
    try:
        return STATE_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_state(value: str) -> None:
    try:
        STATE_PATH.write_text(value, encoding="utf-8")
    except OSError:
        pass  # без состояния сторож просто станет чуть болтливее


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else url_from_config()
    if not url:
        print("Не найден URL: укажи аргументом или заполни searches в config.yaml")
        return 2

    proxy = (os.getenv("PROXY") or "").strip() or None
    result = probe(url, proxy)
    _log(("ОТКРЫТО  " if result.ok else "блокировка  ") + result.describe())

    was = _read_state()
    now = "ok" if result.ok else "blocked"
    _write_state(now)

    # Пишем в Telegram только на переходе блокировка -> открыто: сообщение
    # каждый час одинакового содержания никому не нужно.
    if result.ok and was != "ok":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if token and chat_id:
            notifier = TelegramNotifier(
                token, chat_id,
                proxy=(os.getenv("TELEGRAM_PROXY") or "").strip() or proxy,
                api_base=(os.getenv("TELEGRAM_API_BASE") or "").strip() or None,
            )
            sent = notifier.send_message(
                "🟢 Авито снова пускает с этого IP.\n"
                "Можно запускать бота: sudo systemctl start avito-watcher"
            )
            _log("уведомление в Telegram отправлено" if sent
                 else "не смог отправить уведомление в Telegram")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
