"""Извлечение и нормализация ссылок на объявления Авито."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

AVITO_HOSTS = {"avito.ru", "www.avito.ru", "m.avito.ru"}

# Ссылка в тексте сообщения: до пробела/переноса/закрывающей скобки.
_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]+", re.IGNORECASE)

# .../kategoriya/nazvanie_tovara_1234567890  -> 1234567890
_SLUG_ID_RE = re.compile(r"_(\d{6,})$")
# /i/1234567890 или /1234567890
_BARE_ID_RE = re.compile(r"^/(?:i/)?(\d{6,})$")


@dataclass(frozen=True)
class AvitoLink:
    url: str          # нормализованный url без query/fragment
    item_id: str      # id объявления, "" если вытащить не удалось

    @property
    def key(self) -> str:
        """Ключ дедупликации: id объявления, иначе сам url."""
        return self.item_id or self.url


def _strip_tracking(url: str) -> str:
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith("m."):
        host = "www." + host[2:]
    elif host == "avito.ru":
        host = "www.avito.ru"
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, "", ""))


def parse_avito_url(url: str) -> AvitoLink | None:
    """Возвращает AvitoLink, если url ведёт на объявление Авито, иначе None."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    if parts.netloc.lower().split(":")[0] not in AVITO_HOSTS:
        return None

    normalized = _strip_tracking(url)
    path = urlsplit(normalized).path

    item_id = ""
    m = _BARE_ID_RE.match(path)
    if m:
        item_id = m.group(1)
    else:
        m = _SLUG_ID_RE.search(path)
        if m:
            item_id = m.group(1)
        elif len(path.strip("/").split("/")) < 3:
            # /moskva/telefony без карточки — это выдача, а не объявление
            return None

    return AvitoLink(url=normalized, item_id=item_id)


def extract_links(text: str) -> list[AvitoLink]:
    """Все ссылки на объявления Авито из текста, без повторов, в порядке появления."""
    found: list[AvitoLink] = []
    seen: set[str] = set()
    for raw in _URL_RE.findall(text or ""):
        # пунктуация, прилипшая к концу ссылки
        raw = raw.rstrip(".,;:!?»«")
        link = parse_avito_url(raw)
        if link and link.key not in seen:
            seen.add(link.key)
            found.append(link)
    return found
