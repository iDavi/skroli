/* ----- the app is a browser: everything is a tab ----------------------------
   Tabs are the core navigation. Internal pages (Feed / Ingestors / Enhancers)
   and opened posts are all tabs; the sidebar just opens/focuses them. Tabs can
   be reordered (drag) and closed, and there's always at least one open. */
let tabs = [{ key: 'feed', kind: 'feed', title: 'Feed' }];
let activeKey = 'feed';
const INTERNAL = { home: ['feed', 'Feed'], ingestors: ['ingestors', 'Ingestors'], enhancers: ['enhancers', 'Enhancers'] };

function activeTab(){ return tabs.find(t => t.key === activeKey) || tabs[0]; }

function show(view){                       // sidebar launcher → open/focus a tab
  const [kind, title] = INTERNAL[view] || [];
  if (kind) openInternal(kind, title);
}
function openInternal(kind, title){
  let t = tabs.find(x => x.kind === kind);
  if (!t){ t = { key: kind, kind, title }; tabs.push(t); }
  activeKey = t.key;
  render();
}
function openPage(url, title){
  if (!url) return;
  const key = 'page:' + url;
  if (!tabs.find(t => t.key === key)){
    tabs.push({ key, kind: 'page', title: title || url, url });
    const div = document.createElement('div');
    div.className = 'tabview'; div.dataset.key = key;
    div.innerHTML = '<div class="empty">Opening…</div>';
    document.getElementById('browser').appendChild(div);
    loadPage(key, url, div);
  }
  activeKey = key;
  render();
}
function closeTab(key){
  const i = tabs.findIndex(t => t.key === key);
  if (i < 0) return;
  const t = tabs[i];
  tabs.splice(i, 1);
  if (t.kind === 'page'){
    const d = document.querySelector('#browser .tabview[data-key="' + CSS.escape(key) + '"]');
    if (d) d.remove();
  }
  if (!tabs.length) tabs.push({ key: 'feed', kind: 'feed', title: 'Feed' });
  if (activeKey === key) activeKey = (tabs[Math.max(0, i - 1)] || tabs[0]).key;
  render();
}
function reorder(fromKey, toKey){
  const fi = tabs.findIndex(t => t.key === fromKey), ti = tabs.findIndex(t => t.key === toKey);
  if (fi < 0 || ti < 0 || fi === ti) return;
  const [moved] = tabs.splice(fi, 1);
  tabs.splice(ti, 0, moved);
  render();
}
function render(){
  const at = activeTab();
  document.getElementById('home').classList.toggle('active', at.kind === 'feed');
  document.getElementById('ingestors').classList.toggle('active', at.kind === 'ingestors');
  document.getElementById('enhancers').classList.toggle('active', at.kind === 'enhancers');
  document.getElementById('browser').classList.toggle('active', at.kind === 'page');
  document.querySelectorAll('#browser .tabview').forEach(tv =>
    tv.classList.toggle('active', tv.dataset.key === activeKey));
  const navIndex = { feed: 0, ingestors: 1, enhancers: 2 };
  document.querySelectorAll('.nav .item').forEach((n, i) => n.classList.toggle('active', i === navIndex[at.kind]));
  document.body.classList.toggle('home', at.kind === 'feed');     // rail only on the feed
  document.body.classList.toggle('reading', at.kind === 'page');  // widen for the browser
  renderTabs();
}
function renderTabs(){
  let h = '';
  tabs.forEach(t => {
    h += '<div class="tab' + (t.key === activeKey ? ' active' : '') + '" draggable="true" data-key="' + esc(t.key) + '" title="' + esc(t.title) + '">' +
         '<span class="tlabel">' + esc(t.title) + '</span>' +
         '<span class="tclose" data-close="1">×</span></div>';
  });
  h += '<div class="tabadd" id="tabadd" title="New tab">+</div>';
  document.getElementById('tabs').innerHTML = h;
}
async function loadPage(key, url, div){
  try{
    const d = await (await fetch('/api/open?url=' + encodeURIComponent(url))).json();
    div.innerHTML = browserView(d);
    if (d.mode === 'reader' && d.title){ const t = tabs.find(x => x.key === key); if (t){ t.title = d.title; renderTabs(); } }
  }catch(e){
    div.innerHTML = '<div class="bbar"><a class="act" href="' + esc(url) + '" target="_blank" rel="noopener">open original ↗</a></div>' +
      '<div class="empty">Couldn’t open this page.</div>';
  }
}
function browserView(d){
  const bar = '<div class="bbar"><a class="act" href="' + esc(d.url) + '" target="_blank" rel="noopener">open original ↗</a></div>';
  if (d.mode === 'iframe') return bar + '<iframe class="bframe" src="' + esc(d.url) + '" referrerpolicy="no-referrer"></iframe>';
  if (d.mode === 'reader'){
    const img = d.image ? '<img class="rimg" src="' + esc(d.image) + '" alt="" onerror="this.remove()">' : '';
    const by  = d.byline ? '<div class="rby">' + esc(d.byline) + '</div>' : '';
    return bar + '<article class="reader"><h1>' + esc(d.title) + '</h1>' + by + img +
      '<div class="rbody">' + (d.html || '<p>(no readable content)</p>') + '</div></article>';
  }
  return bar + '<div class="empty">Couldn’t load this page.</div>';
}
let _dragKey = null;
document.addEventListener('DOMContentLoaded', ()=>{
  const bar = document.getElementById('tabs');
  bar.addEventListener('click', e => {
    if (e.target.id === 'tabadd'){ openInternal('feed', 'Feed'); return; }
    const tab = e.target.closest('.tab'); if (!tab) return;
    if (e.target.closest('.tclose')) closeTab(tab.dataset.key);
    else { activeKey = tab.dataset.key; render(); }
  });
  bar.addEventListener('dragstart', e => { const t = e.target.closest('.tab'); if (t) _dragKey = t.dataset.key; });
  bar.addEventListener('dragover', e => e.preventDefault());
  bar.addEventListener('drop', e => {
    e.preventDefault();
    const t = e.target.closest('.tab');
    if (t && _dragKey) reorder(_dragKey, t.dataset.key);
    _dragKey = null;
  });
  document.getElementById('posts').addEventListener('click', e => {
    const link = e.target.closest('[data-open]');
    if (link){ e.stopPropagation(); openPage(link.dataset.open, link.dataset.openTitle || ''); return; }
    const post = e.target.closest('.post');
    if (post && post.dataset.url) openPage(post.dataset.url, post.dataset.title);
  });
  render();
});

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
  return '<article class="post" data-url="'+esc(it.url)+'" data-title="'+esc(it.title)+'"><div class="src '+a.cls+'">'+esc(a.badge)+'</div><div class="body">'+
    '<div class="meta"><span class="name">'+esc(it.source)+'</span>'+
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
      if(!fetching){
        if(msg.origins){   // drop items from sources no longer in the config
          const valid = new Set(msg.origins);
          for(const [id,it] of items){ if(it.origin && !valid.has(it.origin)) items.delete(id); }
        }
        renderFeed();   // fetch finished → one settled update
      }
    }
  };
  ws.onclose = () => setTimeout(connect, 1500);
}
connect();
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
