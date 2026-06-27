"""Local item store + deduplication (SPECS §5.2, §5.3).

A thin SQLite layer. The schema is internal; addons never touch it directly.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import timedelta
from pathlib import Path

from .models import Item, utcnow


def _load_meta(raw: str) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


class Storage:
    def __init__(self, db_path: str | Path):
        # Streaming means several threads (ingestor fetches, the enhancer worker,
        # WebSocket connects) touch the DB, so guard every access with a lock.
        self._lock = threading.Lock()
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
                meta         TEXT NOT NULL DEFAULT '{}',
                published_at REAL NOT NULL,
                first_seen   REAL NOT NULL,
                saved        INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # Migrate older databases that predate added columns.
        cols = {r["name"] for r in self._db.execute("PRAGMA table_info(items)")}
        if "image" not in cols:
            self._db.execute("ALTER TABLE items ADD COLUMN image TEXT NOT NULL DEFAULT ''")
        if "meta" not in cols:
            self._db.execute("ALTER TABLE items ADD COLUMN meta TEXT NOT NULL DEFAULT '{}'")
        self._db.commit()

    def add_new(self, items: list[Item]) -> int:
        """Insert items not seen before (by id). Returns how many were new."""
        now = utcnow().timestamp()
        new = 0
        with self._lock:
            for it in items:
                meta_json = json.dumps(it.meta or {})
                cur = self._db.execute(
                    """
                    INSERT OR IGNORE INTO items
                        (id, source, url, title, body, author, image, meta, published_at, first_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        it.id,
                        it.source,
                        it.url,
                        it.title,
                        it.body,
                        it.author,
                        it.image,
                        meta_json,
                        it.published_at.timestamp(),
                        now,
                    ),
                )
                new += cur.rowcount
                # For items we've already seen, refresh the volatile bits without
                # touching first_seen / saved: meta (votes/points change over time)
                # and an image if one is now available but wasn't before.
                if cur.rowcount == 0:
                    self._db.execute(
                        "UPDATE items SET meta = ? WHERE id = ?", (meta_json, it.id)
                    )
                    if it.image:
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
        with self._lock:
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
                meta=_load_meta(r["meta"]),
                published_at=datetime.fromtimestamp(r["published_at"], tz=timezone.utc),
                saved=bool(r["saved"]),
            )
            for r in rows
        ]

    def prune_sources(self, valid_origins: set[str]) -> int:
        """Delete unsaved items whose origin is no longer configured (a source
        was removed). Items without an origin (legacy) are left alone."""
        removed = 0
        with self._lock:
            rows = self._db.execute("SELECT id, meta FROM items WHERE saved = 0").fetchall()
            stale = [
                r["id"] for r in rows
                if (o := _load_meta(r["meta"]).get("origin")) is not None and o not in valid_origins
            ]
            for rid in stale:
                self._db.execute("DELETE FROM items WHERE id = ?", (rid,))
            removed = len(stale)
            if removed:
                self._db.commit()
        return removed

    def prune(self, retention_hours: int) -> int:
        """Drop unsaved items older than the retention window."""
        cutoff = (utcnow() - timedelta(hours=retention_hours)).timestamp()
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM items WHERE saved = 0 AND first_seen < ?", (cutoff,)
            )
            self._db.commit()
        return cur.rowcount

    def close(self) -> None:
        self._db.close()
