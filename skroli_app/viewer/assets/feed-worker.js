/* Shared feed connection (issue #7).

   All skroli feed tabs of the same origin share this one SharedWorker, which
   holds the single WebSocket to the server and the canonical item store, and
   fans every update out to each connected tab's port. So opening N feed tabs
   creates ONE server connection and ONE fetch/enhance load — not N.

   New tabs are caught up from the store immediately (no per-tab reconnect), and
   the DOM rendering still happens per tab (each has its own document). */

const ports = [];
const items = new Map();       // id -> item (canonical, shared across tabs)
let ready = false;
let lastStatus = null;         // replayed to tabs that connect later
let ws = null;

const WORKER_CAP = 2000;       // hard bound on the shared store

function post(port, msg){ try { port.postMessage(msg); } catch (_){} }
function broadcast(msg){ for (const p of ports) post(p, msg); }

function prune(){
  if (items.size <= WORKER_CAP) return;
  const ordered = [...items.values()].sort((a, b) => (b.published_at || 0) - (a.published_at || 0));
  for (const it of ordered.slice(WORKER_CAP)) items.delete(it.id);
}

function connect(){
  const proto = self.location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(proto + '://' + self.location.host + '/ws');
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'items'){
      msg.items.forEach((it) => items.set(it.id, it));
      prune();
    } else if (msg.type === 'ready'){
      ready = true;
    } else if (msg.type === 'status'){
      lastStatus = msg;
      if (msg.fetching === false && msg.origins){
        const valid = new Set(msg.origins);
        for (const [id, it] of items){ if (it.origin && !valid.has(it.origin)) items.delete(id); }
      }
    }
    broadcast(msg);   // forward the raw message to every tab
  };
  ws.onclose = () => { ws = null; setTimeout(connect, 1500); };
  ws.onerror = () => { try { ws.close(); } catch (_){} };
}

self.onconnect = (e) => {
  const port = e.ports[0];
  ports.push(port);
  port.onmessage = (ev) => {
    if (ev.data && ev.data.type === 'bye'){
      const i = ports.indexOf(port);
      if (i >= 0) ports.splice(i, 1);
    }
  };
  port.start();
  // Catch this tab up with the current shared state — no new server connection.
  if (items.size) port.postMessage({ type: 'items', items: [...items.values()] });
  if (ready) port.postMessage({ type: 'ready' });
  if (lastStatus) port.postMessage(lastStatus);
};

connect();
