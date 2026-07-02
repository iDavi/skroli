"""Image-discovery ingestor: a Pinterest-style pool of photos from image-centric
subreddits.

Rate-limit strategy: every configured subreddit goes into ONE batched
multireddit request (``/r/a+b+c/hot.json`` — see core/reddit.py), so a dozen
subreddits cost a single call. Posts without a usable image are dropped, and
surviving items are tagged ``meta['gallery']`` so the viewer routes them to the
Images grid instead of the reading feed.
"""

from __future__ import annotations

from .config import ImagesConfig
from ...core import reddit
from ...core.models import Item


class ImagesIngestor:
    name = "images"

    def __init__(self, config: ImagesConfig):
        self._config = config

    def fetch(self) -> list[Item]:
        cfg = self._config
        if not cfg.enabled or not cfg.subreddits:
            return []
        posts = reddit.fetch_listing(cfg.subreddits, limit=max(cfg.count, 10))
        items: list[Item] = []
        for d in posts:
            # ``img:`` namespaces both the item id and the origin, so the same
            # post can coexist with a copy from the reading feed, and removing
            # a sub here never prunes the feed's items (or vice versa).
            it = reddit.post_to_item(d, id_ns="img:", extra_meta={"gallery": True})
            if it is None or not it.image:
                continue
            it.meta["origin"] = "img:" + it.meta["origin"]
            items.append(it)
        return items
