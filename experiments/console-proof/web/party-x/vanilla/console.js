// The vanilla console (AVR-762 experiment), written the way web/party/lib/layer-app.js is: static
// markup in index.html, state in one object, render() replaces the dynamic parts with h(), and the
// real web/party/lib modules for DOM helpers, avatars, roster, library words and the layer protocol.
import { h } from '/party/lib/ui.js';
import { hydrateIcons } from '/party/lib/icons.js';
import { avatarNode } from '/party/lib/profile-ui.js';
import { roster } from '/party/lib/party-mode.js';
import { seatsPhrase } from '/party/lib/library.js';
import { parseFromPage } from '/party/lib/layer.js';
import { FIXTURE_NOTE, GAME_ORIGIN, LAYER_PROTOCOL, TABS, api, attentionText, gameUrl, parseTicketRequest, shellOf, whereLine } from '/party/x/shared/rules.js';
import { renderSuggestions } from './suggestions.js';

const $ = (id) => document.getElementById(id);
const shell = shellOf(location);
const inLayer = shell.shell === 'layer' && parent !== window;
const state = { view: null, catalog: [], suggestions: [], tab: 'home', open: !inLayer, vp: null, offset: 0, busy: false };

// ---- the page that mounted this frame (layer shell only) ---------------------------------------------
const post = (msg) => parent.postMessage({ avrana: LAYER_PROTOCOL, ...msg }, GAME_ORIGIN);
if (inLayer) {
  window.addEventListener('message', async (ev) => {
    if (ev.source !== parent || ev.origin !== GAME_ORIGIN) return;          // only the registered game origin
    const vp = parseFromPage(ev.data);
    if (vp) { const first = !state.vp; state.vp = vp; if (first) place(); render(); return; }
    const req = parseTicketRequest(ev.data);
    if (!req) return;
    const body = await api('/api/ticket', { game: shell.game });
    post(body ? { type: 'ticket', id: req.id, ticket: body.ticket, role: body.role } : { type: 'ticket-error', id: req.id, error: 'unavailable' });
  });
}
function place() {
  if (state.open) post({ type: 'place', mode: 'open', side: 'right', y: 0 });
  else post({ type: 'place', mode: 'button', side: 'right', y: Math.round(state.vp.h / 3) });
}

// ---- open, close, back to the game ---------------------------------------------------------------------
function openConsole() {
  if (!inLayer || state.open) return;
  if (shell.strategy === 'R') { post({ type: 'navigate', to: 'console' }); return; }   // the restore path leaves the game
  state.open = true;
  place();
  render();
  enter();
  $('close').focus({ preventScroll: true });
  refresh();
}
function closeConsole() {
  if (!inLayer || !state.open) return;
  state.open = false;
  place();
  render();
  $('layer-button').focus({ preventScroll: true });
}
function backToGame() {
  if (inLayer) { closeConsole(); return; }
  const url = gameUrl(state.view, shell.fw, shell.strategy);
  if (url) location.assign(url);
}
function enter() {                     // the sheet's entrance; prefers-reduced-motion turns the transition off in CSS
  const sheet = $('sheet');
  sheet.setAttribute('data-entering', '');
  requestAnimationFrame(() => requestAnimationFrame(() => sheet.removeAttribute('data-entering')));
}

$('layer-button').addEventListener('click', openConsole);
$('close').addEventListener('click', closeConsole);
$('backdrop').addEventListener('click', closeConsole);
$('back-to-game').addEventListener('click', backToGame);
document.addEventListener('keydown', (e) => {
  if (!inLayer || !state.open) return;
  if (e.key === 'Escape') { e.preventDefault(); closeConsole(); return; }
  if (e.key !== 'Tab') return;
  const all = [...$('sheet').querySelectorAll('button, input, select, [tabindex="0"]')].filter((el) => !el.disabled && el.getClientRects().length > 0);
  if (!all.length) return;
  const at = all.indexOf(document.activeElement);
  if (e.shiftKey && at <= 0) { e.preventDefault(); all.at(-1).focus(); }
  else if (!e.shiftKey && (at === -1 || at === all.length - 1)) { e.preventDefault(); all[0].focus(); }
});
$('tabs').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-tab]');
  if (!b) return;
  state.tab = b.dataset.tab;
  render();
});

// ---- the Party -----------------------------------------------------------------------------------------
async function refresh() {
  const [view, sugg] = await Promise.all([api('/api/view'), api('/api/suggestions')]);
  if (view) { state.view = view; state.offset = view.now - Date.now(); }
  if (sugg) state.suggestions = sugg.suggestions;
  render();
}
async function act(path, body) {
  if (state.busy) return;
  state.busy = true;
  const res = await api(path, body);
  state.busy = false;
  if (res) state.suggestions = res.suggestions;
  render();
}

/** Re-rendering a list replaces its buttons; put focus back on the one with the same data-key. */
function keepFocus(fn) {
  const key = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.key : null;
  fn();
  if (!key || document.activeElement.dataset.key === key) return;
  const again = document.querySelector(`[data-key="${CSS.escape(key)}"]`);
  if (again && !again.disabled) again.focus({ preventScroll: true });
}

function render() { keepFocus(draw); }
function draw() {
  const member = Boolean(state.view && state.view.me);
  $('layer-button').hidden = !(inLayer && state.vp && !state.open && member);
  $('console').hidden = !state.open || !member;
  $('layer-unread').textContent = member && state.view.attention.length ? String(state.view.attention.length) : '';
  if (!member || !state.open) return;
  const view = state.view, me = view.me;
  $('where').textContent = whereLine(view, state.catalog);
  $('attention').replaceChildren(...view.attention.map((a) => h('li', { 'data-kind': a.kind, text: attentionText(a, Date.now() + state.offset, state.catalog) })));
  for (const b of $('tabs').children) b.setAttribute('aria-pressed', String(state.tab === b.dataset.tab));
  for (const t of TABS) $(`panel-${t.id}`).hidden = state.tab !== t.id;
  if (state.tab === 'home') {
    $('fixture-note').textContent = FIXTURE_NOTE;
    renderSuggestions($('sugg'), state.suggestions, { catalog: state.catalog, me: me.name, onApprove: (id) => act('/api/suggestions/approve', { id }) });
  } else if (state.tab === 'party') {
    $('people').replaceChildren(...roster(view).map((m) => h('li', {},
      avatarNode({ avatar: m.avatar || '' }, 'sm'),
      h('span', { class: 'who', text: m.name + (m.me ? ' (you)' : '') }),
      h('span', { class: 'tags' }, m.host ? h('span', { class: 'avrana-tag', text: 'Host' }) : null))));
  } else if (state.tab === 'library') {
    const people = view.members.length;
    const named = new Set(state.suggestions.map((s) => s.game));
    $('library').replaceChildren(...state.catalog.map((g) => h('li', {},
      h('span', {}, h('strong', { text: g.name }), ' ', h('span', { class: 'text-muted', text: seatsPhrase(g, people) })),
      h('button', { type: 'button', class: 'btn btn-outline btn-sm', disabled: named.has(g.id), 'data-key': `suggest-${g.id}`,
        text: named.has(g.id) ? 'Suggested' : 'Suggest', onclick: () => act('/api/suggestions/nominate', { game: g.id }) }))));
  } else {
    $('me').replaceChildren(avatarNode({ avatar: me.avatar }, 'lg'), h('strong', { text: me.name }));
    $('me-role').textContent = whereLine(view, state.catalog);
  }
}

// ---- start ---------------------------------------------------------------------------------------------
async function start() {
  if (inLayer) { document.documentElement.classList.add('avrana-layer-doc'); document.body.classList.add('avrana-layer'); }
  else { document.body.classList.add('cp-page'); $('close').hidden = true; $('backdrop').hidden = true; $('sheet').removeAttribute('aria-modal'); $('sheet').setAttribute('role', 'region'); }
  $('tabs').replaceChildren(...TABS.map((t) => h('button', { type: 'button', id: `tab-${t.id}`, 'data-tab': t.id, 'aria-pressed': String(state.tab === t.id), text: t.label })));
  hydrateIcons();
  const [cat] = await Promise.all([api('/api/catalog'), refresh()]);
  state.catalog = cat ? cat.games : [];
  render();
  if (inLayer) post({ type: 'ready' });
  if (!inLayer) { $('back-to-game').focus({ preventScroll: true }); performance.mark('console-ready'); document.body.dataset.ready = '1'; }
  setInterval(() => { if (document.visibilityState === 'visible') (state.open ? refresh() : api('/api/view').then((v) => { if (v) { state.view = v; render(); } })); }, 2000);
  setInterval(() => { if (state.open && state.view && state.view.attention.some((a) => a.deadline)) render(); }, 1000);
}
start();
