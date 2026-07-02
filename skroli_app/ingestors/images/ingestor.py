"""Image-discovery ingestor: a Pinterest-style pool of photos from image-centric
subreddits.

Rate-limit strategy: every configured subreddit goes into ONE batched
multireddit request (``/r/a+b+c/hot.json`` — see core/reddit.py), so a dozen
subreddits cost a single call. Posts without a usable image are dropped, and
surviving items are tagged ``meta['gallery']`` so the viewer routes them to the
Images grid instead of the reading feed.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET

from .config import ImagesConfig
from ...core import reddit
from ...core.fetcher import fetch
from ...core.models import Item, utcnow

_ATOM = "{http://www.w3.org/2005/Atom}"
# In Reddit's RSS the post's target hides behind an <a>[link]</a> anchor; if it
# points at an image file we get the FULL-RES photo even without the JSON API.
_LINK = re.compile(r'<a href="([^"]+)">\s*\[link\]', re.IGNORECASE)
_THUMB = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
_IMG_URL = re.compile(r"\.(jpe?g|png|gif|webp)(\?|$)|//i\.redd\.it/|//i\.imgur\.com/", re.IGNORECASE)


class ImagesIngestor:
    name = "images"

    def __init__(self, config: ImagesConfig):
        self._config = config

    def fetch(self) -> list[Item]:
        cfg = self._config
        if not cfg.enabled:
            return []
        names = [s.removeprefix("r/").strip("/") for s in cfg.subreddits if s.strip()]
        items = self._fetch_reddit(names) + self._fetch_feeds(cfg.feeds)
        return items

    # ---- Reddit (batched JSON, RSS fallback) --------------------------------
    def _fetch_reddit(self, names: list[str]) -> list[Item]:
        if not names:
            return []
        cfg = self._config
        try:
            posts: list[dict] = []
            # Chunk very wide sub lists to keep URLs sane; each chunk is still
            # one request for up to 40 subreddits.
            for i in range(0, len(names), 40):
                posts.extend(reddit.fetch_listing(
                    names[i:i + 40], sort=cfg.sort, limit=max(cfg.count, 10)))
            items: list[Item] = []
            for d in posts:
                # ``img:`` namespaces both the item id and the origin, so the
                # same post can coexist with a copy from the reading feed, and
                # removing a sub here never prunes the feed's items.
                it = reddit.post_to_item(d, id_ns="img:", extra_meta={"gallery": True})
                if it is None or not it.image:
                    continue
                if it.meta.get("nsfw") and not cfg.allow_nsfw:
                    continue
                it.meta["origin"] = "img:" + it.meta["origin"]
                items.append(it)
            if items:
                print(f"  · images: {len(items)} photos (reddit JSON, {cfg.sort})")
                return items
        except Exception as exc:  # noqa: BLE001 - fall back to RSS below
            print(f"  · images: reddit JSON blocked ({exc}); trying per-sub RSS")
        items = self._fetch_rss(names)
        print(f"  · images: {len(items)} photos (RSS fallback)")
        return items

    # ---- non-Reddit image feeds (art blogs, picture-of-the-day…) ------------
    def _fetch_feeds(self, feeds: list[str]) -> list[Item]:
        if not feeds:
            return []
        # The RSS ingestor's parser is config-independent — reuse it rather than
        # duplicating RSS/Atom + image extraction here.
        from ..rss.config import RssConfig
        from ..rss.ingestor import RssIngestor

        parser = RssIngestor(RssConfig())
        out: list[Item] = []
        for url in feeds:
            u = url.strip()
            if not u:
                continue
            try:
                found = parser._parse(fetch(u), "", u, "img:" + u)
            except Exception as exc:  # noqa: BLE001 - one feed shouldn't stop the rest
                print(f"  ! images feed failed ({u}): {exc}")
                continue
            for it in found:
                if not it.image:
                    continue
                # Re-namespace the id so a copy of the same entry in the reading
                # feed stays a distinct item (and keeps its own meta).
                it.id = hashlib.sha1(("img:" + it.id).encode()).hexdigest()
                it.meta["gallery"] = True
                out.append(it)
        if out:
            print(f"  · images: {len(out)} photos (feeds)")
        return out

    # ---- RSS fallback (no votes, but real images) --------------------------
    def _fetch_rss(self, names: list[str]) -> list[Item]:
        out: list[Item] = []
        for name in names:
            try:
                out.extend(self._parse_atom(reddit.fetch_rss(name), name))
            except Exception as exc:  # noqa: BLE001 - one sub shouldn't stop the rest
                print(f"  ! images: r/{name} failed on all hosts ({exc})")
        return out

    def _parse_atom(self, raw: bytes, name: str) -> list[Item]:
        """Reddit's .rss is Atom; each entry's HTML content carries a [link]
        anchor to the post target (often the full-res image) and a thumbnail."""
        label, origin = f"r/{name}", f"img:reddit:{name.lower()}"
        items: list[Item] = []
        for e in ET.fromstring(raw).findall(f"{_ATOM}entry"):
            entry_id = (e.findtext(f"{_ATOM}id") or "").strip()
            title = (e.findtext(f"{_ATOM}title") or "").strip() or "(untitled)"
            link_el = e.find(f"{_ATOM}link")
            permalink = link_el.get("href", "") if link_el is not None else ""
            content = e.findtext(f"{_ATOM}content") or ""
            m = _LINK.search(content)
            target = m.group(1) if m else ""
            image = target if _IMG_URL.search(target or "") else ""
            if not image:  # fall back to the (low-res) thumbnail
                t = _THUMB.search(content)
                image = t.group(1) if t else ""
            if not entry_id or not image:
                continue
            when = (e.findtext(f"{_ATOM}published") or e.findtext(f"{_ATOM}updated") or "").strip()
            items.append(Item(
                id=reddit._stable_id("img:" + label, entry_id),
                source=label,
                url=target or permalink,
                title=title,
                body="",
                author=(e.findtext(f"{_ATOM}author/{_ATOM}name") or "").strip(),
                image=image,
                published_at=_parse_when(when),
                meta={"origin": origin, "gallery": True, "comments_url": permalink},
            ))
        return items


def _parse_when(value: str):
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return utcnow()
