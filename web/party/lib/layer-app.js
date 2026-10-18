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
  gesture, keptSpots, nudge, orientationOf, park, parseFromPage, requestFor, spotAt, spotFor, toSpot, unpark } from './layer.js';

const $ = (id) => document.getElementById(id);
const game = new URLSearchParams(location.search).get('game');

function kept(store, key) { try { return JSON.parse(globalThis[store].getItem(key)); } catch { return null; } }
function keep(store, key, value) { try { globalThis[store].setItem(key, JSON.stringify(value)); } catch { /* nowhere */ } }

// mode: 'button' | 'tab' | 'open'. spots: where the button is, per orientation (lib/layer.js).
const state = { vp: null, mode: 'button', spots: {}, parentOrigin: null, origins: null, tab: 'people',
  confirm: null, link: 'ok', catalog: null, said: 0, busy: false };
const spot = () => spotFor(state.spots, state.vp);
const closedMode = () => (spot().parked ? 'tab' : 'button');

// ---- talking to the page that mounted us ---------------------------------------------------------
/** Only the page that mounted this frame, once its origin is known to be allowed: the Party's own
 * origin (a same-origin game page) or an origin Party Core registers for this game (ADR 0013). */
async function allowed(origin) {
  if (origin === location.origin) return true;
  if (!state.origins) {
    let body = null;
    try {
      const res = await fetch('/party/api/bridge', { cache: 'no-store', credentials: 'same-origin' });
      body = res.ok ? await res.json() : null;
    } catch { /* the Wi-Fi blinked */ }
    if (!body || !body.origins || typeof body.origins !== 'object') {
      // Not known yet, so not allowed yet: ask the page to say hello again in a moment. A failure
      // is never kept, or one blip would leave a game origin without its button for the round.
      setTimeout(() => parent.postMessage({ avrana: PROTOCOL, type: 'ready' }, '*'), 3000);
      return false;
    }
    state.origins = body.origins;
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
  state.crossOrigin = state.parentOrigin !== location.origin;
  const first = !state.vp;
  state.vp = msg;
  for (const side of ['top', 'right', 'bottom', 'left']) document.documentElement.style.setProperty(`--li-${side}`, `${msg.insets[side]}px`);
  if (first) state.spots = keptSpots(kept('localStorage', POSITION_KEY));
  if (state.mode !== 'open') state.mode = closedMode();   // a turn of the phone may bring another place
  if (state.view && state.view.me) { state.shown = true; show(); }
});

/** Tell the page where the frame goes: the whole screen when open, else the button or tab. */
function show() {
  if (state.mode === 'open') post({ type: 'place', mode: 'open', side: 'right', y: 0 });
  else post(requestFor(spot(), state.vp));
  render();
}

/** The button is somewhere new (a drag, a nudge, a park, a reset): keep it, for this orientation. */
function setSpot(next) {
  state.spots = { ...state.spots, [orientationOf(state.vp)]: next };
  keep('localStorage', POSITION_KEY, state.spots);
}

// ---- the button: tap opens, long-press drags and it stays where it is let go -------------------------
const button = $('layer-button');
let press = null, quietUntil = 0;   // a click right after a drag is not a tap
button.addEventListener('contextmenu', (e) => e.preventDefault());
button.addEventListener('pointerdown', (e) => {
  if (!state.vp || state.mode !== 'button') return;
  const at = spotAt(spot(), state.vp);
  press = { id: e.pointerId, sx: e.screenX, sy: e.screenY, box: at, dragging: false, moved: 0, x: at.x, y: at.y };
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
  setSpot(toSpot({ x: p.x, y: p.y }, state.vp));   // where the finger let go, kept inside the screen
  show();
}
button.addEventListener('pointerup', release);
button.addEventListener('pointercancel', release);
button.addEventListener('click', () => {
  if (performance.now() < quietUntil) return;
  openLayer();
});
// The arrow keys move the focused button without a drag.
button.addEventListener('keydown', (e) => {
  const dir = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right' }[e.key];
  if (!dir || !state.vp || state.mode !== 'button') return;
  e.preventDefault();
  setSpot(nudge(spot(), dir, state.vp));
  show();
});
$('layer-tab').addEventListener('click', () => {
  setSpot(unpark(spot()));
  state.mode = 'button';
  show();
  button.focus({ preventScroll: true });
});

// ---- the drawer --------------------------------------------------------------------------------------
function openLayer(tab = null) {
  if (!state.vp || state.mode === 'open') return;
  if (tab) state.tab = tab;
  state.mode = 'open';
  show();
  $('layer-close').focus({ preventScroll: true });
  syncChat();
}
function closeLayer() {
  if (state.mode !== 'open') return;
  state.confirm = null;
  state.mode = closedMode();
  show();
  (state.mode === 'tab' ? $('layer-tab') : button).focus({ preventScroll: true });
}
$('layer-close').addEventListener('click', closeLayer);
$('layer-backdrop').addEventListener('click', closeLayer);
document.addEventListener('keydown', (e) => {
  if (state.mode !== 'open') return;
  if (e.key === 'Escape') { e.preventDefault(); closeLayer(); return; }
  if (e.key !== 'Tab') return;
  // aria-modal: Tab and Shift+Tab go round the drawer and never reach the game behind it.
  const all = [...$('layer-sheet').querySelectorAll('button, input, select, [tabindex="0"]')]
    .filter((el) => !el.disabled && el.getClientRects().length > 0);
  if (!all.length) return;
  const at = all.indexOf(document.activeElement);
  if (e.shiftKey && at <= 0) { e.preventDefault(); all.at(-1).focus(); }
  else if (!e.shiftKey && (at === -1 || at === all.length - 1)) { e.preventDefault(); all[0].focus(); }
});
$('layer-tabs').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-tab]');
  if (!b) return;
  state.tab = b.dataset.tab;
  render();
  syncChat();
});
// Moving the button without dragging: the drawer's buttons. It moves when the drawer closes.
const said = (text) => { $('layer-confirm-error').textContent = ''; $('layer-live-note').textContent = text; };
for (const b of document.querySelectorAll('[data-nudge]')) {
  b.addEventListener('click', () => { setSpot(nudge(spot(), b.dataset.nudge, state.vp)); said(`The button moves ${b.dataset.nudge}.`); });
}
for (const side of ['left', 'right']) {
  $(`layer-park-${side}`).addEventListener('click', () => {
    setSpot(park(spot(), side));
    closeLayer();       // parking also closes the drawer: the tab takes focus
  });
}
$('layer-reset').addEventListener('click', () => {
  setSpot({ ...spotFor({}, state.vp) });
  said('The button is back where it started.');
});

// ---- the Party ---------------------------------------------------------------------------------------
const client = createPartyClient({ base: '/party/api/', onView, onLink: ({ ok }) => { state.link = ok ? 'ok' : 'offline'; render(); } });
let storageTab;
try { storageTab = window.sessionStorage; } catch { /* unread starts over */ }
const chat = createPartyChat({ base: '/party/api/', storage: storageTab, onChange: renderChat });

function onView(view) {
  state.view = view;
  if (view && view.me) chat.open(view.party, view.me.id); else chat.close();
  if (state.vp && view && view.me && !state.shown) { state.shown = true; show(); }
  if (!(view && view.me) && state.shown) {
    // No longer a member: hide the frame, or an empty frame would sit over the game.
    state.shown = false;
    if (state.vp && state.mode === 'open') state.mode = closedMode();
    post({ type: 'hide' });
  }
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
  const view = state.view;
  const member = Boolean(view && view.me);
  const mode = member && state.vp ? state.mode : null;
  document.documentElement.dataset.mode = mode || 'none';
  button.hidden = mode !== 'button';
  $('layer-tab').hidden = mode !== 'tab';
  $('layer-open').hidden = mode !== 'open';
  if (mode === 'tab') {
    const slot = $('layer-tab'), side = spot().parked;
    slot.replaceChildren(icon(side === 'right' ? 'chevron-left' : 'chevron-right'));
    slot.dataset.side = side;
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
  const offered = actions(view, { crossOrigin: Boolean(state.crossOrigin) });
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
  const showing = state.mode === 'open' && state.tab === 'chat';
  const said = state.said;
  state.said = snapshot.messages.length ? snapshot.messages.at(-1).seq : 0;
  if (showing) {
    const fresh = snapshot.messages.filter((m) => m.kind === 'member' && m.from !== me && m.seq > said);
    if (fresh.length && said) $('chat-live').textContent = `${fresh.at(-1).name}: ${fresh.at(-1).text}`;
    chat.markSeen();
  }
  render();
}
function syncChat() { if (state.mode === 'open' && state.tab === 'chat') chat.markSeen(); }

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
