// What both fixture games share: the Party layer, the seat ticket, the socket with reconnects,
// and the probe the measurements read (window.__probe). Query switches (enums only):
//   fw=vanilla|svelte   s=M|R   embed=1 (the game is a frame in a Party page)
import { embeddedBridge, mountConsole } from './mount.js';

const PARTY = 'http://party.cp.test:8370';
// Limited Mode stand-in: the game page served by the Party origin under /g/ (same origin, no game origin).
export const limited = location.origin === PARTY;
const q = new URLSearchParams(location.search);
export const fw = q.get('fw') === 'svelte' ? 'svelte' : 'vanilla';
export const strategy = q.get('s') === 'R' ? 'R' : 'M';
const embedded = q.get('embed') === '1' && parent !== window;

export const probe = window.__probe = {
  raf: 0, ticks: 0, lastTick: 0, missed: 0, wsOpens: 0, reconnects: 0, rejects: [], role: null, ready: false, readyAt: 0,
  events: [], glLost: 0, glRestored: 0, layerOpen: false, frames: [],
};
const log = (type, extra = {}) => probe.events.push({ type, t: Math.round(performance.now()), vis: document.visibilityState, ...extra });
addEventListener('visibilitychange', () => log('visibilitychange'));
addEventListener('pagehide', (e) => {
  log('pagehide', { persisted: e.persisted });
  try { sessionStorage.setItem('cp-last-events', JSON.stringify({ events: probe.events, lastTick: probe.lastTick })); } catch { /* private mode */ }
});
try { probe.previous = JSON.parse(sessionStorage.getItem('cp-last-events')); } catch { probe.previous = null; }
addEventListener('pageshow', (e) => log('pageshow', { persisted: e.persisted }));
addEventListener('freeze', () => log('freeze'));
addEventListener('resume', () => log('resume'));
(function frame(t) { probe.raf += 1; requestAnimationFrame(frame); })();

export const layer = embedded ? embeddedBridge({ partyOrigin: PARTY })
  : mountConsole({ partyOrigin: PARTY, game: document.body.dataset.game, fw, strategy, limited, onOpen: (open) => { probe.layerOpen = open; log(open ? 'layer-open' : 'layer-close'); } });

/** Connect to the game server with a Party ticket; reconnect by itself; renew an expired ticket. */
export function connect(game, onMessage) {
  let ws = null, leaving = false, delay = 250, first = true;
  addEventListener('pagehide', () => { leaving = true; if (ws) ws.close(1000, 'pagehide'); });
  addEventListener('pageshow', (e) => { if (e.persisted) { leaving = false; open(); } });   // back from bfcache
  async function open() {
    let t;
    try { t = await layer.ticket(); } catch (err) { log('ticket-failed', { error: String(err.message) }); setTimeout(open, delay); return; }
    ws = new WebSocket(`ws://${location.host}${limited ? '/g' : ''}/ws/${game}`);
    ws.onopen = () => { probe.wsOpens += 1; if (!first) probe.reconnects += 1; first = false; delay = 250; ws.send(JSON.stringify({ type: 'hello', ticket: t.ticket })); };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'reject') { probe.rejects.push(msg.reason); ws.close(); return; }   // expired: the next open asks for a fresh ticket
      if (msg.type === 'welcome' || msg.type === 'role') { probe.role = msg.role; document.body.dataset.role = msg.role; }
      if (msg.type === 'welcome') { probe.serverOffset = msg.now - Date.now(); probe.you = msg.you; probe.tickets = (probe.tickets || 0) + 1; }
      if (msg.type === 'tick') {
        if (probe.lastTick && msg.t > probe.lastTick + 1) probe.missed += msg.t - probe.lastTick - 1;
        if (msg.t > probe.lastTick) { probe.lastTick = msg.t; probe.ticks += 1; }
      }
      onMessage(msg, ws);
      if (!probe.ready && (msg.type === 'tick' || msg.type === 'state')) {
        probe.ready = true; probe.readyAt = performance.now(); performance.mark('game-ready');
        document.body.dataset.ready = '1';
      }
    };
    ws.onclose = () => { if (leaving) return; log('ws-close'); setTimeout(open, delay); delay = Math.min(delay * 2, 2000); };
  }
  open();
  return { send: (m) => ws && ws.readyState === 1 && ws.send(JSON.stringify(m)) };
}

/** Focus the game's own control on arrival (the R path returns focus here). */
export function focusStage() { const s = document.getElementById('stage'); if (s) s.focus({ preventScroll: true }); }
