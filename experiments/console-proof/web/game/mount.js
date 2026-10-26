// Game-origin side of the experiment's Party layer. It reuses the vendored production file
// (web/party/bridge/layer-mount.js, served at /vendor/ the way Games vendors it) for the protocol
// checks and the frame geometry, and adds the two things this proof needs:
//   frame -> page  navigate {to: 'console'}      strategy R: leave the game for the Party console
//                  ticket {id, ticket, role} | ticket-error {id, error}
//   page -> frame  ticket-request {id}           the game asks the Party frame for its seat ticket
// `navigate` has a fixed target (the Party's console page), never a URL from a message.
import { BUTTON, LAYER_PROTOCOL, layerBox, parseLayerMessage } from '/vendor/layer-mount.js';

const keysAre = (o, ...names) => Object.keys(o).sort().join(',') === names.sort().join(',');
const FW = ['vanilla', 'svelte'], STRATEGIES = ['M', 'R'];

function parseExtra(data) {
  if (!data || typeof data !== 'object' || data.avrana !== LAYER_PROTOCOL) return null;
  if (data.type === 'navigate') return keysAre(data, 'avrana', 'type', 'to') && data.to === 'console' ? data : null;
  if (data.type === 'ticket') return keysAre(data, 'avrana', 'type', 'id', 'ticket', 'role') && typeof data.ticket === 'string' && Number.isInteger(data.id) ? data : null;
  if (data.type === 'ticket-error') return keysAre(data, 'avrana', 'type', 'id', 'error') && Number.isInteger(data.id) ? data : null;
  return null;
}

/** Mount the Party layer frame. Returns {ticket(), frame, isOpen()}. */
export function mountConsole({ partyOrigin, game, fw, strategy, onOpen = () => {} }) {
  if (!FW.includes(fw) || !STRATEGIES.includes(strategy)) throw new Error('bad experiment switch');
  const frame = document.createElement('iframe');
  frame.title = 'Your Party';
  frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms');   // no top navigation, as in production
  frame.src = `${partyOrigin}/party/x/${fw}/layer?game=${game}&s=${strategy}`;
  frame.dataset.avranaPartyLayer = 'button';
  Object.assign(frame.style, { position: 'fixed', border: '0', background: 'transparent', colorScheme: 'dark', zIndex: '2147483647',
    left: '0', top: '0', width: BUTTON + 'px', height: BUTTON + 'px', visibility: 'hidden' });
  const vp = () => ({ w: innerWidth, h: innerHeight, insets: { top: 0, right: 0, bottom: 0, left: 0 } });
  let open = false, ready = false, last = null, seq = 0;
  const waiting = new Map();
  const send = (msg) => frame.contentWindow && frame.contentWindow.postMessage({ avrana: LAYER_PROTOCOL, ...msg }, partyOrigin);
  function apply(msg) {
    if (msg.type === 'hide') { frame.style.visibility = 'hidden'; return; }
    const box = layerBox(msg, vp());
    Object.assign(frame.style, { left: box.x + 'px', top: box.y + 'px', width: box.w + 'px', height: box.h + 'px', visibility: 'visible' });
    const mode = msg.type === 'drag' ? 'button' : msg.mode;
    frame.dataset.avranaPartyLayer = mode;
    const now = mode === 'open';
    if (now !== open) { open = now; onOpen(open); document.dispatchEvent(new CustomEvent('avrana-party-layer', { detail: { open } })); }
  }
  addEventListener('message', (ev) => {
    if (ev.origin !== partyOrigin || ev.source !== frame.contentWindow) return;
    const base = parseLayerMessage(ev.data);
    if (base) {
      if (base.type === 'ready') { ready = true; const v = vp(); send({ type: 'viewport', w: v.w, h: v.h, insets: v.insets }); return; }
      last = base; apply(base); return;
    }
    const extra = parseExtra(ev.data);
    if (!extra) return;
    if (extra.type === 'navigate') {
      performance.mark('leave-game');
      location.assign(`${partyOrigin}/party/x/${fw}/?s=R`);
      return;
    }
    const w = waiting.get(extra.id);
    if (!w) return;
    waiting.delete(extra.id);
    if (extra.type === 'ticket') w.resolve({ ticket: extra.ticket, role: extra.role }); else w.reject(new Error(extra.error));
  });
  addEventListener('resize', () => { if (ready) { const v = vp(); send({ type: 'viewport', w: v.w, h: v.h, insets: v.insets }); } if (last) apply(last); });
  document.body.append(frame);
  const readyP = new Promise((r) => { const t = setInterval(() => { if (ready) { clearInterval(t); r(); } }, 20); });
  return {
    frame, isOpen: () => open,
    async ticket() {
      await readyP;
      const id = ++seq;
      return new Promise((resolve, reject) => {
        waiting.set(id, { resolve, reject });
        send({ type: 'ticket-request', id });
        setTimeout(() => { if (waiting.delete(id)) reject(new Error('timeout')); }, 5000);
      });
    },
  };
}

/** The embedded variant: the game is a frame inside a Party page, which answers ticket requests. */
export function embeddedBridge({ partyOrigin }) {
  let seq = 0; const waiting = new Map();
  addEventListener('message', (ev) => {
    if (ev.origin !== partyOrigin || ev.source !== parent) return;
    const extra = parseExtra(ev.data);
    if (!extra || extra.type === 'navigate') return;
    const w = waiting.get(extra.id); if (!w) return;
    waiting.delete(extra.id);
    if (extra.type === 'ticket') w.resolve({ ticket: extra.ticket, role: extra.role }); else w.reject(new Error(extra.error));
  });
  return {
    frame: null, isOpen: () => false,
    ticket() {
      const id = ++seq;
      return new Promise((resolve, reject) => {
        waiting.set(id, { resolve, reject });
        parent.postMessage({ avrana: LAYER_PROTOCOL, type: 'ticket-request', id }, partyOrigin);
        setTimeout(() => { if (waiting.delete(id)) reject(new Error('timeout')); }, 5000);
      });
    },
  };
}
