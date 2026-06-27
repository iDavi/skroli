"""Local item store + deduplication (SPECS §5.2, §5.3).

A thin SQLite layer. The schema is internal; addons never touch it directly.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

from .models import Item, utcnow


class Storage:
    def __init__(self, db_path: str | Path):
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id           TEXT PRIMARY KEY,
                source       TEXT NOT NULL,
                url          TEXT NOT NULL,
                title        TEXT NOT NULL,
                body         TEXT NOT NULL DEFAULT '',
                author       TEXT NOT NULL DEFAULT '',
                image        TEXT NOT NULL DEFAULT '',
                published_at REAL NOT NULL,
                first_seen   REAL NOT NULL,
                saved        INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # Migrate older databases that predate the image column.
        cols = {r["name"] for r in self._db.execute("PRAGMA table_info(items)")}
        if "image" not in cols:
            self._db.execute("ALTER TABLE items ADD COLUMN image TEXT NOT NULL DEFAULT ''")
        self._db.commit()

    def add_new(self, items: list[Item]) -> int:
        """Insert items not seen before (by id). Returns how many were new."""
        now = utcnow().timestamp()
        new = 0
        for it in items:
            cur = self._db.execute(
                """
                INSERT OR IGNORE INTO items
                    (id, source, url, title, body, author, image, published_at, first_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    it.id,
                    it.source,
                    it.url,
                    it.title,
                    it.body,
                    it.author,
                    it.image,
                    it.published_at.timestamp(),
                    now,
                ),
            )
            new += cur.rowcount
            # Backfill an image onto a row that was stored before we extracted one,
            # without disturbing first_seen / saved (so re-fetches "heal" old items).
            if cur.rowcount == 0 and it.image:
                self._db.execute(
                    "UPDATE items SET image = ? WHERE id = ? AND image = ''",
                    (it.image, it.id),
                )
        self._db.commit()
        return new

    def load_recent(self, retention_hours: int) -> list[Item]:
        """All items first seen within the retention window, plus any saved."""
        from datetime import datetime, timezone

        cutoff = (utcnow() - timedelta(hours=retention_hours)).timestamp()
        rows = self._db.execute(
            "SELECT * FROM items WHERE first_seen >= ? OR saved = 1",
            (cutoff,),
        ).fetchall()
        return [
            Item(
                id=r["id"],
                source=r["source"],
                url=r["url"],
                title=r["title"],
                body=r["body"],
                author=r["author"],
                image=r["image"],
                published_at=datetime.fromtimestamp(r["published_at"], tz=timezone.utc),
                saved=bool(r["saved"]),
            )
            for r in rows
        ]

    def prune(self, retention_hours: int) -> int:
        """Drop unsaved items older than the retention window."""
        cutoff = (utcnow() - timedelta(hours=retention_hours)).timestamp()
        cur = self._db.execute(
            "DELETE FROM items WHERE saved = 0 AND first_seen < ?", (cutoff,)
        )
        self._db.commit()
        return cur.rowcount

    def close(self) -> None:
        self._db.close()
