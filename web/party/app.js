// Avrana Party page (Full Mode shell at https://party.avrana.net/party/).
//
// What it does, in order: check that the Pi answers, load the game catalog, observe this phone's
// capabilities, and show each installed game with what it will be like on *this* phone. Nothing
// here reserves a seat or runs a game; profiles/chat share donor adapters. Guest copy only.

import { probeCapabilities, statuses } from './lib/capabilities.js';
import { evaluateSeat, explain } from './lib/evaluate.js';
import { registerShell } from './lib/shell.js';
import { capitalize, h, howText, kindIcon, playersText, screenText } from './lib/ui.js';
import { hydrateIcons, icon } from './lib/icons.js';

import { createProfile } from './lib/profile.js';
import { avatarNode, wireProfile } from './lib/profile-ui.js';
import { createPartyChat } from './lib/party-chat.js';
import { donorAvailability, visibleGames, filterGames, launchTarget } from './lib/catalog-view.js';

const $ = (id) => document.getElementById(id);
// "This phone" list, most useful first. Labels come from the catalog (contracts/capabilities.v0.json).
const PHONE_CHECKS = ['secure_context', 'webrtc', 'video.h264', 'wake_lock', 'web_audio', 'gamepad', 'vibration'];
const ESSENTIAL = ['secure_context', 'webrtc', 'video.h264'];
const HEALTH_EVERY_MS = 15000;

const state = { catalog: null, report: null, shell: null, reachable: null, healthTimer: null, donor: null, healths: new Map(), view: 'all' };

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
    const res = await fetch(path, { cache: 'no-store', signal: AbortSignal.timeout(4000) });
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

const FIT = {
  ready: ['circle-check', 'Works on this phone'],
  limited: ['circle-alert', 'Works, with limits'],
  watch: ['eye', 'You can watch'],
  no: ['circle-slash', 'Not on this phone'],
};

function chipFor(result) {
  const fit = FIT[result.outcome] ? result.outcome : 'no';
  const [name, text] = FIT[fit];
  return h('span', { class: 'avrana-fit', 'data-fit': fit }, icon(name), text);
}

const ACCENT = /^#[0-9a-f]{6}$/i;

const ARTWORK = /^art\/[A-Za-z0-9_]+\.svg$/;

// Artwork, most specific first: the catalog's local artwork (Avrana-curated for now), else a
// generic kind icon. Decorative: the title sits right beside it.
function cover(game) {
  const art = ARTWORK.test(game.artwork || '') ? game.artwork : null;
  const el = h('div', { class: 'avrana-game-cover', 'aria-hidden': 'true' },
    art ? h('span', { class: 'avrana-game-art' }) : icon(kindIcon(game)));
  // The catalog's own colour and art for the game; CSSOM, so the CSP's style-src still holds.
  if (ACCENT.test(game.accent || '')) el.style.setProperty('--game-accent', game.accent);
  if (art) el.style.setProperty('--game-art', `url("${new URL(art, document.baseURI).href}")`);
  return el;
}

function emptyState(name, text) {
  return h('li', { class: 'avrana-empty xl:col-span-2' }, icon(name), h('p', { class: 'm-0', text }));
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
  const target = launchTarget(game);
  const installed = Boolean(game.installed && game.entry);
  const note = installed ? explain(result, state.catalog.labels || {}) : '';
  const running = installed && Boolean(target) && !(hp && !hp.running);
  const fits = result.outcome !== 'unavailable';
  const remember = (event) => {
    try {
      if (!profile.snapshot().name) {
        event.preventDefault(); $('profile').open = true; $('profile-name').focus();
        $('profile-note').textContent = 'Choose your Party name before opening a game.';
        return;
      }
      profile.ensureToken(); profile.remember(game); renderProfile();
    }
    catch (err) { event.preventDefault(); $('profile-note').textContent = err.message; }
  };
  const label = result.outcome === 'watch' ? 'Watch' : 'Play';
  const action = running && fits
    ? h('a', { class: 'btn btn-primary', href: target, onclick: remember }, icon(label === 'Watch' ? 'eye' : 'play'), label)
    : running
      ? h('a', { class: 'btn btn-outline', href: target, onclick: remember, text: 'Try anyway' })
      : h('button', { type: 'button', class: 'btn', disabled: true, text: installed ? 'Play' : 'Not installed' });
  const favorite = profile.isFavorite(game);
  const star = h('button', { type: 'button', class: 'btn btn-ghost btn-square -mr-1 -mt-1 ' + (favorite ? 'text-warning' : 'text-muted'),
    'aria-label': (favorite ? 'Remove ' : 'Add ') + game.name + (favorite ? ' from favorites' : ' to favorites'),
    'aria-pressed': favorite, onclick: () => {
      try { profile.toggleFavorite(game); renderProfile(); renderGames(false); }
      catch (err) { $('profile-note').textContent = err.message; }
    } }, icon('star', { cls: favorite ? 'fill-current' : '' }));
  const live = installed && hp?.integration === false ? 'Games update needed before opening here' : installed ? liveText(hp) : 'Experimental · Not installed on this Party box';
  const screen = screenText(game);
  const how = howText(game);
  return h('li', { class: 'avrana-game-card', 'data-id': game.id, 'data-outcome': installed ? result.outcome : 'unavailable' },
    cover(game),
    h('div', { class: 'min-w-0' }, h('h3', { class: 'avrana-game-title', text: game.name }),
      h('p', { class: 'avrana-game-facts m-0' },
        h('span', {}, icon('users'), playersText(game.players)),
        h('span', {}, icon(screen.icon), screen.text))),
    star,
    game.summary ? h('p', { class: 'summary wide m-0', text: game.summary }) : null,
    how ? h('p', { class: 'wide m-0 text-[0.9375rem] text-muted', text: capitalize(how) }) : null,
    game.hardwareValidationRequired ? h('p', { class: 'wide m-0 text-[0.9375rem] text-muted', text: 'Needs a device check before use.' }) : null,
    note ? h('p', { class: 'why wide m-0', text: note }) : null,
    h('div', { class: 'foot' },
      h('div', { class: 'grid gap-0.5' }, installed ? chipFor(result) : null,
        live ? h('span', { class: 'text-[0.9375rem] text-muted', text: live }) : null),
      action));
}

async function renderGames(refresh = true) {
  if (!state.catalog || state.reachable === false) return;
  if (refresh) {
    const installed = state.catalog.games.filter((g) => g.installed && g.health);
    const [donor, ...healths] = await Promise.all([
      getJSON('/api/games', { cache: 'no-store', signal: AbortSignal.timeout(4000) })
        .then(donorAvailability).catch(() => null),
      ...installed.map((g) => health(g.health)),
    ]);
    state.donor = donor;
    state.healths = new Map(installed.map((g, i) => [g.id, healths[i]]));
  }
  if (state.reachable === false) return;
  const caps = statuses(state.report);
  const games = filterGames(visibleGames(state.catalog), {
    query: $('game-search').value, players: Number($('game-players').value), view: state.view,
  }, profile);
  const items = games.map((g) => {
    const hp = g.legacySlug ? state.donor?.get(g.legacySlug) || { running: false }
      : state.healths?.get(g.id);
    return gameCard(g, evaluateSeat(g, caps, 'player'), hp);
  });
  $('game-count').textContent = games.length + (games.length === 1 ? ' game' : ' games');
  if (!items.length) items.push(state.view === 'favorites' ? emptyState('star', 'Tap a star to save a game here.')
    : state.view === 'recent' ? emptyState('history', 'Games you open will appear here.')
      : emptyState('search-x', 'No games match. Try another search or group size.'));
  const list = $('games'), old = [...list.children];
  if (old.length !== items.length || old.some((el, i) => el.dataset.id !== items[i].dataset.id)) {
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
    const mark = status === 'yes' ? 'check' : status === 'no' ? 'x' : 'circle-help';
    return h('li', { 'data-status': status, 'data-cap': name }, icon(mark), h('span', { text }));
  });
  if (state.shell && state.shell.state === 'registered') {
    items.splice(1, 0, h('li', { 'data-status': 'yes', 'data-cap': 'offline_copy' },
      icon('check'), h('span', { text: 'Party page saved on this phone' })));
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
  catalog.games.forEach((game) => profile.keyFor(game));
  state.report = report;
  $('away').hidden = reachable;
  $('chat').hidden = !reachable;
  syncChat();
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

hydrateIcons();

let storage;
try { storage = window.localStorage; } catch { /* compatibility model reports persistence failure */ }
const profile = createProfile(storage);
const chat = createPartyChat({
  identity: () => profile.identity(), origin: location.origin,
  onChange: (snapshot) => {
    const labels = { closed: 'Open to chat', connecting: 'Connecting…',
      unavailable: 'Chat is reconnecting…', profile_required: 'Save your profile to chat' };
    $('chat-status').textContent = snapshot.status === 'connected'
      ? snapshot.online + ' in chat' : labels[snapshot.status];
    $('chat-send').disabled = snapshot.status !== 'connected';
    const list = $('chat-messages');
    const atEnd = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
    list.replaceChildren(...snapshot.messages.map((m) =>
      h('li', { class: 'flex gap-3 border-b border-line py-2.5 last:border-b-0' }, avatarNode(m, 'sm'), h('div', { class: 'min-w-0' },
        h('strong', { class: 'text-[0.9375rem]', text: m.name }),
        h('p', { class: 'm-0 whitespace-pre-wrap', text: m.text }),
        m.photo ? h('p', { class: 'm-0 inline-flex items-center gap-1.5 text-[0.9375rem] text-muted' }, icon('image'), 'Photo shared') : null))));
    if (atEnd) list.scrollTop = list.scrollHeight;
  },
});
const renderProfile = wireProfile(profile, () => { renderGames(false); syncChat(true); });
function syncChat(reconnect = false) {
  if (state.reachable && $('chat').open && profile.snapshot().name) {
    const opened = chat.open();
    if (reconnect && !opened) chat.reconnect();
  } else {
    chat.close();
    if ($('chat').open && state.reachable && !profile.snapshot().name)
      $('chat-status').textContent = 'Choose your name above to chat';
  }
}
$('chat').addEventListener('toggle', () => syncChat());
$('chat-form').onsubmit = (event) => {
  event.preventDefault();
  if (chat.send($('chat-text').value)) {
    $('chat-text').value = ''; $('chat-feedback').textContent = '';
  } else $('chat-feedback').textContent = 'Chat is not connected yet. Please try again.';
};
$('game-search').oninput = () => renderGames(false);
$('game-players').onchange = () => renderGames(false);
$('game-views').onclick = (event) => {
  const button = event.target.closest('button[data-view]');
  if (!button) return;
  state.view = button.dataset.view;
  for (const item of $('game-views').querySelectorAll('button'))
    item.setAttribute('aria-pressed', String(item === button));
  renderGames(false);
};
window.addEventListener('pagehide', () => chat.close());

$('retry').addEventListener('click', () => { boot(); });
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') (state.reachable === false ? boot() : refreshHealth());
});
window.addEventListener('pageshow', (event) => { if (event.persisted) boot(); else syncChat(); });
window.addEventListener('online', () => { if (state.reachable === false) boot(); });
state.healthTimer = setInterval(refreshHealth, HEALTH_EVERY_MS);
boot();
