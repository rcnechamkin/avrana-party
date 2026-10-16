// layer.html's script: the floating Party button and its drawer over a game (AVR-292). It runs in
// a Party-origin frame that a game page mounts (bridge/layer-mount.js), so it reads the Party
// with this phone's own Party credential, which the game page never sees. The page only places
// the frame; every word, name and message is drawn here. Rules: lib/layer.js.
import { hydrateIcons, icon } from './icons.js';
import { h } from './ui.js';
import { avatarNode } from './profile-ui.js';
import { createPartyClient } from './party-client.js';
import { createPartyChat, systemText } from './party-chat.js';
import { locationOf, partyGame, roster } from './party-mode.js';
import { unreadMark } from './frame.js';
import { originAllows } from './bridge.js';
import { ACTION_WORDS, LONG_PRESS_MS, POSITION_KEY, PROTOCOL, SLOP, actions, buttonLabel, connectionLine,
  gesture, initialPlace, layerBox, parseFromPage, settle } from './layer.js';

const $ = (id) => document.getElementById(id);
const game = new URLSearchParams(location.search).get('game');

function kept(store, key) { try { return JSON.parse(globalThis[store].getItem(key)); } catch { return null; } }
function keep(store, key, value) { try { globalThis[store].setItem(key, JSON.stringify(value)); } catch { /* nowhere */ } }

const state = { vp: null, place: null, back: null, parentOrigin: null, origins: null, tab: 'people',
  confirm: null, link: 'ok', catalog: null, said: 0, busy: false };

// ---- talking to the page that mounted us ---------------------------------------------------------
/** Only the page that mounted this frame, once its origin is known to be allowed: the Party's own
 * origin (a same-origin game page) or an origin Party Core registers for this game (ADR 0013). */
async function allowed(origin) {
  if (origin === location.origin) return true;
  if (!state.origins) {
    try {
      const res = await fetch('/party/api/bridge', { cache: 'no-store', credentials: 'same-origin' });
      const body = res.ok ? await res.json() : null;
      state.origins = body && body.origins && typeof body.origins === 'object' ? body.origins : {};
    } catch { state.origins = {}; }
  }
  return originAllows(state.origins, origin, game);
}
const post = (msg) => { if (state.parentOrigin) parent.postMessage({ avrana: PROTOCOL, ...msg }, state.parentOrigin); };

window.addEventListener('message', async (ev) => {
  if (ev.source !== parent || ev.source === window) return;
  const msg = parseFromPage(ev.data);
  if (!msg) return;
  if (state.parentOrigin === null) {
    if (!(await allowed(ev.origin))) return;               // silence for anyone else
    state.parentOrigin = ev.origin;
  } else if (ev.origin !== state.parentOrigin) return;
  const first = !state.vp;
  state.vp = msg;
  for (const side of ['top', 'right', 'bottom', 'left']) document.documentElement.style.setProperty(`--li-${side}`, `${msg.insets[side]}px`);
  if (first) state.place = initialPlace(kept('localStorage', POSITION_KEY), state.vp);
  if (state.view && state.view.me) post({ type: 'place', ...currentPlace() });
});

function currentPlace() {
  const p = state.place;
  return { mode: p.mode, side: p.side, y: Math.round(p.y) };
}

function setPlace(p, { save = true } = {}) {
  state.place = p;
  if (save && p.mode !== 'open') keep('localStorage', POSITION_KEY, { mode: p.mode, side: p.side, y: Math.round(p.y) });
  post({ type: 'place', ...currentPlace() });
  render();
}

// ---- the button: tap opens, long-press drags, a fling tucks it away -----------------------------------
const button = $('layer-button');
let press = null, quietUntil = 0;   // a click right after a drag or a slide is not a tap
button.addEventListener('contextmenu', (e) => e.preventDefault());
button.addEventListener('pointerdown', (e) => {
  if (!state.vp || state.place.mode !== 'button') return;
  const box = layerBox({ type: 'place', ...currentPlace() }, state.vp);
  press = { id: e.pointerId, sx: e.screenX, sy: e.screenY, t: performance.now(), box, dragging: false,
    moved: 0, samples: [], x: box.x, y: box.y };
  try { button.setPointerCapture(e.pointerId); } catch { /* not all pointers */ }
  press.timer = setTimeout(() => {
    if (!press || gesture({ heldMs: LONG_PRESS_MS, moved: press.moved }) !== 'drag' || press.moved > SLOP) return;
    press.dragging = true;
    button.classList.add('lifted');
  }, LONG_PRESS_MS);
});
button.addEventListener('pointermove', (e) => {
  if (!press || e.pointerId !== press.id) return;
  // Screen coordinates: they do not jump as the frame itself moves under the finger.
  const dx = e.screenX - press.sx, dy = e.screenY - press.sy;
  press.moved = Math.max(press.moved, Math.hypot(dx, dy));
  if (!press.dragging) return;
  press.x = press.box.x + dx; press.y = press.box.y + dy;
  press.samples.push({ x: press.x, t: performance.now() });
  if (press.samples.length > 5) press.samples.shift();
  post({ type: 'drag', x: Math.round(press.x), y: Math.round(press.y) });
});
function release(e) {
  if (!press || (e && e.pointerId !== press.id)) return;
  clearTimeout(press.timer);
  const p = press;
  press = null;
  button.classList.remove('lifted');
  if (!p.dragging) { if (p.moved > SLOP) quietUntil = performance.now() + 500; return; }
  quietUntil = performance.now() + 500;
  const s = p.samples, vx = s.length > 1 ? (s.at(-1).x - s[0].x) / Math.max(1, s.at(-1).t - s[0].t) : 0;
  setPlace(settle({ x: p.x, y: p.y, vx }, state.vp));
  if (state.place.mode === 'tab') $('layer-tab').focus({ preventScroll: true });
}
button.addEventListener('pointerup', release);
button.addEventListener('pointercancel', release);
button.addEventListener('click', () => {
  if (performance.now() < quietUntil) return;
  openLayer();
});
$('layer-tab').addEventListener('click', () => {
  setPlace({ mode: 'button', side: state.place.side, y: state.place.y });
  button.focus({ preventScroll: true });
});

// ---- the drawer --------------------------------------------------------------------------------------
function openLayer(tab = null) {
  if (!state.vp || state.place.mode === 'open') return;
  state.back = state.place;
  if (tab) state.tab = tab;
  setPlace({ mode: 'open', side: state.place.side, y: state.place.y }, { save: false });
  $('layer-close').focus({ preventScroll: true });
  syncChat();
}
function closeLayer() {
  if (state.place.mode !== 'open') return;
  state.confirm = null;
  setPlace(state.back || initialPlace(null, state.vp));
  button.focus({ preventScroll: true });
}
$('layer-close').addEventListener('click', closeLayer);
$('layer-backdrop').addEventListener('click', closeLayer);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && state.place && state.place.mode === 'open') { e.preventDefault(); closeLayer(); }
});
$('layer-tabs').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-tab]');
  if (!b) return;
  state.tab = b.dataset.tab;
  render();
  syncChat();
});
$('layer-move').addEventListener('click', () => {
  const back = state.back || state.place;
  state.back = { mode: 'button', side: back.side === 'left' ? 'right' : 'left', y: back.y };
  keep('localStorage', POSITION_KEY, state.back);
  $('layer-confirm-error').textContent = '';
  $('layer-live-note').textContent = `The button is now on the ${state.back.side}.`;
});
$('layer-tuck').addEventListener('click', () => {
  const back = state.back || state.place;
  state.back = { mode: 'tab', side: back.side, y: back.y };
  keep('localStorage', POSITION_KEY, state.back);
  closeLayer();
  $('layer-tab').focus({ preventScroll: true });
});

// ---- the Party ---------------------------------------------------------------------------------------
const client = createPartyClient({ base: '/party/api/', onView, onLink: ({ ok }) => { state.link = ok ? 'ok' : 'offline'; render(); } });
let storageTab;
try { storageTab = window.sessionStorage; } catch { /* unread starts over */ }
const chat = createPartyChat({ base: '/party/api/', storage: storageTab, onChange: renderChat });

function onView(view) {
  state.view = view;
  if (view && view.me) chat.open(view.party, view.me.id); else chat.close();
  if (state.vp && view && view.me && !state.shown) { state.shown = true; post({ type: 'place', ...currentPlace() }); }
  render();
}

function gameName(id) { const g = partyGame(state.catalog, id); return g ? g.name : 'the game'; }

function personItem(m) {
  return h('li', { 'data-away': m.away ? '' : null },
    avatarNode({ avatar: m.avatar || '' }, 'sm'),
    h('span', { class: 'who', text: m.name + (m.me ? ' (you)' : '') }),
    h('span', { class: 'tags' },
      m.host ? h('span', { class: 'avrana-tag', text: 'Host' }) : null,
      m.away ? h('span', { class: 'avrana-tag quiet', text: 'Away' }) : null));
}

function render() {
  const view = state.view, place = state.place;
  const member = Boolean(view && view.me);
  const mode = member && place ? place.mode : null;
  document.documentElement.dataset.mode = mode || 'none';
  button.hidden = mode !== 'button';
  $('layer-tab').hidden = mode !== 'tab';
  $('layer-open').hidden = mode !== 'open';
  if (mode === 'tab') {
    const slot = $('layer-tab');
    slot.replaceChildren(icon(place.side === 'right' ? 'chevron-left' : 'chevron-right'));
    slot.dataset.side = place.side;
  }
  const unread = chat.state().unread;
  button.setAttribute('aria-label', buttonLabel(unread));
  $('layer-unread').textContent = unreadMark(unread);
  if (!member) return;
  const loc = locationOf(view);
  $('layer-where').textContent = loc.at === 'results' ? `${gameName(loc.game)}: the round is over.`
    : loc.game ? `Playing ${gameName(loc.game)}.` : '';
  $('layer-link').textContent = connectionLine({ party: state.link, chat: chat.state().status });
  for (const b of $('layer-tabs').querySelectorAll('button')) b.setAttribute('aria-pressed', String(b.dataset.tab === state.tab));
  $('layer-tab-unread').textContent = unreadMark(unread);
  $('layer-tab-chat').setAttribute('aria-label', unread ? `Chat, ${buttonLabel(unread).replace('Your Party, ', '')}` : 'Chat');
  $('layer-people').hidden = state.tab !== 'people';
  $('chat').hidden = state.tab !== 'chat';
  $('chat-form').hidden = state.tab !== 'chat';
  $('layer-people-list').replaceChildren(...roster(view).map(personItem));
  renderHost(view);
}

function renderHost(view) {
  const offered = actions(view);
  $('layer-host').hidden = offered.length === 0;
  $('layer-actions').replaceChildren(...offered.map((a) => h('button', {
    type: 'button', class: 'btn btn-outline w-full justify-start', 'data-action': a, text: ACTION_WORDS[a].label,
    onclick: () => askConfirm(a),
  })));
  if (state.confirm && !offered.includes(state.confirm)) state.confirm = null;   // the Party moved on
  $('layer-confirm').hidden = !state.confirm;
  $('layer-actions').hidden = Boolean(state.confirm);
}

function askConfirm(action) {
  state.confirm = action;
  const words = ACTION_WORDS[action];
  $('layer-confirm-text').textContent = words.confirm;
  $('layer-yes').textContent = words.yes;
  $('layer-confirm-error').textContent = '';
  const pick = action === 'handover';
  $('layer-pick').hidden = !pick;
  $('layer-pick-label').hidden = !pick;
  if (pick) {
    const v = state.view;
    $('layer-pick').replaceChildren(...v.members
      .filter((m) => m.id !== v.me.id && (m.presence === 'here' || m.presence === 'playing'))
      .map((m) => h('option', { value: m.id, text: m.name })));
  }
  render();
  $('layer-confirm-text').focus({ preventScroll: true });
}
$('layer-no').addEventListener('click', () => {
  const was = state.confirm;
  state.confirm = null;
  render();
  const again = $('layer-actions').querySelector(`[data-action="${was}"]`);
  if (again) again.focus({ preventScroll: true });
});
$('layer-yes').addEventListener('click', async () => {
  if (state.busy || !state.confirm) return;
  state.busy = true;
  $('layer-yes').disabled = true;
  const v = state.view, action = state.confirm;
  let res;
  if (action === 'end') res = await client.end();
  else if (action === 'lobby') res = await client.lobby();
  else if (action === 'handover') res = await client.act('host', { to: $('layer-pick').value, if_version: v.version });
  else res = await client.act('host/spectate', { if_version: v.version });
  state.busy = false;
  $('layer-yes').disabled = false;
  if (res.ok) { state.confirm = null; render(); return; }
  $('layer-confirm-error').textContent = res.error === 'stale' ? 'The Party changed. Have another look and try again.'
    : res.error === 'offline' ? 'Not connected. Nothing changed.' : res.message || 'That did not work. Please try again.';
});

// ---- the chat (the same Party room as Party Home, lib/party-chat.js) -----------------------------------
function renderChat(snapshot) {
  const view = state.view, me = view && view.me ? view.me.id : null;
  $('chat-status').textContent = { connecting: 'Connecting…', unavailable: 'Reconnecting…', not_member: 'Join the Party to chat.' }[snapshot.status] || '';
  $('chat-send').disabled = snapshot.status !== 'connected';
  const pane = $('chat');
  const atEnd = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 40;
  const items = snapshot.messages.map((m) => m.kind === 'system'
    ? h('li', { class: 'avrana-chat-system' }, h('span', { text: systemText(m, (id) => (partyGame(state.catalog, id) || { name: 'The game' }).name) }))
    : h('li', { class: 'avrana-chat-line', 'data-mine': String(m.from === me) },
      avatarNode({ avatar: m.avatar || '' }, 'sm'),
      h('div', { class: 'min-w-0' },
        h('strong', { class: 'text-supporting font-medium text-muted' }, h('bdi', { text: m.from === me ? `${m.name} (you)` : m.name })),
        h('p', { class: 'm-0 whitespace-pre-wrap', dir: 'auto', text: m.text }))));
  if (snapshot.gap) items.unshift(h('li', { class: 'avrana-chat-system', text: 'Earlier messages are gone.' }));
  if (!items.length && snapshot.status === 'connected') items.push(h('li', { class: 'avrana-chat-empty', text: 'No messages yet. Say hello to the Party.' }));
  $('chat-messages').replaceChildren(...items);
  if (atEnd) pane.scrollTop = pane.scrollHeight;
  const showing = state.place && state.place.mode === 'open' && state.tab === 'chat';
  const said = state.said;
  state.said = snapshot.messages.length ? snapshot.messages.at(-1).seq : 0;
  if (showing) {
    const fresh = snapshot.messages.filter((m) => m.kind === 'member' && m.from !== me && m.seq > said);
    if (fresh.length && said) $('chat-live').textContent = `${fresh.at(-1).name}: ${fresh.at(-1).text}`;
    chat.markSeen();
  }
  render();
}
function syncChat() { if (state.place && state.place.mode === 'open' && state.tab === 'chat') chat.markSeen(); }

$('chat-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (state.sending) return;
  state.sending = true;
  $('chat-send').disabled = true;
  const res = await chat.send($('chat-text').value);
  state.sending = false;
  $('chat-send').disabled = chat.state().status !== 'connected';
  if (res.ok) { $('chat-text').value = ''; $('chat-feedback').textContent = ''; $('chat').scrollTop = $('chat').scrollHeight; }
  else $('chat-feedback').textContent = res.message;
});
$('chat-text').addEventListener('input', () => { $('chat-feedback').textContent = ''; });

// ---- start -------------------------------------------------------------------------------------------
async function start() {
  if (parent === window || !game || !/^[a-z][a-z0-9_-]{0,39}$/.test(game)) return;   // only as a mounted layer
  hydrateIcons();
  const note = h('p', { id: 'layer-live-note', class: 'sr-only', 'aria-live': 'polite' });
  document.body.append(note);
  try { const res = await fetch('/party/catalog.json', { credentials: 'same-origin' }); state.catalog = res.ok ? await res.json() : null; } catch { /* names fall back */ }
  parent.postMessage({ avrana: PROTOCOL, type: 'ready' }, '*');   // carries nothing; the answer's origin is checked
  const first = await client.probeRetrying();
  if (first) client.start(first);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { client.poke(); chat.poke(); } });
  window.addEventListener('online', () => { client.poke(); chat.poke(); });
}
start();
