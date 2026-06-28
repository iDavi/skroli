"""Open-a-post support: decide whether a URL can be embedded in an iframe, and
if not, extract a clean readable version of the article. Standard library only.

This powers the in-app tabbed browser: framable pages load live in an iframe;
pages that block framing (X-Frame-Options / CSP frame-ancestors) fall back to a
server-extracted reader view so something always shows.
"""

from __future__ import annotations

import html as _html
import re
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin

USER_AGENT = "Mozilla/5.0 (compatible; skroli/0.0.1; +https://github.com/iDavi/skroli)"
_MAX_BYTES = 3_000_000

# Tags whose entire content we drop, and the inline/block tags we keep.
_DROP = {"script", "style", "noscript", "svg", "iframe", "form", "nav",
         "header", "footer", "aside", "button", "select", "head"}
_KEEP = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote",
         "pre", "code", "img", "a", "figure", "figcaption", "strong", "em",
         "b", "i", "br", "hr", "table", "thead", "tbody", "tr", "td", "th"}
_VOID = {"img", "br", "hr"}


def _fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read(_MAX_BYTES), resp.headers


def _frames_allowed(headers) -> bool:
    xfo = (headers.get("X-Frame-Options") or "").lower()
    if "deny" in xfo or "sameorigin" in xfo:
        return False
    csp = (headers.get("Content-Security-Policy") or "").lower()
    if "frame-ancestors" in csp:
        m = re.search(r"frame-ancestors([^;]*)", csp)
        if m and "*" not in m.group(1):
            return False  # restricts framing and won't include our localhost origin
    return True


def _meta(text: str, key: str) -> str:
    for pat in (
        r'<meta[^>]+(?:property|name)=["\']' + re.escape(key) + r'["\'][^>]*?content=["\']([^"\']*)["\']',
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*?(?:property|name)=["\']' + re.escape(key) + r'["\']',
    ):
        m = re.search(pat, text, re.I)
        if m:
            return _html.unescape(m.group(1)).strip()
    return ""


def _title(text: str) -> str:
    t = _meta(text, "og:title")
    if t:
        return t
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    return re.sub(r"\s+", " ", _html.unescape(m.group(1))).strip() if m else "(untitled)"


def _region(text: str) -> str:
    for tag in ("article", "main"):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.I | re.S)
        if m and len(m.group(1)) > 200:
            return m.group(1)
    m = re.search(r"<body[^>]*>(.*?)</body>", text, re.I | re.S)
    return m.group(1) if m else text


class _Sanitizer(HTMLParser):
    """Emit only an allowlist of tags, with cleaned/absolute href & src."""

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP:
            self._skip += 1
            return
        if self._skip or tag not in _KEEP:
            return
        a = dict(attrs)
        if tag == "a":
            href = urljoin(self.base, a.get("href", "")) if a.get("href") else ""
            self.out.append(f'<a href="{_html.escape(href)}" target="_blank" rel="noopener">')
        elif tag == "img":
            src = a.get("src") or a.get("data-src") or ""
            src = urljoin(self.base, src) if src else ""
            if src:
                self.out.append(f'<img src="{_html.escape(src)}" alt="{_html.escape(a.get("alt", ""))}" loading="lazy">')
        else:
            self.out.append(f"<{tag}>")

    def handle_startendtag(self, tag, attrs):
        if not self._skip and tag in _KEEP:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in _DROP:
            if self._skip:
                self._skip -= 1
            return
        if self._skip or tag not in _KEEP or tag in _VOID:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(_html.escape(data))

    def result(self) -> str:
        out = "".join(self.out)
        out = re.sub(r"(?:\s*<p>\s*</p>\s*)+", "", out)  # drop empty paragraphs
        return out.strip()


def open_url(url: str) -> dict:
    """Return how the UI should open ``url``: as an iframe (framable) or a
    server-extracted reader view (not framable / on error)."""
    if not url:
        return {"mode": "error", "url": url, "error": "no url"}
    try:
        raw, headers = _fetch(url)
    except Exception as exc:  # noqa: BLE001 - surface fetch errors to the UI
        return {"mode": "error", "url": url, "error": str(exc)}
    if _frames_allowed(headers):
        return {"mode": "iframe", "url": url}
    text = raw.decode("utf-8", "replace")
    sanitizer = _Sanitizer(url)
    sanitizer.feed(_region(text))
    return {
        "mode": "reader",
        "url": url,
        "title": _title(text),
        "byline": _meta(text, "author") or _meta(text, "article:author"),
        "image": _meta(text, "og:image"),
        "html": sanitizer.result(),
    }
