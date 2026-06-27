"""Built-in Hacker News ingestor (SPECS §3.1).

The HN RSS feed carries no score, so we use the official Algolia search API
instead — it returns the live front page with points and comment counts, which
the engagement enhancer can fold into ranking. Standard library only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from ..config import HnConfig
from ..fetcher import fetch
from ..models import Item, utcnow

API = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage="
ITEM_URL = "https://news.ycombinator.com/item?id="


def _stable_id(object_id: str) -> str:
    return hashlib.sha1(f"hackernews|{object_id}".encode()).hexdigest()


class HackerNewsIngestor:
    name = "hackernews"

    def __init__(self, config: HnConfig):
        self._config = config

    def fetch(self) -> list[Item]:
        if self._config.count <= 0:
            return []
        payload = json.loads(fetch(API + str(self._config.count)))

        items: list[Item] = []
        for hit in payload.get("hits", []):
            object_id = str(hit.get("objectID") or "")
            if not object_id:
                continue
            comments_url = ITEM_URL + object_id
            points = int(hit.get("points") or 0)
            comments = int(hit.get("num_comments") or 0)
            created = hit.get("created_at_i")
            published = (
                datetime.fromtimestamp(int(created), tz=timezone.utc)
                if created else utcnow()
            )
            items.append(Item(
                id=_stable_id(object_id),
                source="Hacker News",
                # Link to the article if there is one, else the discussion.
                url=hit.get("url") or comments_url,
                title=hit.get("title") or "(untitled)",
                author=hit.get("author") or "",
                published_at=published,
                meta={"engagement": points, "comments": comments,
                      "comments_url": comments_url},
            ))
        return items
