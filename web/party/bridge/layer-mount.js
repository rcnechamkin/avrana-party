// The game page's side of the Party layer (`avrana.party-layer/v1`, AVR-292, ADR 0011 amendment
// of 2026-10-16): mount the floating Party button over this game.
//
// Like shim.js this is one file with no imports, so a game repository can vendor it unchanged and
// serve it from its own origin. A same-origin page (today's deployment, and Limited Mode) gets it
// through party-follow.js. Either way the button and its drawer are drawn by a Party-origin frame
// (<party origin>/party/layer.html); this file only places that frame where it asks, inside this
// page's viewport, and tells it the viewport's size and safe areas.
//
//   const layer = mountPartyLayer({ partyOrigin: 'https://party.avrana.net', game: 'bluff' });
//   document.addEventListener('avrana-party-layer', (e) => e.detail.open);   // pause input if you like
//   layer.stop();
//
// A game that mounts it keeps the frame above its own content: no element over it, and no
// element full screen that hides it. It reserves no region; the player moves the button.
export const LAYER_PROTOCOL = 'avrana.party-layer/v1';
export const BUTTON = 52, TAB = { w: 24, h: 60 }, MARGIN = 6;   // the frame around the 48 px button; the tucked tab
const SIDES = ['left', 'right'], MODES = ['button', 'tab', 'open'];
const num = (v) => typeof v === 'number' && Number.isFinite(v);
const keysAre = (o, ...names) => Object.keys(o).sort().join(',') === names.sort().join(',');
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));

/** A message from the layer frame, checked: the message, or null for anything else. */
export function parseLayerMessage(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data) || data.avrana !== LAYER_PROTOCOL) return null;
  if (data.type === 'ready') return keysAre(data, 'avrana', 'type') ? data : null;
  if (data.type === 'place') {
    return keysAre(data, 'avrana', 'type', 'mode', 'side', 'y') && MODES.includes(data.mode)
      && SIDES.includes(data.side) && num(data.y) ? data : null;
  }
  if (data.type === 'drag') return keysAre(data, 'avrana', 'type', 'x', 'y') && num(data.x) && num(data.y) ? data : null;
  return null;
}

/** The frame's box for a request, always inside the viewport. */
export function layerBox(msg, vp) {
  const ins = vp.insets;
  if (msg.type === 'drag') return { x: clamp(msg.x, 0, vp.w - BUTTON), y: clamp(msg.y, 0, vp.h - BUTTON), w: BUTTON, h: BUTTON };
  if (msg.mode === 'open') return { x: 0, y: 0, w: vp.w, h: vp.h };
  const size = msg.mode === 'tab' ? TAB : { w: BUTTON, h: BUTTON };
  const x = msg.mode === 'tab' ? (msg.side === 'left' ? 0 : vp.w - size.w)
    : (msg.side === 'left' ? ins.left + MARGIN : vp.w - ins.right - MARGIN - size.w);
  return { x: clamp(x, 0, vp.w - size.w), y: clamp(msg.y, ins.top + MARGIN, vp.h - ins.bottom - MARGIN - size.h), w: size.w, h: size.h };
}

export function mountPartyLayer({ partyOrigin, game, window: win = globalThis, document: doc = win.document } = {}) {
  if (!/^https?:\/\/[^/]+$/.test(partyOrigin || '')) throw new Error('mountPartyLayer: partyOrigin must be an origin');
  if (typeof game !== 'string' || !/^[a-z][a-z0-9_-]{0,39}$/.test(game)) throw new Error('mountPartyLayer: game must be a game id');
  let stopped = false, open = false, ready = false;

  const frame = doc.createElement('iframe');
  frame.title = 'Your Party';
  frame.setAttribute('allowtransparency', 'true');
  // Its own origin (the Party cookie lives there), scripts and its chat form (submitted to its own
  // script; the Party's CSP keeps form-action 'self'); it may not navigate this page or open windows.
  frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms');
  frame.src = `${partyOrigin}/party/layer.html?game=${encodeURIComponent(game)}`;
  frame.dataset.avranaPartyLayer = 'button';
  Object.assign(frame.style, { position: 'fixed', border: '0', margin: '0', padding: '0', background: 'transparent',
    colorScheme: 'normal', zIndex: '2147483647', left: '0', top: '0', width: BUTTON + 'px', height: BUTTON + 'px',
    visibility: 'hidden' });

  // The page's safe areas, as CSS sees them (needs viewport-fit=cover to be anything but 0).
  const probe = doc.createElement('div');
  Object.assign(probe.style, { position: 'fixed', inset: '0', visibility: 'hidden', pointerEvents: 'none',
    paddingTop: 'env(safe-area-inset-top)', paddingRight: 'env(safe-area-inset-right)',
    paddingBottom: 'env(safe-area-inset-bottom)', paddingLeft: 'env(safe-area-inset-left)' });

  function viewport() {
    const vv = win.visualViewport;
    const cs = win.getComputedStyle ? win.getComputedStyle(probe) : null;
    const px = (v) => Math.max(0, parseFloat(v) || 0);
    return { w: Math.round(vv ? vv.width : win.innerWidth), h: Math.round(vv ? vv.height : win.innerHeight),
      insets: cs ? { top: px(cs.paddingTop), right: px(cs.paddingRight), bottom: px(cs.paddingBottom), left: px(cs.paddingLeft) }
        : { top: 0, right: 0, bottom: 0, left: 0 } };
  }
  let vp = { w: 0, h: 0, insets: { top: 0, right: 0, bottom: 0, left: 0 } };
  let last = null;

  const send = (msg) => { if (frame.contentWindow) frame.contentWindow.postMessage({ avrana: LAYER_PROTOCOL, ...msg }, partyOrigin); };
  function apply(msg) {
    const box = layerBox(msg, vp);
    Object.assign(frame.style, { left: box.x + 'px', top: box.y + 'px', width: box.w + 'px', height: box.h + 'px', visibility: 'visible' });
    const mode = msg.type === 'drag' ? 'drag' : msg.mode;
    frame.dataset.avranaPartyLayer = mode;
    const nowOpen = mode === 'open';
    if (nowOpen !== open) {
      open = nowOpen;   // focus is already in the frame: it opened from a tap or a key there
      if (typeof win.CustomEvent === 'function') doc.dispatchEvent(new win.CustomEvent('avrana-party-layer', { detail: { open } }));
    }
  }
  function onResize() {
    vp = viewport();
    if (ready) send({ type: 'viewport', ...vp });
    if (last) apply(last);
  }
  function onMessage(ev) {
    if (stopped || ev.origin !== partyOrigin || ev.source !== frame.contentWindow) return;
    const msg = parseLayerMessage(ev.data);
    if (!msg) return;
    if (msg.type === 'ready') { ready = true; vp = viewport(); send({ type: 'viewport', ...vp }); return; }
    if (msg.type === 'place') last = msg;
    apply(msg);
  }

  win.addEventListener('message', onMessage);
  win.addEventListener('resize', onResize);
  if (win.visualViewport) win.visualViewport.addEventListener('resize', onResize);
  const root = doc.body || doc.documentElement;
  root.append(probe);
  root.append(frame);
  return {
    frame,
    isOpen: () => open,
    stop() {
      stopped = true;
      win.removeEventListener('message', onMessage);
      win.removeEventListener('resize', onResize);
      if (win.visualViewport) win.visualViewport.removeEventListener('resize', onResize);
      frame.remove(); probe.remove();
      if (open && typeof win.CustomEvent === 'function') doc.dispatchEvent(new win.CustomEvent('avrana-party-layer', { detail: { open: false } }));
      open = false;
    },
  };
}
