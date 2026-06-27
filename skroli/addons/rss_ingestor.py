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
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from ..config import RssConfig
from ..models import Item, utcnow

USER_AGENT = "skroli/0.0.1 (+https://github.com/iDavi/skroli)"
ATOM = "{http://www.w3.org/2005/Atom}"
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _stable_id(source: str, entry_id: str) -> str:
    return hashlib.sha1(f"{source}|{entry_id}".encode()).hexdigest()


def _clean(text: str) -> str:
    # Strip tags, then decode HTML entities (feeds double up on both).
    return html.unescape(_WS.sub(" ", _TAGS.sub(" ", text or "")).strip())


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
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()

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
                    _text(it.find("author")), is_reddit,
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
                body, date, author, is_reddit,
            ))
        return items

    def _mk(self, source, entry_id, link, title, body, date, author, is_reddit) -> Item:
        return Item(
            id=_stable_id(source, entry_id),
            source=source,
            url=link,
            title=_clean(title) or "(untitled)",
            body=_clean(body),
            author=_clean(author),
            published_at=_parse_date(date),
            meta={"is_reddit": is_reddit},
        )

    def fetch(self) -> list[Item]:
        items: list[Item] = []
        for label, url, is_reddit in self._sources():
            try:
                raw = self._fetch_url(url)
                items.extend(self._parse(raw, label, url, is_reddit))
            except Exception as exc:  # noqa: BLE001 - one bad feed shouldn't stop the rest
                print(f"  ! feed failed ({label or url}): {exc}")
        return items
