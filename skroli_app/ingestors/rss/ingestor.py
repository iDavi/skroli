"""Built-in RSS ingestor (SPECS §3.1).

Reads any RSS 2.0 or Atom feed using only the Python standard library. Three
source kinds share this ingestor:

* **feeds** — any RSS/Atom URL.
* **subreddits** — fetched from Reddit's JSON API (``/r/<name>/hot.json``) so we
  capture upvotes, comment counts, and a preview image for the engagement
  enhancer. No account needed.
* **letterboxd** — a username's public review feed (``letterboxd.com/<user>/rss``).

This ingestor ships with skroli and cannot be removed.
"""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from .config import RssConfig
from ...core.fetcher import fetch
from ...core.models import Item, utcnow
from ...core import reddit

ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_IMG_SRC = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
REDDIT_LIMIT = 25  # posts per subreddit


_LB_FOLLOWING = re.compile(r'href="/([^/"]+)/"\s+class="name"')
_LB_MAX_PAGES = 12  # ~25 names/page → cap the import so it stays quick


def letterboxd_following(username: str, max_pages: int = _LB_MAX_PAGES) -> list[str]:
    """Scrape the public ``/<user>/following/`` pages for the accounts they
    follow. Letterboxd has no API, so this reads the HTML; used by the UI's
    "import following" button to bulk-add profiles."""
    user = username.strip().lstrip("@").strip("/")
    if not user:
        return []
    seen: list[str] = []
    known: set[str] = set()
    for page in range(1, max_pages + 1):
        path = f"https://letterboxd.com/{user}/following/"
        if page > 1:
            path += f"page/{page}/"
        try:
            html_text = fetch(path).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - stop on the first page that fails
            break
        names = [n for n in _LB_FOLLOWING.findall(html_text) if n != user]
        fresh = [n for n in names if n not in known]
        if not fresh:
            break  # no new names → past the last page
        for n in fresh:
            known.add(n)
            seen.append(n)
    return seen


def _stable_id(source: str, entry_id: str) -> str:
    return hashlib.sha1(f"{source}|{entry_id}".encode()).hexdigest()


def _clean(text: str) -> str:
    # Strip tags, then decode HTML entities (feeds double up on both).
    return html.unescape(_WS.sub(" ", _TAGS.sub(" ", text or "")).strip())


def _img_from_html(*chunks: str) -> str:
    """First <img src> found in any HTML chunk (description / content:encoded)."""
    for chunk in chunks:
        if not chunk:
            continue
        m = _IMG_SRC.search(chunk)
        if m:
            return html.unescape(m.group(1))
    return ""


def _extract_image(el) -> str:
    """Pull a lead image from the many places feeds hide one, in priority order.

    Covers Media RSS (media:content / media:thumbnail), RSS enclosures, and a
    fallback scan of the description / content:encoded HTML for an <img> tag.
    """
    # Media RSS: prefer an explicit image; fall back to a thumbnail.
    for mc in el.findall(f"{MEDIA}content"):
        url = mc.get("url")
        medium, mtype = mc.get("medium", ""), mc.get("type", "")
        if url and (medium == "image" or mtype.startswith("image/") or not medium):
            return url
    thumb = el.find(f"{MEDIA}thumbnail")
    if thumb is not None and thumb.get("url"):
        return thumb.get("url")
    # RSS <enclosure type="image/..."> and Atom <link rel="enclosure">.
    for enc in el.findall("enclosure") + el.findall(f"{ATOM}link"):
        if enc.get("type", "").startswith("image/") and (enc.get("url") or enc.get("href")):
            return enc.get("url") or enc.get("href")
    # Last resort: an <img> embedded in the summary/description/content HTML.
    raw_html = " ".join(
        _text(el.find(tag))
        for tag in ("description", f"{CONTENT}encoded", f"{ATOM}summary", f"{ATOM}content")
    )
    return _img_from_html(raw_html)


def _parse_date(value: str) -> datetime:
    if not value:
        return utcnow()
    try:  # RFC 822 (RSS pubDate)
        dt = parsedate_to_datetime(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    try:  # RFC 3339 / ISO 8601 (Atom)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return utcnow()


def _text(el) -> str:
    return el.text.strip() if el is not None and el.text else ""


class RssIngestor:
    name = "rss"

    def __init__(self, config: RssConfig):
        self._config = config

    def _sources(self) -> list[tuple[str, str, str, str]]:
        """Return (kind, label, url, origin) for every plain-feed source.
        Subreddits are handled separately (one batched request for all of them).

        ``origin`` is a stable id for the configured source (used to purge items
        when a source is removed from the config)."""
        out: list[tuple[str, str, str, str]] = []
        for url in self._config.feeds:
            out.append(("rss", "", url, url))
        for user in self._config.letterboxd:
            u = user.strip().lstrip("@").strip("/")
            out.append(("rss", f"Letterboxd · {u}", f"https://letterboxd.com/{u}/rss/", f"letterboxd:{u}"))
        return out

    def _sub_names(self) -> list[str]:
        return [s.removeprefix("r/").strip("/") for s in self._config.subreddits if s.strip()]

    def _parse(self, raw: bytes, label: str, url: str, origin: str) -> list[Item]:
        root = ET.fromstring(raw)
        items: list[Item] = []

        # RSS 2.0: <rss><channel><item>…
        channel = root.find("channel")
        if channel is not None:
            feed_title = label or _text(channel.find("title")) or urlparse(url).netloc
            for it in channel.findall("item"):
                link = _text(it.find("link")) or _text(it.find("guid"))
                if not link:
                    continue
                entry_id = _text(it.find("guid")) or link
                items.append(self._mk(
                    feed_title, entry_id, link, _text(it.find("title")),
                    _text(it.find("description")), _text(it.find("pubDate")),
                    _text(it.find("author")), _extract_image(it), origin,
                ))
            return items

        # Atom: <feed><entry>…
        feed_title = label or _text(root.find(f"{ATOM}title")) or urlparse(url).netloc
        for e in root.findall(f"{ATOM}entry"):
            link_el = e.find(f"{ATOM}link")
            link = (link_el.get("href") if link_el is not None else "") or _text(e.find(f"{ATOM}id"))
            if not link:
                continue
            entry_id = _text(e.find(f"{ATOM}id")) or link
            body = _text(e.find(f"{ATOM}summary")) or _text(e.find(f"{ATOM}content"))
            date = _text(e.find(f"{ATOM}published")) or _text(e.find(f"{ATOM}updated"))
            author = _text(e.find(f"{ATOM}author/{ATOM}name"))
            items.append(self._mk(
                feed_title, entry_id, link, _text(e.find(f"{ATOM}title")),
                body, date, author, _extract_image(e), origin,
            ))
        return items

    def _mk(self, source, entry_id, link, title, body, date, author, image, origin) -> Item:
        return Item(
            id=_stable_id(source, entry_id),
            source=source,
            url=link,
            title=_clean(title) or "(untitled)",
            body=_clean(body),
            author=_clean(author),
            image=image,
            published_at=_parse_date(date),
            meta={"origin": origin},
        )

    def _fetch_reddit_all(self) -> list[Item]:
        """All configured subreddits in ONE batched multireddit request (the
        rate-limit strategy — see core/reddit.py). Falls back to per-subreddit
        RSS (no votes) only if the batched JSON is blocked on both hosts."""
        names = self._sub_names()
        if not names:
            return []
        try:
            posts = reddit.fetch_listing(names, limit=min(100, REDDIT_LIMIT * len(names)))
            items = [it for d in posts if (it := reddit.post_to_item(d)) is not None]
            if items:
                return items
        except Exception as exc:  # noqa: BLE001 - fall back to RSS below
            print(f"  · reddit JSON blocked ({exc}); falling back to per-sub RSS (no votes)")
        out: list[Item] = []
        for name in names:
            label, origin = f"r/{name}", f"reddit:{name.lower()}"
            try:
                out.extend(self._parse(
                    reddit.fetch_rss(name), label, f"reddit.com/r/{name}", origin,
                ))
            except Exception as exc:  # noqa: BLE001 - one sub shouldn't stop the rest
                print(f"  ! subreddit failed on all hosts: r/{name} ({exc})")
        return out

    def _fetch_source(self, src: tuple[str, str, str, str]) -> list[Item]:
        kind, label, url, origin = src
        try:
            return self._parse(fetch(url), label, url, origin)
        except Exception as exc:  # noqa: BLE001 - one bad feed shouldn't stop the rest
            print(f"  ! feed failed ({label or url}): {exc}")
            return []

    def fetch(self) -> list[Item]:
        if not self._config.enabled:
            return []
        sources = self._sources()
        tasks = [lambda s=s: self._fetch_source(s) for s in sources]
        if self._sub_names():
            tasks.append(self._fetch_reddit_all)   # all subreddits = one request
        if not tasks:
            return []
        # Fetch concurrently — the fetcher throttles per domain, so this only
        # overlaps requests to *different* hosts (same-host stays serialized
        # and rate-limited). Turns a serial sum of latencies into ~the slowest.
        items: list[Item] = []
        with ThreadPoolExecutor(max_workers=min(8, len(tasks))) as pool:
            for result in pool.map(lambda fn: fn(), tasks):
                items.extend(result)
        return items
