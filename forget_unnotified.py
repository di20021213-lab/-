#!/usr/bin/env python3
"""Забывает объявления, которые бот записал виденными, но НЕ прислал.

Зачем. В базе у каждой записи есть отметка notified: 1 — объявление ушло в
Telegram, 0 — бот его увидел и решил не слать. Ноль ставился в двух случаях:
объявление не прошло фильтры (так и надо) и объявление прошло, но упёрлось в
лимит уведомлений за цикл (это была ошибка — такие пропадали навсегда).
Ошибку починили, но записи от неё остались. Этот скрипт их стирает, и на
следующем цикле бот оценит те объявления заново.

Что при этом НЕ произойдёт: уже присланное не придёт повторно — у него
notified=1, и оно остаётся в базе нетронутым. Не прошедшее фильтры тоже не
придёт: его снова отсеют те же фильтры, просто ещё раз.

Использование:
  python3 forget_unnotified.py                 — показать, что будет удалено
  python3 forget_unnotified.py --yes           — удалить
  python3 forget_unnotified.py --label "Имя"   — только по одному поиску
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _load_searches(config_path: str) -> dict | None:
    """label -> настройки поиска. None, если конфиг не прочитался."""
    try:
        from avito_watcher.config import load_settings
        return {s.label: s for s in load_settings(config_path).searches}
    except Exception:  # noqa: BLE001 - без конфига просто не уточняем последствия
        return None


def _consequence(label: str, left: int, searches: dict | None) -> list[str]:
    """Чем обернётся удаление по этому поиску — словами, а не догадками."""
    if left:
        return []
    if searches is None:
        return ["ВНИМАНИЕ: по этому поиску не остаётся ни одной присланной записи, "
                "а конфиг прочитать не удалось — последствия не проверить."]
    search = searches.get(label)
    if search is None:
        return [f"Поиска «{label}» в конфиге нет (отключён или переименован) — "
                "записи просто освободятся, слать по нему сейчас нечего."]
    if search.max_age_minutes is None:
        # Пустой ярлык бот считает первым запуском. Без max_age он тогда молча
        # запоминает всю выдачу и не шлёт НИЧЕГО — ровно наоборот тому, зачем
        # скрипт запускают.
        return ["ВНИМАНИЕ: не остаётся ни одной присланной записи, а у поиска нет "
                "max_age. Бот сочтёт это первым запуском, молча запомнит всю "
                "выдачу и не пришлёт ничего. Оставь хотя бы одну запись или "
                "запускай с --label по другому поиску."]
    return ["Присланных не остаётся — бот сочтёт это первым запуском, но у поиска "
            f"задан max_age, так что пришлёт всё не старше {search.max_age_minutes} мин."]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.getenv("DB_PATH") or "seen.sqlite3")
    ap.add_argument("--config", default="config.yaml",
                    help="откуда узнать настройки поисков (для точных предупреждений)")
    ap.add_argument("--label", help="только этот поиск (по умолчанию — все)")
    ap.add_argument("--yes", action="store_true", help="выполнить, а не показать")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"Нет файла базы: {db}", file=sys.stderr)
        return 1

    # Настройки нужны только ради честных предупреждений: последствия удаления
    # зависят от того, задан ли у поиска max_age, и жив ли он вообще в конфиге.
    searches = _load_searches(args.config)

    conn = sqlite3.connect(db)
    where = "notified = 0"
    params: list[str] = []
    if args.label:
        where += " AND search_label = ?"
        params.append(args.label)

    rows = conn.execute(
        f"SELECT search_label, item_id, title, price FROM seen WHERE {where}", params
    ).fetchall()
    if not rows:
        print("Нечего забывать: записей без отправки нет.")
        return 0

    by_label: dict[str, list] = {}
    for label, item_id, title, price in rows:
        by_label.setdefault(label, []).append((title, price))

    for label, items in by_label.items():
        left = conn.execute(
            "SELECT COUNT(*) FROM seen WHERE search_label = ? AND notified = 1", (label,)
        ).fetchone()[0]
        print(f"\n[{label}] к удалению: {len(items)}; останется присланных: {left}")
        for title, price in items[:10]:
            print(f"    {(price or '—'):>10}  {(title or '')[:60]}")
        if len(items) > 10:
            print(f"    … и ещё {len(items) - 10}")
        for line in _consequence(label, left, searches):
            print(f"    {line}")

    if not args.yes:
        print("\nЭто предпросмотр. Чтобы выполнить, добавь --yes")
        return 0

    backup = db.with_name(f"{db.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(db, backup)
    print(f"\nКопия базы: {backup}")

    conn.execute(f"DELETE FROM seen WHERE {where}", params)
    conn.commit()
    print(f"Удалено записей: {len(rows)}. На следующем цикле бот оценит их заново.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
