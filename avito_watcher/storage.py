"""Хранилище уже виденных объявлений (SQLite), чтобы не слать дубли."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class SeenStore:
    def __init__(self, path: str = "seen.sqlite3") -> None:
        self.path = path
        parent = Path(path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
                search_label TEXT NOT NULL,
                item_id      TEXT NOT NULL,
                first_seen   INTEGER NOT NULL,
                notified     INTEGER NOT NULL DEFAULT 0,
                title        TEXT,
                price        TEXT,
                PRIMARY KEY (search_label, item_id)
            )
            """
        )
        # last_seen добавлен позже: у старых баз колонки нет, дописываем на месте.
        # Без неё видно только когда объявление появилось, но не когда исчезло —
        # то есть нельзя понять, за сколько вещь уходит. А для перепродажи это
        # главный вопрос: широкий разброс цен без скорости продажи ничего не значит.
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(seen)")}
        if "last_seen" not in cols:
            self._conn.execute("ALTER TABLE seen ADD COLUMN last_seen INTEGER")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def get_float(self, key: str) -> float | None:
        """Число из таблицы meta (None — ключа нет или он испорчен)."""
        cur = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        try:
            return float(row[0])
        except (TypeError, ValueError):
            return None

    def set_float(self, key: str, value: float) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, repr(float(value))),
        )
        self._conn.commit()

    def has_any(self, search_label: str) -> bool:
        """Есть ли вообще записи по этому поиску (для «первичного посева»)."""
        cur = self._conn.execute(
            "SELECT 1 FROM seen WHERE search_label = ? LIMIT 1", (search_label,)
        )
        return cur.fetchone() is not None

    def is_seen(self, search_label: str, item_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM seen WHERE search_label = ? AND item_id = ? LIMIT 1",
            (search_label, item_id),
        )
        return cur.fetchone() is not None

    def mark_seen(
        self,
        search_label: str,
        item_id: str,
        notified: bool = False,
        title: str | None = None,
        price: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO seen
                (search_label, item_id, first_seen, last_seen, notified, title, price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (search_label, item_id, int(time.time()), int(time.time()),
             1 if notified else 0, title, price),
        )
        self._conn.commit()

    def touch(self, search_label: str, item_ids) -> None:
        """Отмечает, что эти объявления ещё висят в выдаче.

        Разница last_seen - first_seen и есть время жизни объявления. Пока
        вещь продаётся, оно растёт; перестало расти — значит сняли, то есть
        скорее всего продали.
        """
        ids = list(item_ids)
        if not ids:
            return
        now = int(time.time())
        self._conn.executemany(
            "UPDATE seen SET last_seen = ? WHERE search_label = ? AND item_id = ?",
            [(now, search_label, i) for i in ids],
        )
        self._conn.commit()

    def count(self, search_label: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM seen WHERE search_label = ?", (search_label,)
        )
        return int(cur.fetchone()[0])

    def close(self) -> None:
        self._conn.close()
