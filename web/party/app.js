// Avrana Party page (Full Mode shell at https://party.avrana.net/party/).
//
// What it does, in order: check that the Pi answers, load the game catalog, observe this phone's
// capabilities, and show each installed game with what it will be like on *this* phone. Nothing
// here joins a party or plays a game; the games keep their own pages. Guest copy only.

import { probeCapabilities, statuses } from './lib/capabilities.js';
import { evaluateSeat, explain } from './lib/evaluate.js';
import { registerShell } from './lib/shell.js';
import { capitalize, h, howText, kindIcon, playersText } from './lib/ui.js';

const $ = (id) => document.getElementById(id);
// "This phone" list, most useful first. Labels come from the catalog (contracts/capabilities.v0.json).
const PHONE_CHECKS = ['secure_context', 'webrtc', 'video.h264', 'wake_lock', 'web_audio', 'gamepad', 'vibration'];
const ESSENTIAL = ['secure_context', 'webrtc', 'video.h264'];
const HEALTH_EVERY_MS = 15000;

const state = { catalog: null, report: null, shell: null, reachable: null, healthTimer: null };

async function getJSON(url, init) {
  const res = await fetch(url, init);
  if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status });
  return res.json();
}

/** Does the Pi answer? api/origin.json comes from nginx on the Party box and is never answered
 * from the offline copy; anything else answering (another network's portal) does not count. */
async function checkReach() {
  try {
    const origin = await getJSON('api/origin.json', { cache: 'no-store' });
    return Boolean(origin && origin.schema === 'avrana.origin/v0');
  } catch {
    return false;
  }
}

async function health(path) {
  if (!path) return null;
  try {
    const res = await fetch(path, { cache: 'no-store' });
    if (!res.ok) return { running: false };
    let body = null;
    try { body = await res.json(); } catch { /* health without details */ }
    const count = (v) => (Number.isInteger(v) ? v : null);
    const running = !(body && (body.error || body.emulator_running === false));
    return { running, players: count(body && body.players), max: count(body && body.max_players) };
  } catch {
    return { running: false };
  }
}

function setStatus(kind, text) {
  const status = $('status');
  status.dataset.state = kind;
  $('status-text').textContent = text;
  $('secure').hidden = !(kind === 'ok' && window.isSecureContext);
}

function chipFor(result) {
  switch (result.outcome) {
    case 'ready': return h('span', { class: 'chip ok', text: 'Works on this phone' });
    case 'limited': return h('span', { class: 'chip limited', text: 'Works, with limits' });
    case 'watch': return h('span', { class: 'chip watch', text: 'You can watch' });
    default: return h('span', { class: 'chip no', text: 'Not on this phone' });
  }
}

function liveText(hp) {
  if (!hp) return null;
  if (!hp.running) return 'Not running right now';
  if (hp.players !== null && hp.max !== null) {
    return hp.players >= hp.max ? 'Full right now' : `${hp.players} of ${hp.max} playing`;
  }
  return 'Running';
}

function gameCard(game, result, hp) {
  const labels = state.catalog.labels || {};
  const note = explain(result, labels);
  const running = !(hp && !hp.running);
  const fits = result.outcome !== 'unavailable';
  // The engine advises; it never locks anyone out on a probe alone. A phone that looks unable
  // still gets a quiet way in, because a real attempt is the final test.
  const action = running && fits
    ? h('a', { class: 'button', href: game.entry, text: result.outcome === 'watch' ? 'Watch' : 'Play' })
    : running
      ? h('a', { class: 'button quiet', href: game.entry, text: 'Try anyway' })
      : h('button', { type: 'button', class: 'button', disabled: true, text: 'Play' });
  const live = liveText(hp);
  return h('li', { class: 'game', 'data-id': game.id, 'data-outcome': result.outcome },
    h('div', { class: 'gicon', 'aria-hidden': 'true', text: kindIcon(game) }),
    h('div', {},
      h('h3', { text: game.name }),
      h('p', { class: 'gmeta', text: `${playersText(game.players)} · ${howText(game)}` })),
    game.summary ? h('p', { class: 'gsummary note', text: game.summary }) : null,
    note ? h('p', { class: 'note why', text: note }) : null,
    h('div', { class: 'gfoot' }, chipFor(result), live ? h('span', { class: 'live', text: live }) : null, action));
}

function collectionCard(col) {
  return h('li', { class: 'game', 'data-id': col.id, 'data-outcome': col.available ? 'ready' : 'unavailable' },
    h('div', { class: 'gicon', 'aria-hidden': 'true', text: '🎉' }),
    h('div', {}, h('h3', { text: col.name }), h('p', { class: 'gmeta', text: 'play on your phone' })),
    col.summary ? h('p', { class: 'gsummary note', text: col.summary }) : null,
    h('div', { class: 'gfoot' },
      col.available ? h('a', { class: 'button', href: col.entry, text: 'Open' })
        : h('button', { type: 'button', class: 'button', disabled: true, text: 'Open' })));
}

async function renderGames() {
  const list = $('games');
  const caps = statuses(state.report);
  const installed = state.catalog.games.filter((g) => g.installed && g.entry);
  const healths = await Promise.all(installed.map((g) => health(g.health)));
  const items = installed.map((g, i) => gameCard(g, evaluateSeat(g, caps, 'player'), healths[i]));
  for (const col of state.catalog.collections || []) items.push(collectionCard(col));
  if (!items.length) items.push(h('li', { class: 'card', text: 'No games are set up on this Party box yet.' }));
  // Replace only the cards that changed, so a periodic refresh never steals keyboard or
  // screen-reader focus from a card that stayed the same.
  const old = [...list.children];
  if (old.length !== items.length || old.some((el) => !el.dataset.id)) {
    list.replaceChildren(...items);
  } else {
    items.forEach((item, i) => { if (!old[i].isEqualNode(item)) old[i].replaceWith(item); });
  }
  list.setAttribute('aria-busy', 'false');
}

function renderPhone() {
  const labels = state.catalog ? state.catalog.labels || {} : {};
  const caps = state.report.caps;
  const items = PHONE_CHECKS.map((name) => {
    const status = (caps[name] && caps[name].status) || 'unknown';
    const label = labels[name] || { label: name, missing: `${name} isn’t available.` };
    const text = status === 'yes' ? capitalize(label.label)
      : status === 'no' ? label.missing : `${capitalize(label.label)}: not sure yet`;
    const mark = status === 'yes' ? '✓' : status === 'no' ? '✕' : '?';
    return h('li', { 'data-status': status, 'data-mark': mark, 'data-cap': name, text });
  });
  if (state.shell && state.shell.state === 'registered') {
    items.splice(1, 0, h('li', { 'data-status': 'yes', 'data-mark': '✓', 'data-cap': 'offline_copy',
      text: 'Party page saved on this phone' }));
  }
  $('phone-list').replaceChildren(...items);
  const allSet = ESSENTIAL.every((name) => caps[name] && caps[name].status === 'yes');
  $('phone-summary').textContent = allSet ? 'All set' : 'Some things are limited';
}

async function refreshHealth() {
  if (document.visibilityState !== 'visible' || !state.catalog || state.reachable === false) return;
  await renderGames();
}

async function boot() {
  if (location.hash === '#diag') {
    location.replace('diag/');
    return;
  }
  setStatus('checking', 'Checking the connection…');
  const [reachable, catalog, report] = await Promise.all([
    checkReach(), getJSON('catalog.json').catch(() => null), probeCapabilities(),
  ]);
  state.reachable = reachable;
  state.catalog = catalog;
  state.report = report;
  $('away').hidden = reachable;
  $('games-section').hidden = !reachable || !catalog;
  if (!reachable) {
    setStatus('away', 'Not connected to the party');
  } else {
    setStatus('ok', window.isSecureContext ? 'Connected to the party'
      : 'Connected. Open party.avrana.net for the full experience');
  }
  if (catalog) renderPhone();
  if (reachable && catalog) await renderGames();
  document.documentElement.dataset.ready = 'true';
  // The offline copy is never on the critical path.
  const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 500));
  idle(async () => {
    state.shell = await registerShell();
    if (state.catalog) renderPhone();
  });
}

$('retry').addEventListener('click', () => { boot(); });
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') (state.reachable === false ? boot() : refreshHealth());
});
window.addEventListener('pageshow', (event) => { if (event.persisted) boot(); });
window.addEventListener('online', () => { if (state.reachable === false) boot(); });
state.healthTimer = setInterval(refreshHealth, HEALTH_EVERY_MS);
boot();
