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
  _save('/api/ingestors', {enabled:document.getElementById('rss-enabled').checked,
    feeds:_vals('#feeds input'), subreddits:_vals('#subs input'),
    letterboxd:_vals('#letterboxd input')}, 'ing-msg', btn);
}
function saveHackernews(btn){
  const c = parseInt(document.getElementById('hncount').value);
  _save('/api/hackernews', {enabled:document.getElementById('hn-enabled').checked,
    count:(isNaN(c)?0:c)}, 'hn-msg', btn);
}
function saveEnhancers(btn){
  const weights = {};
  document.querySelectorAll('#weights .erow').forEach(r=>{
    const n = r.querySelector('.wname').value.trim();
    const v = parseFloat(r.querySelector('.wval').value);
    if(n && !isNaN(v)) weights[n] = v;
  });
  const hl = parseFloat(document.getElementById('halflife').value);
  _save('/api/enhancers', {enabled:document.getElementById('score-enabled').checked,
    half_life_hours:(isNaN(hl)?12:hl), weights}, 'enh-msg', btn);
}
function saveEngagement(btn){
  const w = parseFloat(document.getElementById('engweight').value);
  const c = parseInt(document.getElementById('engcap').value);
  _save('/api/engagement', {enabled:document.getElementById('eng-enabled').checked,
    weight:(isNaN(w)?0:w), cap:(isNaN(c)?2000:c)}, 'eng2-msg', btn);
}
