"""Built-in skroli viewer (SPECS §3.3, §13).

Serves an empty shell instantly, then streams items in over a WebSocket as the
engine produces them. The feed is rendered and sorted client-side (by per-item
score), so the window opens immediately and fills in as data arrives. Opens a
native window via pywebview when available (extra: ``skroli[desktop]``),
otherwise prints a URL to open in a browser.
"""

from __future__ import annotations

import html
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from ..config import Config
from .. import stream

from pathlib import Path

_ASSETS = Path(__file__).parent / "assets"


def _asset(name: str) -> bytes:
    return (_ASSETS / name).read_bytes()



def _feed_row(url: str = "") -> str:
    return (f'<div class="erow"><input value="{html.escape(url)}" placeholder="https://example.com/feed.xml">'
            f'<button class="x" type="button" onclick="rm(this)">×</button></div>')


def _sub_row(name: str = "") -> str:
    return (f'<div class="erow"><span class="pre">r/</span>'
            f'<input value="{html.escape(name)}" placeholder="subreddit">'
            f'<button class="x" type="button" onclick="rm(this)">×</button></div>')


def _weight_row(name: str = "", value: str = "") -> str:
    return (f'<div class="erow"><input class="wname" list="srclist" value="{html.escape(name)}" '
            f'placeholder="pick or type a source">'
            f'<input class="wval" type="number" step="0.1" value="{html.escape(value)}" placeholder="1.0">'
            f'<button class="x" type="button" onclick="rm(this)">×</button></div>')


def _lb_row(name: str = "") -> str:
    return (f'<div class="erow"><span class="pre">@</span>'
            f'<input value="{html.escape(name)}" placeholder="username">'
            f'<button class="x" type="button" onclick="rm(this)">×</button></div>')


def _toggle(el_id: str, enabled: bool) -> str:
    chk = " checked" if enabled else ""
    return (f'<label class="toggle"><span>enabled</span>'
            f'<input type="checkbox" id="{el_id}"{chk}></label>')


def _ingestors_page(config: Config) -> str:
    rss = config.rss
    feeds = "".join(_feed_row(u) for u in rss.feeds)
    subs = "".join(_sub_row(s.removeprefix("r/").strip("/")) for s in rss.subreddits)
    lb = "".join(_lb_row(u.lstrip("@")) for u in rss.letterboxd)
    return f"""
    <div class="head"><h1>Ingestors</h1></div>
    <div class="page">
      <div class="card">
        <div class="ctitle">RSS <span class="pill">built-in</span>{_toggle("rss-enabled", config.rss.enabled)}</div>
        <div class="desc">Reads any RSS or Atom feed, subreddits (via Reddit's API,
          with upvotes), and Letterboxd profiles (film reviews).</div>
        <div class="cols">
          <div class="col"><h4>Feeds</h4>
            <div id="feeds">{feeds}</div>
            <button class="addbtn" type="button" onclick="addFeed()">+ add feed</button>
          </div>
          <div class="col"><h4>Subreddits</h4>
            <div id="subs">{subs}</div>
            <button class="addbtn" type="button" onclick="addSub()">+ add subreddit</button>
          </div>
        </div>
        <div style="margin-top:16px">
          <h4 style="font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:var(--stone);margin-bottom:8px">Letterboxd profiles</h4>
          <div id="letterboxd">{lb}</div>
          <button class="addbtn" type="button" onclick="addLb()">+ add profile</button>
          <div class="erow" style="border:0;margin-top:10px;padding:0">
            <span class="pre">@</span>
            <input id="lb-import" placeholder="username to import everyone they follow">
            <button class="x" type="button" style="width:auto;padding:0 12px;white-space:nowrap"
              onclick="importFollowing(this)">import following</button>
          </div>
          <span class="savemsg" id="lb-import-msg"></span>
        </div>
        <div class="saverow">
          <button class="savebtn" type="button" onclick="saveIngestors(this)">Save &amp; refresh</button>
          <span class="savemsg" id="ing-msg"></span>
        </div>
      </div>

      <div class="card">
        <div class="ctitle">Hacker News <span class="pill">built-in</span>{_toggle("hn-enabled", config.hn.enabled)}</div>
        <div class="desc">Pulls the live front page from the official HN API, with
          points and comment counts the engagement enhancer can rank by.</div>
        <div class="cols">
          <div class="col"><h4>Parameters</h4>
            <div class="kv"><span>Stories to fetch (0 = off)</span>
              <input id="hncount" type="number" step="5" min="0" value="{config.hn.count}"></div>
          </div>
          <div class="col"></div>
        </div>
        <div class="saverow">
          <button class="savebtn" type="button" onclick="saveHackernews(this)">Save &amp; refresh</button>
          <span class="savemsg" id="hn-msg"></span>
        </div>
      </div>
    </div>"""


def _enhancers_page(config: Config) -> str:
    score = config.score
    eng = config.engagement
    weights = "".join(_weight_row(k, f"{v:g}") for k, v in score.weights.items())
    return f"""
    <div class="head"><h1>Enhancers</h1></div>
    <div class="page">
      <div class="card">
        <div class="ctitle">Score <span class="pill">built-in</span>{_toggle("score-enabled", config.score.enabled)}</div>
        <div class="desc">Ranks the feed by recency. Each item scores
          <code>0.5 ^ (age / half-life)</code> times its source weight.</div>
        <div class="cols">
          <div class="col"><h4>Parameters</h4>
            <div class="kv"><span>Half-life (hours)</span>
              <input id="halflife" type="number" step="0.5" min="0.1"
                     value="{score.half_life_hours:g}"></div>
          </div>
          <div class="col"><h4>Source weights</h4>
            <div id="weights">{weights}</div>
            <button class="addbtn" type="button" onclick="addWeight()">+ add weight</button>
          </div>
        </div>
        <div class="saverow">
          <button class="savebtn" type="button" onclick="saveEnhancers(this)">Save &amp; refresh</button>
          <span class="savemsg" id="enh-msg"></span>
        </div>
      </div>

      <div class="card">
        <div class="ctitle">Engagement <span class="pill">built-in</span>{_toggle("eng-enabled", config.engagement.enabled)}</div>
        <div class="desc">Blends community votes (Reddit upvotes, HN points) into the
          score: <code>(1−weight)·recency + weight·votes</code>. Items without votes
          (plain RSS, Letterboxd) keep their recency score.</div>
        <div class="cols">
          <div class="col"><h4>Weight (0–1)</h4>
            <div class="kv"><span>How much votes matter</span>
              <input id="engweight" type="number" step="0.05" min="0" max="1"
                     value="{eng.weight:g}"></div>
          </div>
          <div class="col"><h4>Cap</h4>
            <div class="kv"><span>Votes for a full score</span>
              <input id="engcap" type="number" step="100" min="1" value="{eng.cap}"></div>
          </div>
        </div>
        <div class="saverow">
          <button class="savebtn" type="button" onclick="saveEngagement(this)">Save &amp; refresh</button>
          <span class="savemsg" id="eng2-msg"></span>
        </div>
      </div>
    </div>"""


def render_page(config: Config) -> str:
    nav_items = [
        ("⌂", "Home", "home", False),
        ("↓", "Ingestors", "ingestors", False),
        ("⇅", "Enhancers", "enhancers", False),
        ("⚙", "Settings", "settings", True),
    ]
    nav = "".join(
        (
            f'<div class="item soon"><span class="ic">{ic}</span> {label}</div>'
            if soon else
            f'<div class="item{" active" if view == "home" else ""}"'
            f' onclick="show(\'{view}\',this)"><span class="ic">{ic}</span> {label}</div>'
        )
        for ic, label, view, soon in nav_items
    )
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>skroli</title><link rel="stylesheet" href="/app.css"></head><body class="home">
<nav class="nav">
  <div class="brand">skroli</div>
  {nav}
</nav>
<main class="feed">
  <section id="home" class="view active">
    <div class="head"><h1>Home</h1>
      <span class="count" id="count">0 items</span>
      <button class="iconbtn" id="refresh" title="Refresh feed" onclick="refresh(this)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><polyline points="21 3 21 9 15 9"/></svg></button></div>
    <div id="posts"><div class="empty">Loading your feed…</div></div>
  </section>
  <section id="ingestors" class="view">{_ingestors_page(config)}</section>
  <section id="enhancers" class="view">{_enhancers_page(config)}</section>
</main>
<aside class="rail">
  <div class="panel"><h3>Sources</h3><div id="sources"><div class="srcrow">none yet</div></div></div>
</aside>
<datalist id="srclist"></datalist>
<script src="/app.js"></script>
</body></html>"""


class SkroliViewer:
    name = "skroli"

    def __init__(
        self,
        port: int = 4242,
        broadcaster: stream.Broadcaster | None = None,
        on_connect: Callable[[stream.Client], None] | None = None,
        on_refresh: Callable[[], None] | None = None,
        on_save: Callable[[], None] | None = None,
        config: Config | None = None,
    ):
        self.port = port
        self._broadcaster = broadcaster or stream.Broadcaster()
        self._on_connect = on_connect
        self._on_refresh = on_refresh
        self._on_save = on_save
        self._config = config or Config()
        self._httpd: ThreadingHTTPServer | None = None

    def _page(self) -> bytes:
        return render_page(self._config).encode("utf-8")

    def serve(self, open_window: bool = False) -> None:
        viewer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def _send(self, body: bytes, content_type: str):
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/ws":
                    self._serve_ws()
                elif self.path in ("/", "/index.html"):
                    self._send(viewer._page(), "text/html; charset=utf-8")
                elif self.path == "/app.css":
                    self._send(_asset("app.css"), "text/css; charset=utf-8")
                elif self.path == "/app.js":
                    self._send(_asset("app.js"), "application/javascript; charset=utf-8")
                else:
                    self.send_response(404)
                    self.end_headers()

            def _serve_ws(self):
                key = self.headers.get("Sec-WebSocket-Key")
                if not key:
                    self.send_response(400)
                    self.end_headers()
                    return
                handshake = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {stream.accept_key(key)}\r\n\r\n"
                )
                self.wfile.write(handshake.encode())
                self.wfile.flush()
                self.close_connection = True  # we own this socket now

                client = stream.Client(self.connection)
                viewer._broadcaster.add(client)
                try:
                    if viewer._on_connect:
                        viewer._on_connect(client)
                    while True:  # drain frames so we notice disconnects
                        opcode, _ = stream.read_message(self.rfile)
                        if opcode is None or opcode == 0x8:  # EOF or close
                            break
                except OSError:
                    pass
                finally:
                    viewer._broadcaster.remove(client)

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    return json.loads(raw or b"{}")
                except (ValueError, TypeError):
                    return {}

            def _ok(self):
                body = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path == "/api/refresh":
                    if viewer._on_refresh:
                        viewer._on_refresh()
                    self._ok()
                elif self.path == "/api/ingestors":
                    data = self._read_json()
                    rss = viewer._config.rss
                    rss.enabled = bool(data.get("enabled", True))
                    rss.feeds = [str(x) for x in data.get("feeds", []) if str(x).strip()]
                    rss.subreddits = [
                        str(x).strip() for x in data.get("subreddits", []) if str(x).strip()
                    ]
                    rss.letterboxd = [
                        str(x).strip().lstrip("@") for x in data.get("letterboxd", []) if str(x).strip()
                    ]
                    if viewer._on_save:
                        viewer._on_save()
                    self._ok()
                elif self.path == "/api/letterboxd-following":
                    from .rss_ingestor import letterboxd_following
                    data = self._read_json()
                    users = letterboxd_following(str(data.get("username", "")))
                    body = json.dumps({"users": users}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/api/hackernews":
                    data = self._read_json()
                    viewer._config.hn.enabled = bool(data.get("enabled", True))
                    try:
                        viewer._config.hn.count = max(int(data.get("count", 30)), 0)
                    except (ValueError, TypeError):
                        pass
                    if viewer._on_save:
                        viewer._on_save()
                    self._ok()
                elif self.path == "/api/enhancers":
                    data = self._read_json()
                    score = viewer._config.score
                    score.enabled = bool(data.get("enabled", True))
                    try:
                        score.half_life_hours = max(float(data.get("half_life_hours", 12)), 0.1)
                    except (ValueError, TypeError):
                        pass
                    weights: dict[str, float] = {}
                    for k, v in (data.get("weights") or {}).items():
                        try:
                            weights[str(k)] = float(v)
                        except (ValueError, TypeError):
                            continue
                    score.weights = weights
                    if viewer._on_save:
                        viewer._on_save()
                    self._ok()
                elif self.path == "/api/engagement":
                    data = self._read_json()
                    eng = viewer._config.engagement
                    eng.enabled = bool(data.get("enabled", True))
                    try:
                        eng.weight = min(max(float(data.get("weight", 0.4)), 0.0), 1.0)
                    except (ValueError, TypeError):
                        pass
                    try:
                        eng.cap = max(int(data.get("cap", 2000)), 1)
                    except (ValueError, TypeError):
                        pass
                    if viewer._on_save:
                        viewer._on_save()
                    self._ok()
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
