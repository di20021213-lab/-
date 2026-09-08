"""Одиночная проверка доступности Авито простым HTTP-запросом.

Без браузера: нужен ровно один запрос, чтобы понять, пускает нас IP или нет.
Используется и в diag.py (разовая диагностика), и в watch_ip.py (сторож,
который ждёт снятия лимита).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import requests
import yaml

from .scraper import ANTIBOT_MARKERS

TIMEOUT_S = 30

# Тот же набор заголовков, что шлёт обычный десктопный Chrome.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class ProbeResult:
    ok: bool                        # пустил ли нас Авито
    status: Optional[int] = None    # HTTP-статус (None — запрос не прошёл)
    items: int = 0                  # сколько объявлений нашлось в HTML
    markers: tuple[str, ...] = ()   # найденные признаки страницы блокировки
    error: Optional[str] = None     # текст сетевой ошибки

    def describe(self) -> str:
        if self.error:
            return f"запрос не прошёл: {self.error}"
        if self.markers:
            return f"HTTP {self.status}, страница блокировки ({', '.join(self.markers)})"
        if self.status == 429:
            return "HTTP 429: лимит запросов с этого IP"
        if self.status and self.status >= 400:
            return f"HTTP {self.status}"
        if not self.items:
            return f"HTTP {self.status}, но объявлений в HTML нет"
        return f"HTTP {self.status}, объявлений: {self.items}"


def decode(resp: requests.Response) -> str:
    """Текст ответа в правильной кодировке.

    requests, не найдя charset в заголовке Content-Type, берёт ISO-8859-1 —
    и русский текст превращается в мусор. Тогда проверка на «Доступ ограничен»
    молча промахивается и мы считаем блокировку чистым ответом.
    """
    if "charset" not in (resp.headers.get("Content-Type") or "").lower():
        resp.encoding = "utf-8"
    return resp.text


def url_from_config(path: str = "config.yaml") -> Optional[str]:
    """Первый URL поиска из config.yaml (или None, если файла/поисков нет)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except OSError:
        return None
    searches = raw.get("searches") or []
    if not searches:
        return None
    return (searches[0].get("url") or "").strip() or None


def probe(url: str, proxy: Optional[str] = None) -> ProbeResult:
    """Один запрос к выдаче. Ничего не повторяет: повторы — это и есть лимит."""
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S, proxies=proxies)
    except requests.RequestException as e:
        return ProbeResult(ok=False, error=str(e))

    body = decode(resp)
    items = len(re.findall(r'data-marker="item"', body))
    lowered = body[:20000].lower()
    markers = tuple(m for m in ANTIBOT_MARKERS if m in lowered)

    # Страницу «Доступ ограничен» Авито отдаёт с кодом 200, так что одного
    # статуса мало — смотрим и на текст, и на наличие самих объявлений.
    ok = not markers and resp.status_code < 400 and items > 0
    return ProbeResult(ok=ok, status=resp.status_code, items=items, markers=markers)
