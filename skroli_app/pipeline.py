"""The streaming feed engine: ingest → queue → enhance → broadcast (SPECS §5).

Instead of "fetch everything, then enhance everything, then show", each ingestor
pushes items onto a queue the moment it returns, and a single enhancer worker
drains that queue — scoring, persisting, and broadcasting items as they flow.
The UI opens instantly and fills in as data arrives.

Scores are per-item (recency decay × source weight), so the client can sort the
feed itself and we never have to wait for the whole batch.
"""

from __future__ import annotations

import json
import queue
import threading

from .addons_base import Enhancer, Ingestor
from .config import Config
from .models import Item
from .storage import Storage
from .stream import Broadcaster, Client


def item_to_dict(it: Item) -> dict:
    """The shape the browser receives over the WebSocket."""
    body = it.body or ""
    return {
        "id": it.id,
        "source": it.source,
        "url": it.url,
        "title": it.title,
        "excerpt": body[:240] + ("…" if len(body) > 240 else ""),
        "image": it.image,
        "score": round(it.score, 4),
        "published_at": it.published_at.timestamp(),
        "is_reddit": it.source.startswith("r/"),
        "origin": it.meta.get("origin"),
        # Engagement signals (present for Reddit / Hacker News items).
        "engagement": it.meta.get("engagement"),
        "comments": it.meta.get("comments"),
        "comments_url": it.meta.get("comments_url"),
    }


class Engine:
    def __init__(
        self,
        config: Config,
        storage: Storage,
        ingestors: list[Ingestor],
        enhancers: list[Enhancer],
        broadcaster: Broadcaster,
    ):
        self.config = config
        self.storage = storage
        self.ingestors = ingestors
        self.enhancers = enhancers
        self.broadcaster = broadcaster
        self._queue: queue.Queue[list[Item]] = queue.Queue()
        self._worker = threading.Thread(target=self._enhance_loop, daemon=True)
        self._worker.start()

    # --- enhancer stage (one worker draining the queue) ---------------------
    def _enhance(self, items: list[Item]) -> list[Item]:
        for enh in self.enhancers:
            try:
                items = enh.enhance(items)
            except Exception as exc:  # noqa: BLE001 - one bad enhancer shouldn't stop the feed
                print(f"  ! enhancer '{enh.name}' failed: {exc}")
        return items

    def _enhance_loop(self) -> None:
        while True:
            items = self._queue.get()
            if not items:
                continue
            try:
                self.storage.add_new(items)  # dedup + persist
                items = self._enhance(items)
                self.broadcaster.publish(
                    {"type": "items", "items": [item_to_dict(i) for i in items]}
                )
            except Exception as exc:  # noqa: BLE001 - keep the worker alive across errors
                print(f"  ! processing batch failed: {exc}")

    # --- ingestor stage (parallel, each feeds the queue) --------------------
    def _fetch_one(self, ingestor: Ingestor) -> None:
        try:
            items = ingestor.fetch()
            if items:
                self._queue.put(items)
        except Exception as exc:  # noqa: BLE001 - resilience over correctness
            print(f"  ! ingestor '{ingestor.name}' failed: {exc}")

    def _valid_origins(self) -> set[str]:
        """The set of source origins the current config still includes. Must
        match the ``meta['origin']`` values the ingestors stamp on items."""
        c = self.config
        origins: set[str] = set()
        if c.rss.enabled:
            origins |= set(c.rss.feeds)
            origins |= {f"reddit:{s.removeprefix('r/').strip('/')}" for s in c.rss.subreddits}
            origins |= {f"letterboxd:{u.strip().lstrip('@').strip('/')}" for u in c.rss.letterboxd}
        if c.hn.enabled and c.hn.count > 0:
            origins.add("hn")
        return origins

    def refresh(self) -> None:
        """Kick off a fetch from every ingestor. Returns immediately; items
        stream out over the broadcaster as each source lands."""
        valid = self._valid_origins()
        # Drop anything from sources that were removed from the config.
        self.storage.prune_sources(valid)
        self.broadcaster.publish({"type": "status", "fetching": True})
        threads = [
            threading.Thread(target=self._fetch_one, args=(ing,), daemon=True)
            for ing in self.ingestors
        ]
        for t in threads:
            t.start()

        def finish() -> None:
            for t in threads:
                t.join()
            self.storage.prune(self.config.runtime.retention_hours)
            # Tell clients which origins are still valid so they can drop the rest.
            self.broadcaster.publish(
                {"type": "status", "fetching": False, "origins": sorted(valid)}
            )

        threading.Thread(target=finish, daemon=True).start()

    def run_once(self) -> int:
        """Synchronous fetch → enhance → persist, for ``skroli fetch`` (no server)."""
        fetched: list[Item] = []
        for ing in self.ingestors:
            try:
                fetched.extend(ing.fetch())
            except Exception as exc:  # noqa: BLE001
                print(f"  ! ingestor '{ing.name}' failed: {exc}")
        self.storage.add_new(fetched)
        self.storage.prune(self.config.runtime.retention_hours)
        items = self._enhance(self.storage.load_recent(self.config.runtime.retention_hours))
        return len(items)

    # --- a new viewer connected: send what we already have ------------------
    def send_cached(self, client: Client) -> None:
        items = self.storage.load_recent(self.config.runtime.retention_hours)
        items = self._enhance(items)
        client.send(json.dumps({"type": "items", "items": [item_to_dict(i) for i in items]}))
        client.send(json.dumps({"type": "ready"}))
