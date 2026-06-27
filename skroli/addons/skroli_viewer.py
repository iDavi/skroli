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

from ..config import RssConfig, ScoreConfig
from ..models import Item, utcnow

FONT = '"Libertinus Math","Libertinus Serif",Georgia,"Times New Roman",serif'

# Rectangular by design — no rounded corners anywhere.
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--olive:#4f4b3b;--olive-soft:#56523f;--olive-line:#605b46;
 --card:rgba(255,255,255,.035);--card-hover:rgba(255,255,255,.06);
 --parchment:#f5f3ec;--parchment-dim:#d9d6c8;--stone:#959389;--stone-dim:#8c8a7f;--gold:#c9b27a}
html,body{background:var(--olive);color:var(--parchment);font-family:__FONT__}
body{display:flex;justify-content:center;min-height:100vh;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}

/* ---------- left nav ---------- */
.nav{width:240px;flex:0 0 240px;padding:24px 14px;position:sticky;top:0;height:100vh;
 border-right:1px solid var(--olive-line);display:flex;flex-direction:column}
.brand{font-size:32px;padding:6px 12px 24px;letter-spacing:.5px}
.nav .item{display:flex;align-items:center;gap:13px;padding:11px 13px;font-size:20px;
 color:var(--parchment-dim);cursor:pointer;border-left:3px solid transparent}
.nav .item .ic{width:22px;text-align:center;color:var(--stone);font-size:17px}
.nav .item:hover{background:var(--card)}
.nav .item.active{color:var(--parchment);background:var(--card);border-left-color:var(--gold)}
.nav .item.active .ic{color:var(--gold)}
.nav .item.soon{opacity:.4;cursor:default}
.nav .item.soon:hover{background:none}
.nav .foot{margin-top:auto;padding:12px;font-size:13px;color:var(--stone-dim)}

/* ---------- middle column ---------- */
.feed{width:600px;flex:0 0 600px;border-right:1px solid var(--olive-line);min-height:100vh}
.head{position:sticky;top:0;z-index:2;backdrop-filter:blur(8px);background:rgba(79,75,59,.85);
 border-bottom:1px solid var(--olive-line);padding:16px 22px;display:flex;
 align-items:center;justify-content:space-between;gap:14px}
.head h1{font-size:21px;font-weight:600}
.head .count{font-size:13px;color:var(--stone);margin-left:auto}
.iconbtn{background:transparent;border:1px solid var(--olive-line);color:var(--parchment);
 width:36px;height:36px;cursor:pointer;font-size:17px;font-family:inherit;
 display:flex;align-items:center;justify-content:center}
.iconbtn:hover{background:var(--card)}
.iconbtn:disabled{opacity:.5;cursor:default}
.iconbtn.spin{animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* ---------- feed posts ---------- */
.view{display:none}
.view.active{display:block}
.post{padding:16px 22px;border-bottom:1px solid var(--olive-line);display:flex;gap:13px}
.post:hover{background:var(--card)}
.src{width:38px;height:38px;flex:0 0 38px;display:flex;align-items:center;justify-content:center;
 font-size:13px;border:1px solid var(--olive-line);background:#6b5d34;color:#e7d6a3}
.src.reddit{background:#7a4632;color:#f2c2ad}
.post .body{flex:1;min-width:0}
.meta{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--stone);flex-wrap:wrap}
.meta .name{color:var(--parchment);font-weight:600;font-size:14px}
.meta .badge{font-size:11px;color:var(--parchment-dim);border:1px solid var(--olive-line);padding:1px 7px}
.dot{color:var(--stone-dim)}
.title{font-size:17px;line-height:1.3;margin:4px 0 3px}
.excerpt{font-size:14px;line-height:1.5;color:var(--parchment-dim)}
.media{margin-top:11px;border:1px solid var(--olive-line);overflow:hidden;
 aspect-ratio:16/9;background:var(--olive-soft)}
.media img{display:block;width:100%;height:100%;object-fit:cover}
.actions{display:flex;align-items:center;gap:24px;margin-top:11px;color:var(--stone);font-size:13px}
.act:hover{color:var(--parchment)}
.score{margin-left:auto;display:flex;align-items:center;gap:6px;font-size:12px;color:var(--stone)}
.score b{color:var(--gold);font-weight:600}
.meter{width:56px;height:4px;background:var(--olive-line);overflow:hidden}
.meter i{display:block;height:100%;background:var(--gold)}
.empty{padding:60px 22px;text-align:center;color:var(--stone);font-size:17px}

/* ---------- ingestors / enhancers pages ---------- */
.page{padding:22px}
.card{border:1px solid var(--olive-line);background:var(--card);padding:18px 20px;margin-bottom:16px}
.card .ctitle{font-size:20px;display:flex;align-items:center;gap:10px}
.card .pill{font-size:11px;color:var(--stone);border:1px solid var(--olive-line);
 padding:2px 8px;text-transform:uppercase;letter-spacing:.5px}
.card .desc{color:var(--stone);font-size:14px;margin:6px 0 16px;line-height:1.5}
.cols{display:flex;gap:26px}
.col{flex:1;min-width:0}
.col h4{font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:var(--stone);
 margin-bottom:8px;display:flex;justify-content:space-between}
.row{padding:8px 0;border-bottom:1px solid var(--olive-line);font-size:14px;
 color:var(--parchment-dim);word-break:break-all}
.row:last-child{border-bottom:0}
.row.none{color:var(--stone-dim)}
.kv{display:flex;justify-content:space-between;padding:9px 0;
 border-bottom:1px solid var(--olive-line);font-size:14px;color:var(--parchment-dim)}
.kv:last-child{border-bottom:0}
.kv b{color:var(--gold);font-weight:600}
.hint{color:var(--stone-dim);font-size:13px;margin-top:16px;line-height:1.5}
.hint code{background:var(--card);border:1px solid var(--olive-line);padding:1px 6px}

/* ---------- editable rows ---------- */
.erow{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--olive-line)}
.erow:last-child{border-bottom:0}
.erow .pre{color:var(--stone);font-size:14px}
.erow input{flex:1;min-width:0;background:var(--olive-soft);border:1px solid var(--olive-line);
 color:var(--parchment);font-family:inherit;font-size:14px;padding:6px 8px}
.erow input:focus{outline:0;border-color:var(--gold)}
.erow .wname{flex:2}.erow .wval{flex:0 0 84px;text-align:right}
.erow .x{flex:0 0 28px;background:transparent;border:1px solid var(--olive-line);color:var(--stone);
 cursor:pointer;height:30px;font-size:15px;font-family:inherit}
.erow .x:hover{color:var(--parchment);background:var(--card)}
.addbtn{margin-top:10px;width:100%;background:transparent;border:1px dashed var(--olive-line);
 color:var(--stone);cursor:pointer;font-family:inherit;font-size:13px;padding:8px}
.addbtn:hover{color:var(--parchment);border-color:var(--stone)}
.kv input{background:var(--olive-soft);border:1px solid var(--olive-line);color:var(--parchment);
 font-family:inherit;font-size:14px;padding:5px 8px;width:90px;text-align:right}
.kv input:focus{outline:0;border-color:var(--gold)}
.saverow{display:flex;align-items:center;gap:14px;margin-top:18px}
.savebtn{background:var(--parchment);color:var(--olive);border:0;font-family:inherit;
 font-size:15px;font-weight:600;padding:9px 18px;cursor:pointer}
.savebtn:hover{background:#fff}
.savebtn:disabled{opacity:.6;cursor:default}
.savemsg{font-size:13px;color:var(--stone)}

/* ---------- right rail (home only) ---------- */
/* Rail column is always reserved so switching tabs never reflows the layout
   (otherwise the centered body re-centers and the sidebar appears to move). */
.rail{width:330px;flex:0 0 330px;padding:20px 22px}
.rail .panel{display:none}
body.home .rail .panel{display:block}
.panel{border:1px solid var(--olive-line);padding:0 16px;margin-bottom:18px}
.panel h3{font-size:13px;padding:14px 0 4px;color:var(--stone);font-weight:600;
 text-transform:uppercase;letter-spacing:.6px}
.srcrow{display:flex;align-items:center;justify-content:space-between;padding:9px 0;
 font-size:15px;color:var(--parchment-dim);border-top:1px solid var(--olive-line)}
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
    initials = "".join(w[0] for w in source.split()[:2]).upper() or "·"
    return "", initials


def _post_html(it: Item) -> str:
    # meta isn't persisted through storage, so detect reddit from the source name.
    is_reddit = it.source.startswith("r/")
    cls, badge = _avatar(it.source, is_reddit)
    pct = int(round(it.score * 100))
    excerpt = html.escape(it.body[:240]) + ("…" if len(it.body) > 240 else "")
    badge_html = '<span class="badge">reddit feed</span>' if is_reddit else ""
    media_html = (
        f'<div class="media"><img src="{html.escape(it.image)}" alt="" loading="lazy"'
        f' onerror="this.closest(\'.media\').remove()"></div>'
        if it.image else ""
    )
    return f"""
    <article class="post">
      <div class="src {cls}">{html.escape(badge)}</div>
      <div class="body">
        <div class="meta"><span class="name">{html.escape(it.source)}</span>
          <span class="dot">·</span><span>via RSS</span>
          <span class="dot">·</span><span>{_rel_time(it.published_at)}</span>{badge_html}</div>
        <div class="title">{html.escape(it.title)}</div>
        <div class="excerpt">{excerpt}</div>
        {media_html}
        <div class="actions">
          <a class="act" href="{html.escape(it.url)}" target="_blank" rel="noopener">↗ open</a>
          <span class="score">score <b>{it.score:.2f}</b>
            <span class="meter"><i style="width:{pct}%"></i></span></span>
        </div>
      </div>
    </article>"""


def _feed_row(url: str = "") -> str:
    return (f'<div class="erow"><input value="{html.escape(url)}" placeholder="https://example.com/feed.xml">'
            f'<button class="x" type="button" onclick="rm(this)">×</button></div>')


def _sub_row(name: str = "") -> str:
    return (f'<div class="erow"><span class="pre">r/</span>'
            f'<input value="{html.escape(name)}" placeholder="subreddit">'
            f'<button class="x" type="button" onclick="rm(this)">×</button></div>')


def _weight_row(name: str = "", value: str = "") -> str:
    return (f'<div class="erow"><input class="wname" value="{html.escape(name)}" placeholder="Source name">'
            f'<input class="wval" type="number" step="0.1" value="{html.escape(value)}" placeholder="1.0">'
            f'<button class="x" type="button" onclick="rm(this)">×</button></div>')


def _ingestors_page(rss: RssConfig) -> str:
    feeds = "".join(_feed_row(u) for u in rss.feeds)
    subs = "".join(_sub_row(s.removeprefix("r/").strip("/")) for s in rss.subreddits)
    return f"""
    <div class="head"><h1>Ingestors</h1></div>
    <div class="page">
      <div class="card">
        <div class="ctitle">RSS <span class="pill">built-in · always on</span></div>
        <div class="desc">Reads any RSS or Atom feed, plus subreddits via their
          public <code>.rss</code>. This ingestor ships with skroli and can't be removed.</div>
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
        <div class="saverow">
          <button class="savebtn" type="button" onclick="saveIngestors(this)">Save &amp; refresh</button>
          <span class="savemsg" id="ing-msg"></span>
        </div>
      </div>
    </div>"""


def _enhancers_page(score: ScoreConfig) -> str:
    weights = "".join(_weight_row(k, f"{v:g}") for k, v in score.weights.items())
    return f"""
    <div class="head"><h1>Enhancers</h1></div>
    <div class="page">
      <div class="card">
        <div class="ctitle">Score <span class="pill">built-in</span></div>
        <div class="desc">Ranks the feed by recency. Each item scores
          <code>0.5 ^ (age / half-life)</code> times its source weight, then the
          feed is sorted high to low.</div>
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
    </div>"""


def render_page(items: list[Item], rss: RssConfig, score: ScoreConfig) -> str:
    counts = Counter(it.source for it in items)
    sources = "".join(
        f'<a class="srcrow"><span>{html.escape(s)}</span><span class="c">{n}</span></a>'
        for s, n in counts.most_common(8)
    )
    posts = (
        "".join(_post_html(it) for it in items) if items
        else '<div class="empty">No items yet. Add feeds in Ingestors and refresh.</div>'
    )
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
    css = CSS.replace("__FONT__", FONT)
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>skroli</title><style>{css}</style></head><body class="home">
<nav class="nav">
  <div class="brand">skroli</div>
  {nav}
</nav>
<main class="feed">
  <section id="home" class="view active">
    <div class="head"><h1>Home</h1>
      <span class="count">{len(items)} items</span>
      <button class="iconbtn" title="Refresh feed" onclick="refresh(this)">↻</button></div>
    {posts}
  </section>
  <section id="ingestors" class="view">{_ingestors_page(rss)}</section>
  <section id="enhancers" class="view">{_enhancers_page(score)}</section>
</main>
<aside class="rail">
  <div class="panel"><h3>Sources</h3>{sources or '<div class="srcrow">none yet</div>'}</div>
</aside>
<script>
function show(view, el){{
  document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active', v.id===view));
  document.querySelectorAll('.nav .item').forEach(n=>n.classList.remove('active'));
  el.classList.add('active');
  document.body.classList.toggle('home', view==='home');
}}
async function refresh(btn){{
  btn.disabled=true; btn.classList.add('spin');
  await fetch('/api/refresh',{{method:'POST'}}); location.reload();
}}
function rm(btn){{ btn.closest('.erow').remove(); }}
function _append(id, frag){{
  const w=document.getElementById(id);
  w.insertAdjacentHTML('beforeend', frag);
  const last=w.lastElementChild.querySelector('input'); if(last) last.focus();
}}
function addFeed(){{ _append('feeds',
  '<div class="erow"><input placeholder="https://example.com/feed.xml">'+
  '<button class="x" type="button" onclick="rm(this)">×</button></div>'); }}
function addSub(){{ _append('subs',
  '<div class="erow"><span class="pre">r/</span><input placeholder="subreddit">'+
  '<button class="x" type="button" onclick="rm(this)">×</button></div>'); }}
function addWeight(){{ _append('weights',
  '<div class="erow"><input class="wname" placeholder="Source name">'+
  '<input class="wval" type="number" step="0.1" placeholder="1.0">'+
  '<button class="x" type="button" onclick="rm(this)">×</button></div>'); }}
function _vals(sel){{ return [...document.querySelectorAll(sel)].map(i=>i.value.trim()).filter(Boolean); }}
async function _post(url, body, msgId, btn){{
  btn.disabled=true; const msg=document.getElementById(msgId);
  if(msg) msg.textContent='Saving…';
  await fetch(url,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
  location.reload();
}}
function saveIngestors(btn){{
  _post('/api/ingestors', {{feeds:_vals('#feeds input'), subreddits:_vals('#subs input')}}, 'ing-msg', btn);
}}
function saveEnhancers(btn){{
  const weights={{}};
  document.querySelectorAll('#weights .erow').forEach(r=>{{
    const n=r.querySelector('.wname').value.trim();
    const v=parseFloat(r.querySelector('.wval').value);
    if(n && !isNaN(v)) weights[n]=v;
  }});
  const hl=parseFloat(document.getElementById('halflife').value);
  _post('/api/enhancers', {{half_life_hours:(isNaN(hl)?12:hl), weights}}, 'enh-msg', btn);
}}
</script>
</body></html>"""


class SkroliViewer:
    name = "skroli"

    def __init__(
        self,
        port: int = 4242,
        on_refresh: Callable[[], None] | None = None,
        on_save: Callable[[], None] | None = None,
        rss: RssConfig | None = None,
        score: ScoreConfig | None = None,
    ):
        self.port = port
        self._on_refresh = on_refresh
        self._on_save = on_save
        self._rss = rss or RssConfig()
        self._score = score or ScoreConfig()
        self._items: list[Item] = []
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None

    def render(self, items: list[Item]) -> None:
        with self._lock:
            self._items = list(items)

    def _page(self) -> bytes:
        with self._lock:
            return render_page(self._items, self._rss, self._score).encode("utf-8")

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
                    viewer._rss.feeds = [str(x) for x in data.get("feeds", []) if str(x).strip()]
                    viewer._rss.subreddits = [
                        str(x).strip() for x in data.get("subreddits", []) if str(x).strip()
                    ]
                    if viewer._on_save:
                        viewer._on_save()
                    self._ok()
                elif self.path == "/api/enhancers":
                    data = self._read_json()
                    try:
                        viewer._score.half_life_hours = max(float(data.get("half_life_hours", 12)), 0.1)
                    except (ValueError, TypeError):
                        pass
                    weights: dict[str, float] = {}
                    for k, v in (data.get("weights") or {}).items():
                        try:
                            weights[str(k)] = float(v)
                        except (ValueError, TypeError):
                            continue
                    viewer._score.weights = weights
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
