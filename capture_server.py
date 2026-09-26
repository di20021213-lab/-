"""Локальный приёмник ссылок из браузера.

Слушает только 127.0.0.1 и принимает POST /capture с JSON {"url": "..."} от
браузерного расширения. Когда приходит ссылка на видео Kinescope — вызывает
колбэк, который добавляет её в очередь скачивания.

Безопасность: сервер доступен только с локальной машины, требует общий токен
в заголовке и принимает только адреса kinescope. По умолчанию выключен —
включается галочкой в приложении.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib.parse import urlparse

CAPTURE_HOST = "127.0.0.1"
CAPTURE_PORT = 53127
CAPTURE_TOKEN = "kinescope-local-capture"  # общий секрет с расширением


_ALLOWED_HOSTS = (
    "kinescope.io", "kinescopecdn.net",
    "mts-link.ru", "webinar.ru", "webinarcdn.com",
)


def is_allowed_url(url: str) -> bool:
    """Разрешаем адреса поддерживаемых площадок или любой манифест m3u8/mpd."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "").lower()
    except ValueError:
        return False
    if path.endswith(".m3u8") or path.endswith(".mpd"):
        return True
    return any(host == h or host.endswith("." + h) or host.endswith(h)
               for h in _ALLOWED_HOSTS)


class CaptureServer:
    """Фоновый HTTP-приёмник ссылок из браузерного расширения."""

    def __init__(self, on_url: Callable[[str], None]) -> None:
        self.on_url = on_url
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def start(self) -> None:
        if self._httpd is not None:
            return
        on_url = self.on_url

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # тихо
                pass

            def _cors(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Content-Type, X-Kinescope-Token",
                )
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802 — пинг для проверки
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

            def do_POST(self) -> None:  # noqa: N802
                if self.headers.get("X-Kinescope-Token") != CAPTURE_TOKEN:
                    self.send_response(403)
                    self._cors()
                    self.end_headers()
                    return
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    data = json.loads(raw.decode("utf-8") or "{}")
                except ValueError:
                    data = {}
                url = str(data.get("url") or "").strip()
                accepted = bool(url) and is_allowed_url(url)

                self.send_response(200 if accepted else 400)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}' if accepted else b'{"ok":false}')

                if accepted:
                    payload = {
                        "url": url,
                        "referer": str(data.get("referer") or "").strip(),
                        "cookies": str(data.get("cookies") or "").strip(),
                        "title": str(data.get("title") or "").strip(),
                    }
                    try:
                        on_url(payload)
                    except Exception:  # noqa: BLE001 — не роняем сервер
                        pass

        self._httpd = ThreadingHTTPServer((CAPTURE_HOST, CAPTURE_PORT), Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._thread = None
