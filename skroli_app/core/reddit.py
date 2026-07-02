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


# Cards/grid target width. Reddit's `source`/`s` is the ORIGINAL upload (often
# 4000px+, tens of MB decoded) — rendering that in a wall of cards is what eats
# gigabytes of memory. Cards get a ~mid-size preview; the original is kept
# separately for the lightbox to load on demand.
_CARD_WIDTH = 720


def _pick_res(cands: list[dict], key_u: str, key_w: str, key_h: str) -> tuple[str, int, int]:
    """From Reddit resolution candidates, the smallest one >= _CARD_WIDTH wide
    (else the largest available)."""
    best: tuple[str, int, int] = ("", 0, 0)
    for c in cands or []:
        u, w, h = c.get(key_u) or "", int(c.get(key_w) or 0), int(c.get(key_h) or 0)
        if not u:
            continue
        if w >= _CARD_WIDTH and (best[1] < _CARD_WIDTH or w < best[1]):
            best = (u, w, h)
        elif best[1] < _CARD_WIDTH and w > best[1]:
            best = (u, w, h)
    return html.unescape(best[0]), best[1], best[2]


def image_info(d: dict) -> tuple[str, int, int, int, str]:
    """Best image from a Reddit post's JSON: (card_url, w, h, count, full_url).

    Handles gallery posts (``is_gallery`` + ``media_metadata`` — invisible to
    the plain preview path), then the preview, then the thumbnail. The card URL
    is a mid-size preview (memory!); ``full_url`` is the original, for the
    lightbox. ``count`` > 1 marks multi-image posts so the UI can badge them."""
    if d.get("is_gallery") and d.get("media_metadata"):
        order = [g.get("media_id") for g in (d.get("gallery_data") or {}).get("items", [])]
        metas = d["media_metadata"]
        for mid in order or list(metas):
            m = metas.get(mid) or {}
            s = m.get("s") or {}
            full = html.unescape(s.get("u") or s.get("gif") or "")
            if not full:
                continue
            card, w, h = _pick_res(m.get("p") or [], "u", "x", "y")
            if not card:
                card, w, h = full, int(s.get("x") or 0), int(s.get("y") or 0)
            return card, w, h, max(len(order), 1), full
    preview = d.get("preview") or {}
    images = preview.get("images") or []
    if images:
        src_el = images[0].get("source") or {}
        full = html.unescape(src_el.get("url") or "")
        if full:
            card, w, h = _pick_res(images[0].get("resolutions") or [], "url", "width", "height")
            if not card:
                card, w, h = full, int(src_el.get("width") or 0), int(src_el.get("height") or 0)
            return card, w, h, 1, full
    thumb = d.get("thumbnail", "")
    if thumb.startswith("http"):
        return thumb, 0, 0, 1, thumb
    return "", 0, 0, 0, ""


def image_of(d: dict) -> str:
    """Best card-size image URL from a Reddit post's JSON, if any."""
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
    image, w, h, count, full = image_info(d)
    if w and h:
        meta["img_w"], meta["img_h"] = w, h
    if count > 1:
        meta["n_images"] = count
    if full and full != image:
        meta["img_full"] = full   # original, loaded only by the lightbox
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
