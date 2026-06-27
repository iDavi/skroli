"""Built-in skroli viewer (SPECS §3.3, §13).

Renders the feed in the skroli design language and serves it on localhost. Opens
a native window via pywebview when available (extra: ``skroli[desktop]``),
otherwise prints a URL to open in a browser.
"""

from __future__ import annotations

import html
import json
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from ..models import Item, utcnow

FONT = '"Libertinus Math","Libertinus Serif",Georgia,"Times New Roman",serif'

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--olive:#4f4b3b;--olive-soft:#56523f;--olive-line:#605b46;
 --card:rgba(255,255,255,.035);--card-hover:rgba(255,255,255,.06);
 --parchment:#f5f3ec;--parchment-dim:#d9d6c8;--stone:#959389;--stone-dim:#8c8a7f;--gold:#c9b27a}
html,body{background:var(--olive);color:var(--parchment);font-family:__FONT__}
body{display:flex;justify-content:center;min-height:100vh;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.nav{width:248px;flex:0 0 248px;padding:26px 18px;position:sticky;top:0;height:100vh;
 border-right:1px solid var(--olive-line);display:flex;flex-direction:column}
.brand{display:flex;align-items:center;gap:10px;font-size:34px;padding:6px 10px 22px}
.brand .stars{color:var(--stone);font-size:18px}
.nav .item{display:flex;align-items:center;gap:14px;padding:11px 14px;border-radius:12px;
 font-size:21px;color:var(--parchment-dim)}
.nav .item .ic{width:20px;text-align:center;color:var(--stone);font-size:16px}
.nav .item.active{color:var(--parchment);background:var(--card)}
.nav .item.active .ic{color:var(--gold)}
.compose{margin-top:18px;background:var(--parchment);color:var(--olive);text-align:center;
 padding:13px;border-radius:14px;font-size:20px;font-weight:600;cursor:pointer;border:0;
 font-family:__FONT__}
.compose:disabled{opacity:.6;cursor:default}
.me{margin-top:auto;display:flex;align-items:center;gap:11px;padding:10px 12px}
.ava{width:40px;height:40px;border-radius:50%;background:var(--olive-soft);
 border:1px solid var(--olive-line);display:flex;align-items:center;justify-content:center;color:var(--stone)}
.me .h{font-size:19px}.me .s{font-size:15px;color:var(--stone)}
.feed{width:600px;flex:0 0 600px;border-right:1px solid var(--olive-line);min-height:100vh}
.feedhead{position:sticky;top:0;backdrop-filter:blur(8px);background:rgba(79,75,59,.82);
 border-bottom:1px solid var(--olive-line);padding:18px 22px;display:flex;
 align-items:center;justify-content:space-between}
.feedhead h1{font-size:21px;font-weight:600}
.feedhead .sub{font-size:13px;color:var(--stone)}
.feedhead .count{font-size:13px;color:var(--stone)}
.post{padding:16px 22px;border-bottom:1px solid var(--olive-line);display:flex;gap:13px}
.post:hover{background:var(--card)}
.src{width:38px;height:38px;border-radius:50%;flex:0 0 38px;display:flex;align-items:center;
 justify-content:center;font-size:13px;border:1px solid var(--olive-line);background:#6b5d34;color:#e7d6a3}
.src.reddit{background:#7a4632;color:#f2c2ad}
.post .body{flex:1;min-width:0}
.meta{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--stone);flex-wrap:wrap}
.meta .name{color:var(--parchment);font-weight:600;font-size:14px}
.meta .badge{font-size:11px;color:var(--parchment-dim);border:1px solid var(--olive-line);
 padding:1px 7px;border-radius:20px}
.dot{color:var(--stone-dim)}
.title{font-size:17px;line-height:1.3;margin:4px 0 3px}
.excerpt{font-size:14px;line-height:1.5;color:var(--parchment-dim)}
.actions{display:flex;align-items:center;gap:24px;margin-top:11px;color:var(--stone);font-size:13px}
.act:hover{color:var(--parchment)}
.score{margin-left:auto;display:flex;align-items:center;gap:6px;font-size:12px;color:var(--stone)}
.score b{color:var(--gold);font-weight:600}
.meter{width:56px;height:4px;border-radius:4px;background:var(--olive-line);overflow:hidden}
.meter i{display:block;height:100%;background:var(--gold)}
.empty{padding:60px 22px;text-align:center;color:var(--stone);font-size:17px}
.rail{width:330px;flex:0 0 330px;padding:20px 22px}
.panel{background:var(--card);border:1px solid var(--olive-line);border-radius:16px;
 padding:14px 16px;margin-bottom:18px}
.panel h3{font-size:15px;margin-bottom:6px;color:var(--stone);font-weight:600;
 text-transform:uppercase;letter-spacing:.6px}
.srcrow{display:flex;align-items:center;justify-content:space-between;padding:8px 0;
 font-size:15px;color:var(--parchment-dim);border-bottom:1px solid var(--olive-line)}
.srcrow:last-child{border-bottom:0}
.srcrow .c{color:var(--stone);font-size:13px}
"""


def _rel_time(dt) -> str:
    secs = (utcnow() - dt).total_seconds()
    if secs < 60:
        return "now"
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    return f"{int(secs // 86400)}d"


def _avatar(source: str, is_reddit: bool) -> tuple[str, str]:
    if is_reddit:
        return "reddit", "r/"
    initials = "".join(w[0] for w in source.split()[:2]).upper() or "★"
    return "", initials


def _post_html(it: Item) -> str:
    # meta isn't persisted through storage, so detect reddit from the source name.
    is_reddit = it.source.startswith("r/")
    cls, badge = _avatar(it.source, is_reddit)
    pct = int(round(it.score * 100))
    excerpt = html.escape(it.body[:240]) + ("…" if len(it.body) > 240 else "")
    badge_html = '<span class="badge">reddit feed</span>' if is_reddit else ""
    return f"""
    <article class="post">
      <div class="src {cls}">{html.escape(badge)}</div>
      <div class="body">
        <div class="meta"><span class="name">{html.escape(it.source)}</span>
          <span class="dot">·</span><span>via RSS</span>
          <span class="dot">·</span><span>{_rel_time(it.published_at)}</span>{badge_html}</div>
        <div class="title">{html.escape(it.title)}</div>
        <div class="excerpt">{excerpt}</div>
        <div class="actions">
          <a class="act" href="{html.escape(it.url)}" target="_blank" rel="noopener">↗ open</a>
          <span class="score">score <b>{it.score:.2f}</b>
            <span class="meter"><i style="width:{pct}%"></i></span></span>
        </div>
      </div>
    </article>"""


def render_page(items: list[Item]) -> str:
    counts = Counter(it.source for it in items)
    sources = "".join(
        f'<a class="srcrow"><span>{html.escape(s)}</span><span class="c">{n}</span></a>'
        for s, n in counts.most_common(8)
    )
    if items:
        posts = "".join(_post_html(it) for it in items)
    else:
        posts = '<div class="empty">No items yet. Add feeds in your config and refresh.</div>'
    nav_items = [
        ("★", "Home", True),
        ("↧", "Ingestors", False),
        ("✦", "Enhancers", False),
        ("▢", "Viewers", False),
        ("⚙", "Settings", False),
    ]
    nav = "".join(
        f'<div class="item{" active" if a else ""}"><span class="ic">{i}</span> {l}</div>'
        for i, l, a in nav_items
    )
    css = CSS.replace("__FONT__", FONT)
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>skroli</title><style>{css}</style></head><body>
<nav class="nav">
  <div class="brand">skroli <span class="stars">★</span></div>
  {nav}
  <button class="compose" onclick="refresh(this)">Refresh feed</button>
  <div class="me"><div class="ava">★</div><div><div class="h">you</div>
    <div class="s">@me · local</div></div></div>
</nav>
<main class="feed">
  <div class="feedhead"><div><h1>Home</h1>
    <div class="sub">your custom local internet algorithm</div></div>
    <div class="count">{len(items)} items</div></div>
  {posts}
</main>
<aside class="rail">
  <div class="panel"><h3>Sources</h3>{sources or '<div class="srcrow">none yet</div>'}</div>
</aside>
<script>
async function refresh(btn){{btn.disabled=true;btn.textContent="Refreshing…";
  await fetch("/api/refresh",{{method:"POST"}});location.reload();}}
</script>
</body></html>"""


class SkroliViewer:
    name = "skroli"

    def __init__(self, port: int = 4242, on_refresh: Callable[[], None] | None = None):
        self.port = port
        self._on_refresh = on_refresh
        self._items: list[Item] = []
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None

    def render(self, items: list[Item]) -> None:
        with self._lock:
            self._items = list(items)

    def _page(self) -> bytes:
        with self._lock:
            return render_page(self._items).encode("utf-8")

    def serve(self, open_window: bool = False) -> None:
        viewer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    body = viewer._page()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path == "/api/refresh":
                    if viewer._on_refresh:
                        viewer._on_refresh()
                    body = json.dumps({"ok": True}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        url = f"http://127.0.0.1:{self.port}"

        if open_window:
            try:
                import webview  # pywebview

                threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
                webview.create_window("skroli", url, width=1200, height=900)
                webview.start()
                return
            except ImportError:
                print("  (pywebview not installed; serving in browser instead)")

        print(f"\n  skroli is running → open {url}\n  Ctrl-C to stop.\n")
        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  stopped.")
