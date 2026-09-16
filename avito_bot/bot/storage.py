"""SQLite-состояние: дедупликация объявлений, журнал отправок, счётчики лимитов."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    key         TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    first_seen  REAL NOT NULL,
    status      TEXT NOT NULL,          -- queued | sent | skipped | failed | dry_run
    title       TEXT,
    price       TEXT,
    message     TEXT,
    error       TEXT,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sends (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL,
    sent_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sends_time ON sends(sent_at);
"""


@dataclass
class Item:
    key: str
    url: str
    status: str
    title: str | None = None
    price: str | None = None


class Storage:
    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # -- дедупликация ------------------------------------------------------
    def is_known(self, key: str) -> bool:
        cur = self.db.execute("SELECT 1 FROM items WHERE key = ?", (key,))
        return cur.fetchone() is not None

    def add_queued(self, key: str, url: str) -> bool:
        """True — объявление новое и поставлено в очередь, False — уже видели."""
        now = time.time()
        try:
            self.db.execute(
                "INSERT INTO items (key, url, first_seen, status, updated_at)"
                " VALUES (?, ?, ?, 'queued', ?)",
                (key, url, now, now),
            )
        except sqlite3.IntegrityError:
            return False
        self.db.commit()
        return True

    def mark(
        self,
        key: str,
        status: str,
        *,
        title: str | None = None,
        price: str | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        self.db.execute(
            "UPDATE items SET status = ?, title = COALESCE(?, title),"
            " price = COALESCE(?, price), message = COALESCE(?, message),"
            " error = ?, updated_at = ? WHERE key = ?",
            (status, title, price, message, error, time.time(), key),
        )
        self.db.commit()

    # -- лимиты ------------------------------------------------------------
    def record_send(self, key: str) -> None:
        self.db.execute(
            "INSERT INTO sends (key, sent_at) VALUES (?, ?)", (key, time.time())
        )
        self.db.commit()

    def sent_since(self, seconds: float) -> int:
        cur = self.db.execute(
            "SELECT COUNT(*) FROM sends WHERE sent_at > ?", (time.time() - seconds,)
        )
        return int(cur.fetchone()[0])

    def stats(self) -> dict[str, int]:
        cur = self.db.execute("SELECT status, COUNT(*) c FROM items GROUP BY status")
        out = {row["status"]: row["c"] for row in cur.fetchall()}
        out["sent_1h"] = self.sent_since(3600)
        out["sent_24h"] = self.sent_since(86400)
        return out

    def close(self) -> None:
        self.db.close()
