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
import json
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

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
    # Pick the richest candidate: the longest <article>/<main>, else the body.
    candidates: list[str] = []
    for tag in ("article", "main"):
        candidates += re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.I | re.S)
    best = max(candidates, key=len, default="")
    if len(best) > 400:
        return best
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
            # No target=_blank — the app intercepts clicks and navigates in-tab.
            self.out.append(f'<a href="{_html.escape(href)}">')
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


def _sanitize(html_fragment: str, base: str) -> str:
    s = _Sanitizer(base)
    s.feed(html_fragment)
    return s.result()


def _reddit(url: str) -> dict:
    """Render a Reddit post + top comments natively from its JSON (the page
    itself is JS-rendered, so reader extraction comes back empty)."""
    raw, _ = _fetch(url.split("?")[0].rstrip("/") + ".json")
    data = json.loads(raw)
    post = data[0]["data"]["children"][0]["data"]
    parts = []
    if post.get("selftext_html"):
        parts.append(_sanitize(_html.unescape(post["selftext_html"]), url))
    elif post.get("url") and not post.get("is_self"):
        u = _html.escape(post["url"])
        parts.append(f'<p><a href="{u}" target="_blank" rel="noopener">{u}</a></p>')
    comments = data[1]["data"]["children"] if len(data) > 1 else []
    rendered = []
    for c in comments:
        if c.get("kind") != "t1":
            continue
        d = c["data"]
        if not d.get("body_html"):
            continue
        rendered.append(
            f'<div class="rcomment"><div class="rcmeta">{_html.escape(d.get("author","?"))}'
            f' · ▲ {d.get("score", 0)}</div>{_sanitize(_html.unescape(d["body_html"]), url)}</div>'
        )
        if len(rendered) >= 40:
            break
    body = "".join(parts)
    if rendered:
        body += '<h3 class="rch">Comments</h3>' + "".join(rendered)
    return {
        "mode": "reader", "url": url, "title": post.get("title", "(untitled)"),
        "byline": "r/" + post.get("subreddit", ""), "image": "", "html": body,
    }


def read_url(url: str) -> dict:
    """Extract a clean reader view of ``url`` (Reddit via its JSON)."""
    if not url:
        return {"url": url, "title": "", "html": "<p>(no url)</p>"}
    host = urlparse(url).netloc.lower()
    if host.endswith("reddit.com") and "/comments/" in url:
        try:
            return _reddit(url)
        except Exception:  # noqa: BLE001 - fall through to generic reader
            pass
    try:
        raw, _ = _fetch(url)
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "title": "", "html": f"<p>Couldn’t load this page ({_html.escape(str(exc))}).</p>"}
    text = raw.decode("utf-8", "replace")
    return {
        "url": url,
        "title": _title(text),
        "byline": _meta(text, "author") or _meta(text, "article:author"),
        "image": _meta(text, "og:image"),
        "html": _sanitize(_region(text), url) or "<p>(no readable content)</p>",
    }


# Script injected into proxied pages so in-page link clicks navigate the skroli
# tab (via postMessage to the parent) instead of the iframe wandering off to a
# frame-blocked URL.
_NAV_SHIM = (
    '<script>(function(){document.addEventListener("click",function(e){'
    'var a=e.target&&e.target.closest&&e.target.closest("a");if(!a||!a.href)return;'
    'e.preventDefault();e.stopPropagation();'
    'try{parent.postMessage({skroliNav:a.href},"*");}catch(_){}}, true);})();</script>'
)


def proxy(url: str) -> tuple[bytes, str]:
    """Fetch ``url`` server-side and return it for same-origin embedding: frame
    headers are dropped (we just don't resend them), a <base> makes subresources
    load from the real site, and a shim routes link clicks back to the app.
    Reddit is served via old.reddit.com, which is server-rendered (the new SPA
    needs APIs we can't proxy)."""
    target = url
    if urlparse(url).netloc.lower().endswith("reddit.com"):
        target = re.sub(r"^https?://[^/]+", "https://old.reddit.com", url, count=1)
    raw, headers = _fetch(target)
    ctype = headers.get("Content-Type", "text/html")
    if "html" not in ctype.lower():
        return raw, ctype  # images/css/etc. pass through untouched
    text = raw.decode("utf-8", "replace")
    inject = f'<base href="{_html.escape(target)}">' + _NAV_SHIM
    if re.search(r"<head[^>]*>", text, re.I):
        text = re.sub(r"<head[^>]*>", lambda m: m.group(0) + inject, text, count=1, flags=re.I)
    else:
        text = inject + text
    return text.encode("utf-8"), "text/html; charset=utf-8"
