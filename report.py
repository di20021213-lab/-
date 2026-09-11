#!/usr/bin/env python3
"""Сводка по накопленной базе: есть ли в категории заработок.

Отвечает на три вопроса, ради которых всё и затевалось:
  · сколько объявлений появляется в день — стоит ли вообще следить;
  · какой разброс цен — есть ли зазор между «дёшево» и «обычно»;
  · за сколько вещи уходят — быстро ли надо реагировать.

Запуск:  python report.py            (или --db путь, --label "Имя поиска")
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

DAY = 86400


def money(text) -> int | None:
    """«3 500 ₽» -> 3500. Договорная и прочее без цифр -> None."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", str(text))
    return int(digits) if digits else None


def pct(values: list[int], p: float) -> int:
    """Процентиль по отсортированному списку (ближайший ранг)."""
    if not values:
        return 0
    i = max(0, min(len(values) - 1, round(p / 100 * (len(values) - 1))))
    return values[i]


def human(seconds: float) -> str:
    if seconds < 3600:
        return f"{seconds / 60:.0f} мин"
    if seconds < DAY:
        return f"{seconds / 3600:.1f} ч"
    return f"{seconds / DAY:.1f} дн"


def bar(n: int, top: int, width: int = 24) -> str:
    return "█" * max(1, round(n / top * width)) if n else ""


def matching(rows, search):
    """Оставляет только то, что прошло бы фильтры поиска.

    Без этого цифровой спам по 350 ₽ попадает в статистику наравне с дисками:
    он тянет медиану вниз и заполняет собой «дешевле медианы», превращая отчёт
    в красивую бессмыслицу. Фильтры берём настоящие, из конфига.

    Свежесть при этом не проверяем: в базе нет возраста объявления, только
    время, когда мы его увидели. Для поиска без max_age это ничего не меняет.
    """
    if search is None:
        return rows, False
    # dataclasses.replace, а не copy.replace: последний появился только
    # в Python 3.13, а на мини-ПК 3.11.
    from dataclasses import replace
    from avito_watcher.filters import passes
    from avito_watcher.scraper import Listing

    relaxed = replace(search, max_age_minutes=None)
    kept = []
    for r in rows:
        price = money(r[4])
        lst = Listing(id="", title=r[3], price=r[4], price_value=price, url=None,
                      location=None, date_text=None, image_url=None)
        if passes(lst, relaxed):
            kept.append(r)
    return kept, True


def load_search(config_path: str, label: str):
    """Настройки поиска по его названию. None — конфиг не прочитался."""
    try:
        from avito_watcher.config import load_settings
        for s in load_settings(config_path).searches:
            if s.label == label:
                return s
    except Exception:  # noqa: BLE001 - без конфига просто считаем по всему
        pass
    return None


def report(conn: sqlite3.Connection, label: str, config_path: str) -> None:
    rows = conn.execute(
        "SELECT first_seen, last_seen, notified, title, price FROM seen WHERE search_label = ?",
        (label,),
    ).fetchall()
    if not rows:
        print(f"\n[{label}] пусто")
        return

    now = time.time()
    firsts = [r[0] for r in rows if r[0]]
    span = max(now - min(firsts), DAY)

    print(f"\n\033[1m[{label}]\033[0m")
    print(f"  наблюдение с {datetime.fromtimestamp(min(firsts)):%d.%m %H:%M} "
          f"({span / DAY:.1f} дн)")
    print(f"  объявлений всего: {len(rows)}  →  {len(rows) / (span / DAY):.1f} в день")

    good, filtered = matching(rows, load_search(config_path, label))
    if filtered:
        print(f"  из них подходящих под твои фильтры: {len(good)} "
              f"({len(good) / (span / DAY):.1f} в день)")
        print("  Дальше считаю ТОЛЬКО по ним — иначе цифровой спам портит всю картину.")
    else:
        print("  (настройки поиска не нашлись — считаю по всему подряд, "
              "вместе с посторонним)")

    prices = sorted(p for p in (money(r[4]) for r in good) if p)
    if len(prices) < 5:
        print("  слишком мало данных для выводов — подожди, пока накопится")
        return

    p25, med, p75 = pct(prices, 25), pct(prices, 50), pct(prices, 75)
    print(f"\n  цены: минимум {prices[0]} · 25% {p25} · \033[1mмедиана {med}\033[0m "
          f"· 75% {p75} · максимум {prices[-1]} ₽")

    # Вот ради этого числа всё и считается: если дешёвых почти нет, ловить нечего,
    # сколько ни следи.
    cheap = [p for p in prices if p <= med * 0.8]
    print(f"  дешевле медианы на 20%+: {len(cheap)} шт "
          f"({len(cheap) / len(prices) * 100:.0f}%), "
          f"{len(cheap) / (span / DAY):.1f} в день")
    if cheap:
        print(f"  запас на таком: {med - max(cheap)}–{med - min(cheap)} ₽ до медианы "
              "(до вычета доставки и комиссий)")

    print("\n  как распределены цены:")
    lo, hi = prices[0], prices[-1]
    step = max(1, (hi - lo) // 8 or 1)
    buckets = {}
    for p in prices:
        buckets[(p - lo) // step] = buckets.get((p - lo) // step, 0) + 1
    top = max(buckets.values())
    for b in sorted(buckets):
        lo_b = lo + b * step
        print(f"    {lo_b:>6}-{lo_b + step - 1:<6} {buckets[b]:>3}  {bar(buckets[b], top)}")

    lifes = [r[1] - r[0] for r in good if r[1] and r[0] and r[1] > r[0]]
    print()
    if len(lifes) >= 5:
        lifes.sort()
        print(f"  сколько висят до снятия: медиана {human(pct(lifes, 50))}, "
              f"четверть уходит быстрее {human(pct(lifes, 25))}")
        print("  Чем быстрее уходят — тем меньше у тебя времени на решение.")
    else:
        print("  время жизни объявлений пока не измерено — счётчик начал копиться")
        print("  только сейчас. Вернись к отчёту через пару дней.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.getenv("DB_PATH") or "seen.sqlite3")
    ap.add_argument("--label", help="только этот поиск")
    ap.add_argument("--config", default="config.yaml",
                    help="откуда взять фильтры поиска (по умолчанию ./config.yaml)")
    args = ap.parse_args()

    try:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    except sqlite3.Error as e:
        print(f"Не открылась база {args.db}: {e}", file=sys.stderr)
        return 1

    labels = ([args.label] if args.label else
              [r[0] for r in conn.execute(
                  "SELECT search_label, COUNT(*) c FROM seen GROUP BY 1 ORDER BY c DESC")])
    if not labels:
        print("В базе нет ни одного поиска.")
        return 0
    for label in labels:
        report(conn, label, args.config)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
