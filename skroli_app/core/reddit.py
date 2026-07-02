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


def image_of(d: dict) -> str:
    """Best preview image from a Reddit post's JSON, if any."""
    preview = d.get("preview") or {}
    images = preview.get("images") or []
    if images:
        src = (images[0].get("source") or {}).get("url")
        if src:
            return html.unescape(src)  # Reddit HTML-escapes the URL
    thumb = d.get("thumbnail", "")
    return thumb if thumb.startswith("http") else ""


def fetch_listing(subreddits: list[str], sort: str = "hot", limit: int = 100) -> list[dict]:
    """Fetch one batched listing for ``subreddits`` and return the raw post
    dicts. Goes through the shared host/UA attempt chain."""
    multi = "+".join(s.removeprefix("r/").strip("/") for s in subreddits if s.strip())
    if not multi:
        return []
    raw = get(f"/r/{multi}/{sort}.json?limit={min(limit, 100)}&raw_json=1")
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
    }
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
        image=image_of(d),
        published_at=published,
        meta=meta,
    )


def _stable_id(source: str, entry_id: str) -> str:
    # Same scheme as the RSS ingestor, so already-stored Reddit items keep
    # their ids across this refactor (no duplicates after upgrading).
    import hashlib

    return hashlib.sha1(f"{source}|{entry_id}".encode()).hexdigest()
