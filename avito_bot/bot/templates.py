"""Шаблоны сообщений."""
from __future__ import annotations

import random


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def render(templates: list[str], **fields: str) -> str:
    """Случайный шаблон с подставленными полями. Неизвестные плейсхолдеры -> ''."""
    if not templates:
        raise ValueError("В конфиге не задан ни один шаблон (templates)")
    tpl = random.choice(templates)
    text = tpl.format_map(_SafeDict({k: (v or "") for k, v in fields.items()}))
    # схлопнуть пробелы, оставшиеся от пустых плейсхолдеров
    return " ".join(text.split()).strip()
