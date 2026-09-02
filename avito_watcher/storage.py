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
            INSERT OR IGNORE INTO seen (search_label, item_id, first_seen, notified, title, price)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (search_label, item_id, int(time.time()), 1 if notified else 0, title, price),
        )
        self._conn.commit()

    def count(self, search_label: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM seen WHERE search_label = ?", (search_label,)
        )
        return int(cur.fetchone()[0])

    def close(self) -> None:
        self._conn.close()
