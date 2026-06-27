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
.kv{display:flex;justify-content:space-between;padding:9px 0;
 border-bottom:1px solid var(--olive-line);font-size:14px;color:var(--parchment-dim)}
.kv:last-child{border-bottom:0}
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

# Client logic kept as a plain string (real braces) so we don't fight f-string
# escaping. Streams items in over the WebSocket and renders the feed client-side.
SCRIPT = """
function show(view, el){
  document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active', v.id===view));
  document.querySelectorAll('.nav .item').forEach(n=>n.classList.remove('active'));
  el.classList.add('active');
  document.body.classList.toggle('home', view==='home');
}

/* ----- live feed over WebSocket ----- */
const items = new Map();
let ready = false;
let fetching = false;
function esc(s){ const d=document.createElement('div'); d.textContent = (s==null?'':s); return d.innerHTML; }
function relTime(ts){
  const s = Date.now()/1000 - ts;
  if(s<60) return 'now';
  if(s<3600) return Math.floor(s/60)+'m';
  if(s<86400) return Math.floor(s/3600)+'h';
  return Math.floor(s/86400)+'d';
}
function avatar(it){
  if(it.is_reddit) return {cls:'reddit', badge:'r/'};
  const ini = (it.source||'').split(/\\s+/).slice(0,2).map(w=>w[0]||'').join('').toUpperCase() || '·';
  return {cls:'', badge:ini};
}
function postHTML(it){
  const a = avatar(it);
  const pct = Math.min(Math.round((it.score||0)*100), 100);
  const media = it.image ? '<div class="media"><img src="'+esc(it.image)+'" alt="" loading="lazy" '+
    'onerror="this.closest(\\'.media\\').remove()"></div>' : '';
  let eng = '';
  if(it.engagement != null){
    eng += '<span class="dot">·</span><span>▲ '+it.engagement+'</span>';
  }
  const ctxt = (it.comments != null) ? 'comments ('+it.comments+')' : 'comments';
  const comments = it.comments_url
    ? '<a class="act" href="'+esc(it.comments_url)+'" target="_blank" rel="noopener">'+ctxt+'</a>' : '';
  return '<article class="post"><div class="src '+a.cls+'">'+esc(a.badge)+'</div><div class="body">'+
    '<div class="meta"><span class="name">'+esc(it.source)+'</span>'+
    '<span class="dot">·</span><span>'+relTime(it.published_at)+'</span>'+eng+'</div>'+
    '<div class="title">'+esc(it.title)+'</div>'+
    '<div class="excerpt">'+esc(it.excerpt)+'</div>'+ media +
    '<div class="actions"><a class="act" href="'+esc(it.url)+'" target="_blank" rel="noopener">↗ open</a>'+ comments +
    '<span class="score">score <b>'+(it.score||0).toFixed(2)+'</b>'+
    '<span class="meter"><i style="width:'+pct+'%"></i></span></span></div></div></article>';
}
let _lastSig = '';
function renderFeed(){
  const arr = [...items.values()].sort((a,b)=>(b.score||0)-(a.score||0));
  // Skip the rebuild entirely if nothing visible actually changed (avoids flicker).
  const sig = arr.map(it=>it.id+':'+(it.score||0)).join(',') + '|' + ready + '|' + fetching;
  if(sig === _lastSig) return;
  _lastSig = sig;
  const feed = document.getElementById('posts');
  if(arr.length===0){
    feed.innerHTML = (ready && !fetching)
      ? '<div class="empty">No items yet. Add feeds in Ingestors, then refresh.</div>'
      : '<div class="empty">Loading your feed…</div>';
  } else {
    feed.innerHTML = arr.map(postHTML).join('');
  }
  document.getElementById('count').textContent = arr.length + ' items';
  const counts = {};
  arr.forEach(it => counts[it.source] = (counts[it.source]||0)+1);
  const top = Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,8);
  document.getElementById('sources').innerHTML = top.length
    ? top.map(([s,n])=>'<a class="srcrow"><span>'+esc(s)+'</span><span class="c">'+n+'</span></a>').join('')
    : '<div class="srcrow">none yet</div>';
  // Keep the source-weight combobox suggestions in sync with what's in the feed.
  const dl = document.getElementById('srclist');
  if(dl){
    const names = [...new Set([...items.values()].map(i=>i.source))].sort();
    dl.innerHTML = names.map(s=>'<option value="'+esc(s)+'">').join('');
  }
}
function connect(){
  const proto = location.protocol==='https:' ? 'wss' : 'ws';
  const ws = new WebSocket(proto+'://'+location.host+'/ws');
  ws.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if(msg.type==='items'){
      // Buffer silently — don't reorder the visible feed while a fetch is running.
      msg.items.forEach(it=>items.set(it.id, it));
      if(!fetching) renderFeed();   // cached load / idle update: safe to show now
    } else if(msg.type==='ready'){
      ready = true; renderFeed();
    } else if(msg.type==='status'){
      fetching = !!msg.fetching;
      document.getElementById('refresh').classList.toggle('spin', fetching);
      if(!fetching) renderFeed();   // fetch finished → one settled update
    }
  };
  ws.onclose = () => setTimeout(connect, 1500);
}
connect();
function refresh(btn){ btn.classList.add('spin'); fetch('/api/refresh', {method:'POST'}); }

/* ----- config editing ----- */
function rm(btn){ btn.closest('.erow').remove(); }
function _append(id, frag){
  const w = document.getElementById(id);
  w.insertAdjacentHTML('beforeend', frag);
  const last = w.lastElementChild.querySelector('input'); if(last) last.focus();
}
function addFeed(){ _append('feeds',
  '<div class="erow"><input placeholder="https://example.com/feed.xml">'+
  '<button class="x" type="button" onclick="rm(this)">×</button></div>'); }
function addSub(){ _append('subs',
  '<div class="erow"><span class="pre">r/</span><input placeholder="subreddit">'+
  '<button class="x" type="button" onclick="rm(this)">×</button></div>'); }
function addWeight(){ _append('weights',
  '<div class="erow"><input class="wname" list="srclist" placeholder="pick or type a source">'+
  '<input class="wval" type="number" step="0.1" placeholder="1.0">'+
  '<button class="x" type="button" onclick="rm(this)">×</button></div>'); }
function addLb(value){ _append('letterboxd',
  '<div class="erow"><span class="pre">@</span><input value="'+(value?esc(value):'')+'" placeholder="username">'+
  '<button class="x" type="button" onclick="rm(this)">×</button></div>'); }
async function importFollowing(btn){
  const u = document.getElementById('lb-import').value.trim().replace(/^@/,'');
  const msg = document.getElementById('lb-import-msg');
  if(!u){ if(msg) msg.textContent='enter a username first'; return; }
  btn.disabled = true; if(msg) msg.textContent = 'importing…';
  const res = await fetch('/api/letterboxd-following', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:u})});
  const data = await res.json();
  const have = new Set(_vals('#letterboxd input').map(s=>s.toLowerCase()));
  let added = 0;
  (data.users||[]).forEach(name=>{ if(!have.has(name.toLowerCase())){ addLb(name); have.add(name.toLowerCase()); added++; } });
  btn.disabled = false;
  if(msg) msg.textContent = added ? ('added '+added+' — review, then Save & refresh') : 'no new profiles found';
  document.getElementById('lb-import').value = '';
}
function _vals(sel){ return [...document.querySelectorAll(sel)].map(i=>i.value.trim()).filter(Boolean); }
async function _save(url, body, msgId, btn){
  btn.disabled = true; const msg = document.getElementById(msgId);
  if(msg) msg.textContent = 'Saving…';
  await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  location.reload();
}
function saveIngestors(btn){
  _save('/api/ingestors', {feeds:_vals('#feeds input'), subreddits:_vals('#subs input'),
    letterboxd:_vals('#letterboxd input')}, 'ing-msg', btn);
}
function saveHackernews(btn){
  const c = parseInt(document.getElementById('hncount').value);
  _save('/api/hackernews', {count:(isNaN(c)?0:c)}, 'hn-msg', btn);
}
function saveEnhancers(btn){
  const weights = {};
  document.querySelectorAll('#weights .erow').forEach(r=>{
    const n = r.querySelector('.wname').value.trim();
    const v = parseFloat(r.querySelector('.wval').value);
    if(n && !isNaN(v)) weights[n] = v;
  });
  const hl = parseFloat(document.getElementById('halflife').value);
  _save('/api/enhancers', {half_life_hours:(isNaN(hl)?12:hl), weights}, 'enh-msg', btn);
}
function saveEngagement(btn){
  const w = parseFloat(document.getElementById('engweight').value);
  const c = parseInt(document.getElementById('engcap').value);
  _save('/api/engagement', {weight:(isNaN(w)?0:w), cap:(isNaN(c)?2000:c)}, 'eng2-msg', btn);
}
"""


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


def _ingestors_page(config: Config) -> str:
    rss = config.rss
    feeds = "".join(_feed_row(u) for u in rss.feeds)
    subs = "".join(_sub_row(s.removeprefix("r/").strip("/")) for s in rss.subreddits)
    lb = "".join(_lb_row(u.lstrip("@")) for u in rss.letterboxd)
    return f"""
    <div class="head"><h1>Ingestors</h1></div>
    <div class="page">
      <div class="card">
        <div class="ctitle">RSS <span class="pill">built-in · always on</span></div>
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
        <div class="cols" style="margin-top:16px">
          <div class="col"><h4>Letterboxd profiles</h4>
            <div id="letterboxd">{lb}</div>
            <button class="addbtn" type="button" onclick="addLb()">+ add profile</button>
            <div class="erow" style="border:0;margin-top:10px;padding:0">
              <span class="pre">@</span>
              <input id="lb-import" placeholder="username to import following from">
              <button class="x" type="button" style="width:auto;padding:0 10px;white-space:nowrap"
                onclick="importFollowing(this)">import</button>
            </div>
            <span class="savemsg" id="lb-import-msg"></span>
          </div>
          <div class="col"></div>
        </div>
        <div class="saverow">
          <button class="savebtn" type="button" onclick="saveIngestors(this)">Save &amp; refresh</button>
          <span class="savemsg" id="ing-msg"></span>
        </div>
      </div>

      <div class="card">
        <div class="ctitle">Hacker News <span class="pill">built-in</span></div>
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
        <div class="ctitle">Score <span class="pill">built-in</span></div>
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
        <div class="ctitle">Engagement <span class="pill">built-in</span></div>
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
      <span class="count" id="count">0 items</span>
      <button class="iconbtn" id="refresh" title="Refresh feed" onclick="refresh(this)">↻</button></div>
    <div id="posts"><div class="empty">Loading your feed…</div></div>
  </section>
  <section id="ingestors" class="view">{_ingestors_page(config)}</section>
  <section id="enhancers" class="view">{_enhancers_page(config)}</section>
</main>
<aside class="rail">
  <div class="panel"><h3>Sources</h3><div id="sources"><div class="srcrow">none yet</div></div></div>
</aside>
<datalist id="srclist"></datalist>
<script>{SCRIPT}</script>
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

            def do_GET(self):
                if self.path == "/ws":
                    self._serve_ws()
                elif self.path in ("/", "/index.html"):
                    body = viewer._page()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
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
