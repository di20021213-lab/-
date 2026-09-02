"""Разбор дат Авито в возраст объявления (в минутах).

Авито показывает время публикации по-разному:
  «только что», «5 минут назад», «час назад», «2 часа назад», «день назад»,
  «3 дня назад», «неделю назад», «вчера в 14:30», «сегодня, 09:15», «12 августа».
Всё это приводим к одному числу — сколько минут прошло с публикации.
Если формат незнаком — возвращаем None («возраст неизвестен»).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

# (основы слов единицы, множитель в минутах). Порядок важен: проверяем по очереди.
_UNITS = (
    (("секунд",), 0),
    (("минут",), 1),
    (("час",), 60),
    (("день", "дн"), 1440),
    (("недел",), 10080),
    (("месяц",), 43200),
)

_MONTH_RE = r"(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)"
_MONTH_NUM = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "май": 5, "мая": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def parse_age_minutes(text: Optional[str], now: Optional[datetime] = None) -> Optional[int]:
    """Возраст объявления в минутах по тексту даты Авито, либо None если не разобрали."""
    if not text:
        return None
    t = text.strip().lower().replace("ё", "е")
    now = now or datetime.now(MSK)

    if "только что" in t or t.startswith("сейчас") or "несколько секунд" in t:
        return 0

    m_time = _TIME_RE.search(t)

    # «сегодня, 09:15» / «вчера в 14:30» / просто «вчера»
    if "сегодня" in t or "вчера" in t:
        days = 1 if "вчера" in t else 0
        base = now - timedelta(days=days)
        if m_time:
            stamp = base.replace(hour=int(m_time.group(1)), minute=int(m_time.group(2)),
                                 second=0, microsecond=0)
            return max(0, int((now - stamp).total_seconds() // 60))
        return days * 1440

    # «5 минут назад», «час назад», «2 дня назад», «неделю назад»
    if "назад" in t:
        m = re.search(r"(\d+)", t)
        n = int(m.group(1)) if m else 1  # «час назад» = 1 час
        for stems, mult in _UNITS:
            if any(s in t for s in stems):
                return n * mult
        return None

    # «12 августа», «12 августа 2025», «12 августа в 14:30»
    m = re.search(r"(\d{1,2})\s+" + _MONTH_RE, t)
    if m:
        day, mon = int(m.group(1)), _MONTH_NUM[m.group(2)]
        m_year = re.search(r"\b(20\d{2})\b", t)
        year = int(m_year.group(1)) if m_year else now.year
        try:
            stamp = now.replace(year=year, month=mon, day=day, hour=0, minute=0,
                                second=0, microsecond=0)
        except ValueError:
            return None
        if m_time:
            stamp = stamp.replace(hour=int(m_time.group(1)), minute=int(m_time.group(2)))
        if stamp > now and not m_year:
            # Год не указан, а дата «в будущем» — значит, это прошлый год.
            stamp = stamp.replace(year=year - 1)
        return max(0, int((now - stamp).total_seconds() // 60))

    return None


def format_age(minutes: Optional[int]) -> str:
    """Человекочитаемый возраст для сообщений: «5 мин», «2 ч», «1 д»."""
    if minutes is None:
        return "?"
    if minutes < 60:
        return f"{minutes} мин"
    if minutes < 1440:
        return f"{minutes // 60} ч"
    return f"{minutes // 1440} д"
