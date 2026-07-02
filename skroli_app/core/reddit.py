"""Shared Reddit access: batched multireddit fetches with a resilient fallback
chain. Used by every ingestor that reads Reddit, so the rate-limit strategy
lives in one place.

Why this exists — Reddit is by far the flakiest source:

* Its WAF 403s unknown/bot User-Agents, so requests go out with a browser UA
  (``fetcher.REDDIT_HEADERS``).
* The rate limit is per-IP and unforgiving, so instead of one request per
  subreddit we use Reddit's *multireddit* syntax — ``/r/a+b+c/hot.json`` —
  which returns posts from N subreddits in ONE request. Each post carries its
  own ``subreddit`` field, so per-source labels and origins still work.
* When JSON is blocked anyway, we retry the same listing on old.reddit.com
  (fronted differently, frequently reachable when www is not) before giving up
  and letting callers fall back to per-subreddit RSS (no votes).
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from .fetcher import BROWSER_UA, USER_AGENT, fetch
from .models import Item, utcnow

# Attempt chain for every Reddit request. Reddit's API rules ask for a unique,
# DESCRIPTIVE User-Agent, and in practice that's what gets through (a spoofed
# browser UA over urllib trips the WAF's UA/TLS-fingerprint mismatch check).
# The browser UA is kept only as a last-resort variant on old.reddit.
_ATTEMPTS: list[tuple[str, dict]] = [
    ("https://www.reddit.com", {"User-Agent": USER_AGENT}),
    ("https://old.reddit.com", {"User-Agent": USER_AGENT}),
    ("https://old.reddit.com", {"User-Agent": BROWSER_UA}),
]


def get(path: str) -> bytes:
    """Fetch ``path`` (e.g. ``/r/a+b/hot.json?...`` or ``/r/x/.rss``) through
    the host/UA attempt chain; returns the first success, raises the last
    error. All ingestors reading Reddit share this, so what works is decided in
    one place."""
    last_exc: Exception | None = None
    for host, headers in _ATTEMPTS:
        try:
            return fetch(host + path, headers=headers, retries=1)
        except Exception as exc:  # noqa: BLE001 - try the next host/UA combo
            last_exc = exc
    raise last_exc if last_exc else RuntimeError("no attempts")


def image_info(d: dict) -> tuple[str, int, int, int]:
    """Best image from a Reddit post's JSON: (url, width, height, count).

    Handles gallery posts (``is_gallery`` + ``media_metadata`` — invisible to
    the plain preview path), then the preview source, then the thumbnail.
    ``count`` > 1 marks multi-image posts so the UI can badge them."""
    if d.get("is_gallery") and d.get("media_metadata"):
        order = [g.get("media_id") for g in (d.get("gallery_data") or {}).get("items", [])]
        metas = d["media_metadata"]
        for mid in order or list(metas):
            s = (metas.get(mid) or {}).get("s") or {}
            src = s.get("u") or s.get("gif") or ""
            if src:
                return html.unescape(src), int(s.get("x") or 0), int(s.get("y") or 0), max(len(order), 1)
    preview = d.get("preview") or {}
    images = preview.get("images") or []
    if images:
        src_el = images[0].get("source") or {}
        src = src_el.get("url")
        if src:
            return (html.unescape(src), int(src_el.get("width") or 0),
                    int(src_el.get("height") or 0), 1)
    thumb = d.get("thumbnail", "")
    if thumb.startswith("http"):
        return thumb, 0, 0, 1
    return "", 0, 0, 0


def image_of(d: dict) -> str:
    """Best preview image URL from a Reddit post's JSON, if any."""
    return image_info(d)[0]


def fetch_listing(subreddits: list[str], sort: str = "hot", limit: int = 100) -> list[dict]:
    """Fetch one batched listing for ``subreddits`` and return the raw post
    dicts. Goes through the shared host/UA attempt chain. ``sort`` accepts
    hot/new/rising plus windowed top ("top-week", "top-month", "top-all")."""
    multi = "+".join(s.removeprefix("r/").strip("/") for s in subreddits if s.strip())
    if not multi:
        return []
    t = ""
    if sort.startswith("top"):
        sort, _, window = sort.partition("-")
        t = f"&t={window or 'week'}"
    raw = get(f"/r/{multi}/{sort}.json?limit={min(limit, 100)}&raw_json=1{t}")
    data = json.loads(raw)
    return [
        c.get("data", {})
        for c in data.get("data", {}).get("children", [])
        if c.get("kind") == "t3"
    ]


def fetch_rss(subreddit: str) -> bytes:
    """A subreddit's public Atom feed (no votes) via the same attempt chain."""
    return get(f"/r/{subreddit.removeprefix('r/').strip('/')}/.rss")


def post_to_item(d: dict, id_ns: str = "", extra_meta: dict | None = None) -> Item | None:
    """Map one raw Reddit post dict to an Item. The subreddit is read from the
    post itself (multireddit listings mix subreddits), and ``origin`` is set to
    ``reddit:<sub>`` unless the caller overrides it via ``extra_meta``."""
    post_id = d.get("id")
    sub = (d.get("subreddit") or "").strip()
    if not post_id or not sub:
        return None
    label = f"r/{sub}"
    permalink = "https://www.reddit.com" + d.get("permalink", "")
    external = d.get("url_overridden_by_dest") or d.get("url") or permalink
    created = d.get("created_utc")
    published = (
        datetime.fromtimestamp(float(created), tz=timezone.utc) if created else utcnow()
    )
    meta = {
        "engagement": int(d.get("score") or 0),
        "comments": int(d.get("num_comments") or 0),
        "comments_url": permalink,
        "origin": f"reddit:{sub.lower()}",
        "nsfw": bool(d.get("over_18")),
    }
    image, w, h, count = image_info(d)
    if w and h:
        meta["img_w"], meta["img_h"] = w, h
    if count > 1:
        meta["n_images"] = count
    if extra_meta:
        meta.update(extra_meta)
    body = d.get("selftext", "") or ""
    return Item(
        id=_stable_id(id_ns + label, str(post_id)),
        source=label,
        url=external,
        title=(d.get("title") or "").strip() or "(untitled)",
        body=body.strip(),
        author=d.get("author", ""),
        image=image,
        published_at=published,
        meta=meta,
    )


def _stable_id(source: str, entry_id: str) -> str:
    # Same scheme as the RSS ingestor, so already-stored Reddit items keep
    # their ids across this refactor (no duplicates after upgrading).
    import hashlib

    return hashlib.sha1(f"{source}|{entry_id}".encode()).hexdigest()
