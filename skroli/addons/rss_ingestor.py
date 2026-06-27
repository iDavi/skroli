"""Built-in RSS ingestor (SPECS §3.1).

Reads any RSS 2.0 or Atom feed using only the Python standard library. Reddit is
supported by adding a subreddit — skroli fetches ``reddit.com/r/<name>/.rss``,
no account needed. This ingestor ships with skroli and cannot be removed; the
user configures its feeds and subreddits.
"""

from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from ..config import RssConfig
from ..models import Item, utcnow

USER_AGENT = "skroli/0.0.1 (+https://github.com/iDavi/skroli)"
ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_IMG_SRC = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
# Reddit rate-limits anonymous .rss hard; be polite between requests and retry.
_REQUEST_GAP_SECONDS = 1.5
_MAX_RETRIES = 3
# Reddit rate-limits anonymous .rss hard; be polite between requests and retry.
_REQUEST_GAP_SECONDS = 1.5
_MAX_RETRIES = 3


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

    def _sources(self) -> list[tuple[str, str, bool]]:
        """Return (label, url, is_reddit) for every configured source."""
        out: list[tuple[str, str, bool]] = []
        for url in self._config.feeds:
            out.append(("", url, False))
        for sub in self._config.subreddits:
            name = sub.removeprefix("r/").strip("/")
            out.append((f"r/{name}", f"https://www.reddit.com/r/{name}/.rss", True))
        return out

    def _fetch_url(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(_MAX_RETRIES):
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == _MAX_RETRIES - 1:
                    raise
                # Honor Retry-After when present, otherwise exponential backoff.
                retry_after = exc.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else 0.0
                except ValueError:
                    wait = 0.0
                wait = max(wait, 2.0 * (2 ** attempt))
                print(f"  · rate-limited (429), retrying in {wait:.0f}s…")
                time.sleep(wait)
        raise RuntimeError("unreachable")

    def _parse(self, raw: bytes, label: str, url: str, is_reddit: bool) -> list[Item]:
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
                    _text(it.find("author")), is_reddit, _extract_image(it),
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
                body, date, author, is_reddit, _extract_image(e),
            ))
        return items

    def _mk(self, source, entry_id, link, title, body, date, author, is_reddit, image) -> Item:
        return Item(
            id=_stable_id(source, entry_id),
            source=source,
            url=link,
            title=_clean(title) or "(untitled)",
            body=_clean(body),
            author=_clean(author),
            image=image,
            published_at=_parse_date(date),
            meta={"is_reddit": is_reddit},
        )

    def fetch(self) -> list[Item]:
        items: list[Item] = []
        sources = self._sources()
        for i, (label, url, is_reddit) in enumerate(sources):
            if i:  # space requests out so feeds (esp. Reddit) don't 429 us
                time.sleep(_REQUEST_GAP_SECONDS)
            try:
                raw = self._fetch_url(url)
                items.extend(self._parse(raw, label, url, is_reddit))
            except Exception as exc:  # noqa: BLE001 - one bad feed shouldn't stop the rest
                print(f"  ! feed failed ({label or url}): {exc}")
        return items
