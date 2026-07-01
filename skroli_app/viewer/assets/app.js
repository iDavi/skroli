/* ----- the app is a browser ------------------------------------------------
   Tab strip = browsing tabs only (feeds, opened pages, source pages). Robust:
   session-persisted, keyboard-driven, reorderable, with per-tab history. */
let tabs = [];
let activeKey = null;
let section = 'browse';   // 'browse' | 'ingestors' | 'enhancers'
let seq = 0;             // monotonic id for unique tab keys
const closedStack = [];  // recently closed tabs, for reopen

function activeTab(){ return tabs.find(t => t.key === activeKey) || tabs[0]; }
function nextTabKey(key){ const i = tabs.findIndex(t => t.key === key); return (i >= 0 && i + 1 < tabs.length) ? tabs[i + 1].key : null; }
function hostOf(u){ try { return new URL(u).hostname; } catch(_){ return ''; } }

/* Native shell mode (PySide6 + QtWebEngine): the native window owns the tab bar,
   so we hide our own web tab strip and open posts/comments as real native tabs
   (window.open → the shell's createWindow). Internal views (feed, source pages,
   config) still navigate inside this web app. */
const SHELL = new URLSearchParams(location.search).get('shell') === '1';
if (SHELL) document.body.classList.add('shell');

/* ---- (1) session persistence ---- */
function saveState(){
  try {
    localStorage.setItem('skroli.tabs', JSON.stringify({
      seq, section, activeKey,
      tabs: tabs.map(t => ({ key:t.key, kind:t.kind, title:t.title, url:t.url,
                             source:t.source, history:t.history, hidx:t.hidx })),
    }));
  } catch(_){}
}
function restore(){
  let s; try { s = JSON.parse(localStorage.getItem('skroli.tabs') || 'null'); } catch(_){ s = null; }
  if (!s || !Array.isArray(s.tabs) || !s.tabs.length) return false;
  seq = s.seq || 0; section = s.section || 'browse';
  s.tabs.forEach(t => { tabs.push(t); mountTab(t); });
  activeKey = tabs.some(t => t.key === s.activeKey) ? s.activeKey : tabs[0].key;
  render(); _lastSig = ''; renderFeed();
  return true;
}
function mountTab(t){   // (re)create a tab's DOM container
  if (t.kind === 'feed') ensureFeedView(t.key);
  else if (t.kind === 'source') ensureSourceView(t.key, t.source);
  else if (t.kind === 'page'){
    const div = document.createElement('div');
    div.className = 'tabview'; div.dataset.key = t.key;
    document.getElementById('browser').appendChild(div);
    if (!t.history) { t.history = [t.url]; t.hidx = 0; }
    t.loading = true; loadPage(t.key, t.url, div);
  }
}

function show(view){      // sidebar: Home goes to the feed; the others are views
  if (view === 'home'){ section = 'browse'; focusOrNewFeed(); }
  else { section = view; render(); }
}
function ensureFeedView(key){
  if (document.querySelector('#feeds .feedview[data-key="'+CSS.escape(key)+'"]')) return;
  const div = document.createElement('div');
  div.className = 'feedview'; div.dataset.key = key;
  div.innerHTML =
    '<div class="head"><h1>Feed</h1><span class="count">0 items</span>'+
    '<button class="iconbtn refreshbtn" title="Refresh feed">'+
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'+
    '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><polyline points="21 3 21 9 15 9"/></svg></button></div>'+
    '<div class="posts"><div class="empty">Loading your feed…</div></div>';
  document.getElementById('feeds').appendChild(div);
}
function newFeed(){
  section = 'browse';
  const key = 'feed:' + (++seq);
  tabs.push({ key, kind: 'feed', title: 'Feed' });
  ensureFeedView(key);
  activeKey = key; render();
  _lastSig = ''; renderFeed();
}
function focusOrNewFeed(){
  const f = tabs.find(t => t.kind === 'feed');
  if (f){ activeKey = f.key; section = 'browse'; render(); } else newFeed();
}
function ensureSourceView(key, source){
  if (document.querySelector('#sourceviews .sourceview[data-key="'+CSS.escape(key)+'"]')) return;
  const div = document.createElement('div');
  div.className = 'sourceview'; div.dataset.key = key; div.dataset.source = source;
  div.innerHTML = '<div class="head"><h1>'+esc(source)+'</h1><span class="count">0 items</span></div>'+
                  '<div class="posts"><div class="empty">No posts from this source yet.</div></div>';
  document.getElementById('sourceviews').appendChild(div);
}
function openSource(source){
  if (!source) return;
  section = 'browse';
  const exist = tabs.find(t => t.kind === 'source' && t.source === source);
  if (exist){ activeKey = exist.key; render(); return; }
  const key = 'source:' + (++seq);
  tabs.push({ key, kind: 'source', title: source, source });
  ensureSourceView(key, source);
  activeKey = key; render(); _lastSig = ''; renderFeed();
}
/* ---- (4) middle/⌘-click → background; (6) per-tab history; (10) dedupe ---- */
function openPage(url, title, opts){
  if (!url) return;
  opts = opts || {};
  if (SHELL){ window.open(url, '_blank'); return; }   // hand off to a native tab
  const exist = tabs.find(t => t.kind === 'page' && t.url === url);
  if (exist && !opts.force){
    if (!opts.background){ section = 'browse'; activeKey = exist.key; render(); }
    return;
  }
  const key = 'page:' + (++seq);
  const tab = { key, kind: 'page', title: title || url, url, history: [url], hidx: 0, loading: true };
  tabs.push(tab);
  const div = document.createElement('div');
  div.className = 'tabview'; div.dataset.key = key;
  document.getElementById('browser').appendChild(div);
  loadPage(key, url, div);
  if (!opts.background){ section = 'browse'; activeKey = key; }
  render();
}
/* ---- (3) reopen-closed stack ---- */
function closeTab(key){
  const i = tabs.findIndex(t => t.key === key);
  if (i < 0) return;
  const t = tabs[i];
  tabs.splice(i, 1);
  const host = { page: '#browser .tabview', feed: '#feeds .feedview', source: '#sourceviews .sourceview' }[t.kind];
  if (host){ const d = document.querySelector(host + '[data-key="' + CSS.escape(key) + '"]'); if (d) d.remove(); }
  closedStack.push({ kind: t.kind, title: t.title, url: t.url, source: t.source, idx: i });
  if (closedStack.length > 25) closedStack.shift();
  if (!tabs.length){ newFeed(); return; }
  if (activeKey === key) activeKey = (tabs[Math.min(i, tabs.length - 1)] || tabs[0]).key;
  render();
}
function reopenClosed(){
  const c = closedStack.pop();
  if (!c) return;
  if (c.kind === 'feed') newFeed();
  else if (c.kind === 'source') openSource(c.source);
  else openPage(c.url, c.title, { force: true });
}
/* ---- (8) context-menu actions ---- */
function closeOthers(key){ tabs.filter(t => t.key !== key).map(t => t.key).forEach(closeTab); }
function closeToRight(key){
  const i = tabs.findIndex(t => t.key === key);
  tabs.slice(i + 1).map(t => t.key).forEach(closeTab);
}
function duplicateTab(key){
  const t = tabs.find(x => x.key === key); if (!t) return;
  if (t.kind === 'page') openPage(t.url, t.title, { force: true });
  else if (t.kind === 'feed') newFeed();
  else if (t.kind === 'source') openSource(t.source);
}
/* ---- (9) reorder with drop-at-end ---- */
function reorder(fromKey, toKey){
  const fi = tabs.findIndex(t => t.key === fromKey);
  if (fi < 0) return;
  const [moved] = tabs.splice(fi, 1);
  let ti = toKey ? tabs.findIndex(t => t.key === toKey) : tabs.length;
  if (ti < 0) ti = tabs.length;
  tabs.splice(ti, 0, moved);
  render();
}
function selectIndex(i){ if (tabs[i]){ section = 'browse'; activeKey = tabs[i].key; render(); } }
function cycleTab(d){
  const i = tabs.findIndex(t => t.key === activeKey);
  const n = ((i < 0 ? 0 : i) + d + tabs.length) % tabs.length;
  selectIndex(n);
}
function render(){
  const browse = section === 'browse';
  const at = activeTab();
  const kind = browse && at ? at.kind : null;
  document.getElementById('feeds').classList.toggle('active', kind === 'feed');
  document.getElementById('sourceviews').classList.toggle('active', kind === 'source');
  document.getElementById('browser').classList.toggle('active', kind === 'page');
  document.getElementById('ingestors').classList.toggle('active', section === 'ingestors');
  document.getElementById('enhancers').classList.toggle('active', section === 'enhancers');
  document.querySelectorAll('#feeds .feedview').forEach(v => v.classList.toggle('active', v.dataset.key === activeKey));
  document.querySelectorAll('#sourceviews .sourceview').forEach(v => v.classList.toggle('active', v.dataset.key === activeKey));
  document.querySelectorAll('#browser .tabview').forEach(v => v.classList.toggle('active', v.dataset.key === activeKey));
  const navSel = section === 'ingestors' ? 1 : section === 'enhancers' ? 2 : 0;
  document.querySelectorAll('.nav .item').forEach((n, i) => n.classList.toggle('active', i === navSel));
  document.body.classList.toggle('home', kind === 'feed');
  document.body.classList.toggle('pageview', kind === 'page');  // full-width page, no rail
  renderTabs();
  saveState();
}
function tabTitle(t){
  // (5) never show a blank tab — fall back to the host, then a generic label.
  const s = (t.title || '').trim();
  if (s) return s;
  if (t.url){ const h = hostOf(t.url); if (h) return h; }
  return t.kind === 'feed' ? 'Feed' : 'Untitled';
}
let _tabSig = '';
function renderTabs(){
  // (1)(7) only rebuild when the strip's visible state actually changed, so
  // favicons don't reload / flicker on every feed update or hover.
  const sig = tabs.map(t => t.key + '|' + tabTitle(t) + '|' + (t.kind === 'page' ? (t.loading ? 'L' : 'F') + hostOf(t.url) : '') +
    '|' + (t.key === activeKey && section === 'browse' ? 'A' : '')).join('§') + '#' + section;
  if (sig === _tabSig){ scrollActiveTabIntoView(); return; }
  _tabSig = sig;
  let h = '';
  tabs.forEach(t => {
    const active = section === 'browse' && t.key === activeKey;
    let icon = '';
    if (t.kind === 'page'){
      const inner = t.loading
        ? '<span class="tspin"></span>'
        : '<img class="tfav" src="https://www.google.com/s2/favicons?domain=' + encodeURIComponent(hostOf(t.url)) + '&sz=32" onerror="this.style.visibility=\'hidden\'">';
      icon = '<span class="ticon">' + inner + '</span>';   // slot only for page tabs
    }
    const label = tabTitle(t);
    const tip = t.url ? label + '\n' + t.url : label;
    h += '<div class="tab' + (active ? ' active' : '') + (t.key === _dragKey ? ' dragging' : '') +
         (t.key === _dropKey ? ' dropbefore' : '') +
         '" draggable="true" data-key="' + esc(t.key) + '" title="' + esc(tip) + '">' +
         icon + '<span class="tlabel">' + esc(label) + '</span>' +
         '<span class="tclose" data-close="1" title="Close">×</span></div>';
  });
  document.getElementById('tabs').innerHTML = h;
  scrollActiveTabIntoView();
}
function scrollActiveTabIntoView(){
  const el = document.querySelector('#tabs .tab.active');
  if (el) el.scrollIntoView({ inline: 'nearest', block: 'nearest' });
}
/* ---- (7) loading spinner + (6) history bar ---- */
function loadPage(key, url, div){
  const tab = tabs.find(t => t.key === key);
  const canBack = tab && tab.hidx > 0;
  const canFwd  = tab && tab.history && tab.hidx < tab.history.length - 1;
  div.innerHTML =
    '<div class="bbar">' +
    '<button class="navbtn" data-nav="back" ' + (canBack ? '' : 'disabled') + ' title="Back">◀</button>' +
    '<button class="navbtn" data-nav="fwd" ' + (canFwd ? '' : 'disabled') + ' title="Forward">▶</button>' +
    '<button class="navbtn" data-nav="reload" title="Reload">↻</button>' +
    '<a class="act" href="' + esc(url) + '" target="_blank" rel="noopener">open original ↗</a></div>' +
    '<div class="bcontent"><iframe class="bframe" sandbox="allow-scripts allow-forms" ' +
    'onload="tabLoaded(\'' + esc(key) + '\')" src="/proxy?url=' + encodeURIComponent(url) + '"></iframe></div>';
  if (tab) tab.loading = true;
}
function tabLoaded(key){ const t = tabs.find(x => x.key === key); if (t){ t.loading = false; renderTabs(); } }
function reloadTab(key){
  const tab = tabs.find(t => t.key === key);
  const div = document.querySelector('#browser .tabview[data-key="' + CSS.escape(key) + '"]');
  if (tab && div) loadPage(key, tab.url, div);
}
function navigateTab(key, url){
  const t = tabs.find(x => x.key === key); if (!t) return;
  t.history = (t.history || [t.url]).slice(0, (t.hidx || 0) + 1);
  t.history.push(url); t.hidx = t.history.length - 1;
  t.url = url; t.title = url; reloadTab(key); renderTabs(); saveState();
}
function goBack(key){ const t = tabs.find(x => x.key === key); if (t && t.hidx > 0){ t.hidx--; t.url = t.history[t.hidx]; reloadTab(key); renderTabs(); saveState(); } }
function goFwd(key){ const t = tabs.find(x => x.key === key); if (t && t.history && t.hidx < t.history.length - 1){ t.hidx++; t.url = t.history[t.hidx]; reloadTab(key); renderTabs(); saveState(); } }

function onPostClick(e){
  if (e.target.closest('.refreshbtn')){ refresh(e.target.closest('.refreshbtn')); return; }
  const src = e.target.closest('[data-source]');
  if (src){ e.stopPropagation(); openSource(src.dataset.source); return; }
  const bg = e.metaKey || e.ctrlKey || e.button === 1;   // open in background tab
  const link = e.target.closest('[data-open]');
  if (link){ e.stopPropagation(); openPage(link.dataset.open, link.dataset.openTitle || '', { background: bg }); return; }
  const post = e.target.closest('.post');
  if (post && post.dataset.url) openPage(post.dataset.url, post.dataset.title, { background: bg });
}

/* ---- (8) tab context menu ---- */
function showTabMenu(key, x, y){
  closeTabMenu();
  const m = document.createElement('div');
  m.className = 'ctxmenu'; m.id = 'ctxmenu';
  m.innerHTML =
    '<button data-a="close">Close</button>' +
    '<button data-a="others">Close others</button>' +
    '<button data-a="right">Close to the right</button>' +
    '<button data-a="dup">Duplicate</button>';
  m.style.left = x + 'px'; m.style.top = y + 'px';
  m.style.visibility = 'hidden';
  document.body.appendChild(m);
  // (6) clamp inside the viewport so the menu never spills off the right/bottom edge.
  const r = m.getBoundingClientRect();
  if (r.right > window.innerWidth) m.style.left = Math.max(0, window.innerWidth - r.width - 4) + 'px';
  if (r.bottom > window.innerHeight) m.style.top = Math.max(0, window.innerHeight - r.height - 4) + 'px';
  m.style.visibility = '';
  m.addEventListener('click', ev => {
    const a = ev.target.dataset.a;
    if (a === 'close') closeTab(key);
    else if (a === 'others') closeOthers(key);
    else if (a === 'right') closeToRight(key);
    else if (a === 'dup') duplicateTab(key);
    closeTabMenu();
  });
}
function closeTabMenu(){ const m = document.getElementById('ctxmenu'); if (m) m.remove(); }

let _dragKey = null;
let _dropKey = null;   // tab the drop indicator sits before (null = end)
document.addEventListener('DOMContentLoaded', ()=>{
  if (!restore()) newFeed();      // (1) restore session, else open one feed
  const bar = document.getElementById('tabs');
  const topbar = document.querySelector('.topbar');
  document.getElementById('tabadd').addEventListener('click', () => newFeed());  // (3) pinned + button
  bar.addEventListener('click', e => {
    const tab = e.target.closest('.tab'); if (!tab) return;
    if (e.target.closest('.tclose')) closeTab(tab.dataset.key);
    else { section = 'browse'; activeKey = tab.dataset.key; render(); }
  });
  // (8) middle-click on a tab: suppress the OS autoscroll/paste, then close on release.
  bar.addEventListener('mousedown', e => { if (e.button === 1 && e.target.closest('.tab')) e.preventDefault(); });
  bar.addEventListener('auxclick', e => {        // middle-click closes a tab
    if (e.button !== 1) return;
    const tab = e.target.closest('.tab'); if (tab){ e.preventDefault(); closeTab(tab.dataset.key); }
  });
  bar.addEventListener('contextmenu', e => {     // (6) right-click menu
    const tab = e.target.closest('.tab'); if (!tab) return;
    e.preventDefault(); showTabMenu(tab.dataset.key, e.clientX, e.clientY);
  });
  // (4) translate vertical wheel into horizontal scrolling of the strip.
  bar.addEventListener('wheel', e => {
    if (e.deltaY === 0) return;
    const max = bar.scrollWidth - bar.clientWidth;
    if (max <= 0) return;
    bar.scrollLeft += e.deltaY;
    e.preventDefault();
  }, { passive: false });
  // (9) drag-reorder with an insertion indicator; the whole topbar is a drop
  // target so releasing over the + button or drag space drops at the end.
  // NB: never re-render the strip during a drag — replacing the dragged node's
  // DOM cancels the browser's drag. We toggle classes on the live elements.
  function markDrop(key){
    if (key === _dropKey) return;
    _dropKey = key;
    bar.querySelectorAll('.tab').forEach(el => el.classList.toggle('dropbefore', el.dataset.key === key));
  }
  topbar.addEventListener('dragstart', e => {
    const t = e.target.closest('.tab');
    if (t){ _dragKey = t.dataset.key; setTimeout(() => t.classList.add('dragging'), 0); }
  });
  topbar.addEventListener('dragend', () => {
    _dragKey = null; _dropKey = null;
    bar.querySelectorAll('.tab').forEach(el => el.classList.remove('dragging', 'dropbefore'));
  });
  topbar.addEventListener('dragover', e => {
    if (!_dragKey) return;
    e.preventDefault();
    const t = e.target.closest('.tab');
    if (t && t.dataset.key !== _dragKey){
      const r = t.getBoundingClientRect();
      markDrop(e.clientX < r.left + r.width / 2 ? t.dataset.key : nextTabKey(t.dataset.key));
    } else if (!t){
      markDrop(null);   // over the + button / drag space → append at end
    }
  });
  topbar.addEventListener('drop', e => {
    e.preventDefault();
    const from = _dragKey, to = _dropKey;
    _dragKey = null; _dropKey = null;
    bar.querySelectorAll('.tab').forEach(el => el.classList.remove('dragging', 'dropbefore'));
    if (from) reorder(from, to);
  });
  document.getElementById('feeds').addEventListener('click', onPostClick);
  document.getElementById('feeds').addEventListener('auxclick', e => { if (e.button === 1) onPostClick(e); });
  document.getElementById('sourceviews').addEventListener('click', onPostClick);
  document.getElementById('sourceviews').addEventListener('auxclick', e => { if (e.button === 1) onPostClick(e); });
  document.getElementById('browser').addEventListener('click', e => {   // (6) history buttons
    const nb = e.target.closest('.navbtn'); if (!nb) return;
    const tv = e.target.closest('.tabview'); const key = tv && tv.dataset.key; if (!key) return;
    if (nb.dataset.nav === 'back') goBack(key);
    else if (nb.dataset.nav === 'fwd') goFwd(key);
    else reloadTab(key);
  });
  document.addEventListener('click', closeTabMenu);
  document.addEventListener('keydown', onKey);   // (2) shortcuts
  // Links inside a proxied (live) page post back here to navigate in the same tab.
  window.addEventListener('message', e => {
    const nav = e.data && e.data.skroliNav;
    if (!nav) return;
    let key = null;
    document.querySelectorAll('#browser .tabview iframe').forEach(f => {
      if (f.contentWindow === e.source){ const tv = f.closest('.tabview'); if (tv) key = tv.dataset.key; }
    });
    if (key) navigateTab(key, nav);
  });
});
/* ---- (2) keyboard shortcuts ---- */
function onKey(e){
  if (e.ctrlKey && e.key === 'Tab'){ e.preventDefault(); cycleTab(e.shiftKey ? -1 : 1); return; }
  const mod = e.metaKey || e.ctrlKey; if (!mod) return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable) return;
  const k = e.key.toLowerCase();
  if (k === 't' && e.shiftKey){ e.preventDefault(); reopenClosed(); }
  else if (k === 't'){ e.preventDefault(); newFeed(); }
  else if (k === 'w'){ e.preventDefault(); closeTab(activeKey); }
  else if (/^[1-9]$/.test(e.key)){ e.preventDefault(); selectIndex(e.key === '9' ? tabs.length - 1 : (+e.key - 1)); }
}

/* ----- live feed over WebSocket ----- */
const items = new Map();
let ready = false;
let fetching = false;
/* Bound memory: the server only streams recent items but never asks us to drop
   aged-out ones, so over a long session the map would grow without limit. Keep
   the newest ITEM_CAP by publish time. */
const ITEM_CAP = 1500;
function pruneItems(){
  if(items.size <= ITEM_CAP) return;
  const ordered = [...items.values()].sort((a,b)=>(b.published_at||0)-(a.published_at||0));
  for(const it of ordered.slice(ITEM_CAP)) items.delete(it.id);
}
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
  const ini = (it.source||'').split(/\s+/).slice(0,2).map(w=>w[0]||'').join('').toUpperCase() || '·';
  return {cls:'', badge:ini};
}
function postHTML(it){
  const a = avatar(it);
  const pct = Math.min(Math.round((it.score||0)*100), 100);
  const media = it.image ? '<div class="media"><img src="'+esc(it.image)+'" alt="" loading="lazy" '+
    'onerror="this.closest(\'.media\').remove()"></div>' : '';
  let eng = '';
  if(it.engagement != null){
    eng += '<span class="dot">·</span><span>▲ '+it.engagement+'</span>';
  }
  const ctxt = (it.comments != null) ? 'comments ('+it.comments+')' : 'comments';
  const comments = it.comments_url
    ? '<span class="act" data-open="'+esc(it.comments_url)+'" data-open-title="'+esc(it.source+' — comments')+'">'+ctxt+'</span>' : '';
  // Hacker News opens on its comments/discussion by default.
  const openUrl = (it.source === 'Hacker News' && it.comments_url) ? it.comments_url : it.url;
  return '<article class="post" data-url="'+esc(openUrl)+'" data-title="'+esc(it.title)+'"><div class="src '+a.cls+'" data-source="'+esc(it.source)+'" title="'+esc(it.source)+'">'+esc(a.badge)+'</div><div class="body">'+
    '<div class="meta"><span class="name" data-source="'+esc(it.source)+'">'+esc(it.source)+'</span>'+
    '<span class="dot">·</span><span>'+relTime(it.published_at)+'</span>'+eng+'</div>'+
    '<div class="title">'+esc(it.title)+'</div>'+
    '<div class="excerpt">'+esc(it.excerpt)+'</div>'+ media +
    '<div class="actions">'+ comments +
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
  const html = arr.length
    ? arr.map(postHTML).join('')
    : '<div class="empty">'+((ready && !fetching) ? 'No items yet. Add feeds in Ingestors, then refresh.' : 'Loading your feed…')+'</div>';
  document.querySelectorAll('#feeds .feedview .posts').forEach(p => p.innerHTML = html);
  document.querySelectorAll('#feeds .feedview .count').forEach(c => c.textContent = arr.length + ' items');
  // Source "profile" pages: same posts, filtered to that source.
  document.querySelectorAll('#sourceviews .sourceview').forEach(v => {
    const mine = arr.filter(it => it.source === v.dataset.source);
    v.querySelector('.posts').innerHTML = mine.length ? mine.map(postHTML).join('')
      : '<div class="empty">No posts from this source right now.</div>';
    v.querySelector('.count').textContent = mine.length + ' items';
  });
  const counts = {};
  arr.forEach(it => counts[it.source] = (counts[it.source]||0)+1);
  const top = Object.entries(counts).sort((a,b)=>b[1]-a[1]);
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
/* One message handler shared by both transports below. */
function handleMessage(msg){
  if(msg.type==='items'){
    // Buffer silently — don't reorder the visible feed while a fetch is running.
    msg.items.forEach(it=>items.set(it.id, it));
    pruneItems();
    if(!fetching) renderFeed();   // cached load / idle update: safe to show now
  } else if(msg.type==='ready'){
    ready = true; renderFeed();
  } else if(msg.type==='status'){
    fetching = !!msg.fetching;
    document.querySelectorAll('.refreshbtn').forEach(b=>b.classList.toggle('spin', fetching));
    if(!fetching){
      if(msg.origins){   // drop items from sources no longer in the config
        const valid = new Set(msg.origins);
        for(const [id,it] of items){ if(it.origin && !valid.has(it.origin)) items.delete(id); }
      }
      renderFeed();   // fetch finished → one settled update
    }
  }
}
/* Direct WebSocket — the fallback when SharedWorker isn't available. */
function connectDirect(){
  const proto = location.protocol==='https:' ? 'wss' : 'ws';
  const ws = new WebSocket(proto+'://'+location.host+'/ws');
  ws.onmessage = ev => handleMessage(JSON.parse(ev.data));
  ws.onclose = () => setTimeout(connectDirect, 1500);
}
/* Preferred: a SharedWorker owns the single WebSocket + item store and fans
   updates out to every tab, so N feed tabs share ONE server connection (see
   issue #7). Falls back to a per-tab WebSocket if SharedWorker is unavailable. */
function startFeed(){
  if(typeof SharedWorker !== 'undefined'){
    try {
      const worker = new SharedWorker('/feed-worker.js', {name:'skroli-feed'});
      worker.port.onmessage = e => handleMessage(e.data);
      worker.onerror = connectDirect;   // worker failed to load → direct WS
      worker.port.start();
      // Let the worker drop our port when this tab goes away.
      addEventListener('pagehide', () => { try { worker.port.postMessage({type:'bye'}); } catch(_){} });
      return;
    } catch(_){ /* fall through to a direct connection */ }
  }
  connectDirect();
}
startFeed();
function refresh(btn){ btn.classList.add('spin'); fetch('/api/refresh', {method:'POST'}); }

/* ----- config forms (generic — rendered from /api/config sections) ----- */
let sections = [];
const X = '<button class="x" type="button" onclick="rm(this)">×</button>';
function rm(btn){ btn.closest('.erow').remove(); }
function _append(id, frag){
  const w = document.getElementById(id);
  w.insertAdjacentHTML('beforeend', frag);
  const last = w.lastElementChild.querySelector('input'); if(last) last.focus();
}
function listId(sid,key){ return 'list_'+sid+'_'+key; }
function listRow(prefix, value){
  const pre = prefix ? '<span class="pre">'+esc(prefix)+'</span>' : '';
  return '<div class="erow">'+pre+'<input value="'+esc(value||'')+'">'+X+'</div>';
}
function weightRow(name, val){
  return '<div class="erow"><input class="wname" list="srclist" value="'+esc(name||'')+'" placeholder="pick or type a source">'+
    '<input class="wval" type="number" step="0.1" value="'+esc(val==null?'':val)+'" placeholder="1.0">'+X+'</div>';
}
function toggleHTML(id,on){ return '<label class="toggle"><span>enabled</span><input type="checkbox" id="'+id+'"'+(on?' checked':'')+'></label>'; }
function addRow(sid,key,prefix){ _append(listId(sid,key), listRow(prefix,'')); }
function addWeight(sid,key){ _append(listId(sid,key), weightRow('','')); }

function fieldHTML(s, f){
  const v = s.values[f.key];
  if(f.kind==='int' || f.kind==='float'){
    const a = (f.min!=null?' min="'+f.min+'"':'')+(f.max!=null?' max="'+f.max+'"':'')+(f.step!=null?' step="'+f.step+'"':'');
    return '<div class="col"><h4>'+esc(f.label||f.key)+'</h4>'+
      '<div class="kv"><span></span><input data-f="'+f.key+'" type="number"'+a+' value="'+esc(v)+'"></div></div>';
  }
  if(f.kind==='list'){
    const rows = (v||[]).map(x=>listRow(f.prefix, x)).join('');
    let imp = '';
    if(f.action){
      imp = '<div class="erow" style="border:0;margin-top:10px;padding:0">'+
        (f.prefix?'<span class="pre">'+esc(f.prefix)+'</span>':'')+
        '<input id="imp_'+s.id+'_'+f.key+'" placeholder="username to import everyone they follow">'+
        '<button class="x" type="button" style="width:auto;padding:0 12px;white-space:nowrap" '+
        "onclick=\"doAction('"+s.id+"','"+f.key+"','"+f.action+"',this)\">import following</button></div>"+
        '<span class="savemsg" id="impmsg_'+s.id+'_'+f.key+'"></span>';
    }
    return '<div class="col"><h4>'+esc(f.label||f.key)+'</h4>'+
      '<div id="'+listId(s.id,f.key)+'" data-list="'+f.key+'" data-prefix="'+esc(f.prefix||'')+'">'+rows+'</div>'+
      '<button class="addbtn" type="button" onclick="addRow(\''+s.id+'\',\''+f.key+'\',\''+esc(f.prefix||'')+'\')">+ add</button>'+imp+'</div>';
  }
  if(f.kind==='weights'){
    const rows = Object.entries(v||{}).map(([n,wv])=>weightRow(n,wv)).join('');
    return '<div class="col"><h4>'+esc(f.label||f.key)+'</h4>'+
      '<div id="'+listId(s.id,f.key)+'" data-weights="'+f.key+'">'+rows+'</div>'+
      '<button class="addbtn" type="button" onclick="addWeight(\''+s.id+'\',\''+f.key+'\')">+ add weight</button></div>';
  }
  return '';
}
function cardHTML(s){
  let title = '<div class="ctitle">'+esc(s.title)+' <span class="pill">built-in</span>';
  const cols = [];
  s.fields.forEach(f=>{
    if(f.kind==='toggle'){ title += toggleHTML('en_'+s.id, !!s.values[f.key]); }
    else { cols.push(fieldHTML(s,f)); }
  });
  title += '</div>';
  return '<div class="card" data-id="'+s.id+'">'+title+
    '<div class="desc">'+esc(s.desc)+'</div>'+
    '<div class="cols">'+cols.join('')+'</div>'+
    '<div class="saverow"><button class="savebtn" type="button" onclick="saveSection(this)">Save &amp; refresh</button>'+
    '<span class="savemsg" id="msg_'+s.id+'"></span></div></div>';
}
function renderConfig(){
  const ing = sections.filter(s=>s.group==='ingestor').map(cardHTML).join('');
  const enh = sections.filter(s=>s.group==='enhancer').map(cardHTML).join('');
  document.getElementById('ingestors').innerHTML = '<div class="head"><h1>Ingestors</h1></div><div class="page">'+ing+'</div>';
  document.getElementById('enhancers').innerHTML = '<div class="head"><h1>Enhancers</h1></div><div class="page">'+enh+'</div>';
}
function saveSection(btn){
  const card = btn.closest('.card'); const id = card.dataset.id;
  const s = sections.find(x=>x.id===id); const values = {};
  s.fields.forEach(f=>{
    if(f.kind==='toggle'){ values[f.key] = card.querySelector('#en_'+id).checked; }
    else if(f.kind==='int' || f.kind==='float'){ const n = parseFloat(card.querySelector('[data-f="'+f.key+'"]').value); values[f.key] = isNaN(n)?0:n; }
    else if(f.kind==='list'){ values[f.key] = [...card.querySelectorAll('[data-list="'+f.key+'"] input')].map(i=>i.value.trim()).filter(Boolean); }
    else if(f.kind==='weights'){ const w={}; card.querySelectorAll('[data-weights="'+f.key+'"] .erow').forEach(r=>{ const n=r.querySelector('.wname').value.trim(); const vv=parseFloat(r.querySelector('.wval').value); if(n&&!isNaN(vv)) w[n]=vv; }); values[f.key]=w; }
  });
  const msg = document.getElementById('msg_'+id); if(msg) msg.textContent = 'Saving…';
  btn.disabled = true;
  fetch('/api/save', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id, values})}).then(()=>location.reload());
}
async function doAction(sid, key, action, btn){
  const inp = document.getElementById('imp_'+sid+'_'+key); const u = inp.value.trim().replace(/^@/,'');
  const msg = document.getElementById('impmsg_'+sid+'_'+key);
  if(!u){ if(msg) msg.textContent='enter a username first'; return; }
  btn.disabled = true; if(msg) msg.textContent='importing…';
  const res = await fetch('/api/action', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action, payload:{username:u}})});
  const data = await res.json();
  const cont = document.getElementById(listId(sid,key)); const prefix = cont.dataset.prefix||'';
  const have = new Set([...cont.querySelectorAll('input')].map(i=>i.value.trim().toLowerCase()));
  let added = 0;
  (data.users||[]).forEach(name=>{ if(!have.has(name.toLowerCase())){ cont.insertAdjacentHTML('beforeend', listRow(prefix,name)); have.add(name.toLowerCase()); added++; } });
  btn.disabled = false; inp.value='';
  if(msg) msg.textContent = added ? ('added '+added+' — review, then Save & refresh') : 'no new profiles found';
}
fetch('/api/config').then(r=>r.json()).then(d=>{ sections = d.sections||[]; renderConfig(); });
