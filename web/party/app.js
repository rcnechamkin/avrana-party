// Avrana Party page (Full Mode shell at https://party.avrana.net/party/).
//
// What it does, in order: check that the Pi answers, load the game catalog, observe this phone's
// capabilities, and show each installed game with what it will be like on *this* phone. Profiles
// and chat share donor adapters. Guest copy only.
//
// Party mode (AVR-20, AVR-127) is progressive enhancement: only when Party Core answers
// /party/api/state does the page offer Join, show who is here and who hosts, let the host start a
// party game for everyone, and take every member into it when that start is committed. Without
// Party Core (production before AVR-51) the page is the catalog it always was.

import { probeCapabilities, statuses } from './lib/capabilities.js';
import { evaluateSeat, explain } from './lib/evaluate.js';
import { registerShell } from './lib/shell.js';
import { capitalize, h, howText, kindIcon, playersText, screenText } from './lib/ui.js';
import { hydrateIcons, icon } from './lib/icons.js';

import { createProfile } from './lib/profile.js';
import { avatarNode, wireProfile } from './lib/profile-ui.js';
import { createPartyChat } from './lib/party-chat.js';
import { donorAvailability, visibleGames, filterGames, launchTarget } from './lib/catalog-view.js';
import { arrival, liveSession, partyGame, tileMode } from './lib/party-mode.js';
import { createPartyClient } from './lib/party-client.js';

const $ = (id) => document.getElementById(id);
// "This phone" list, most useful first. Labels come from the catalog (contracts/capabilities.v0.json).
const PHONE_CHECKS = ['secure_context', 'webrtc', 'video.h264', 'wake_lock', 'web_audio', 'gamepad', 'vibration'];
const ESSENTIAL = ['secure_context', 'webrtc', 'video.h264'];
const HEALTH_EVERY_MS = 15000;
// Party mode: the session this tab last went into (a session id, not a secret), and how long the
// "joining" announcement shows before the page moves (long enough for a screen reader to start).
const ENTERED_KEY = 'avrana-party-entered';
const ENTER_DELAY_MS = 900;
const PRESENCE_WORDS = { here: 'here', away: 'away', playing: 'playing' };

const state = { catalog: null, report: null, shell: null, reachable: null, healthTimer: null, donor: null, healths: new Map(), view: 'all',
  partyMode: false, partyBusy: false, entering: null };

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

const ARTWORK = /^art\/(lan|kenney)-[A-Za-z0-9_]+\.svg$/;

// Artwork, most specific first: the title's own art (or, for a few games, a curated Kenney
// icon), else a generic kind icon. Decorative: the title sits right beside it.
function cover(game) {
  const art = ARTWORK.test(game.artwork || '') ? game.artwork : null;
  const el = h('div', { class: 'avrana-game-cover' + (art ? ' has-art' : ''), 'aria-hidden': 'true' },
    art ? h('img', { src: art, alt: '', width: 72, height: 72, loading: 'lazy', decoding: 'async' })
      : icon(kindIcon(game)));
  // The catalog's own colour for the game; CSSOM, so the CSP's style-src still holds.
  if (ACCENT.test(game.accent || '')) el.style.setProperty('--game-accent', game.accent);
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
  const mode = state.partyMode ? tileMode(game, party.view(), state.catalog) : null;
  const action = mode ? partyAction(game, mode)
    : running && fits
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
  const live = mode ? (mode.kind === 'switch' ? `Ends ${mode.name} first, then everyone moves here`
    : 'Everyone plays together: the host starts it')
    : installed && hp?.integration === false ? 'Games update needed before opening here' : installed ? liveText(hp) : 'Experimental · Not installed on this Party box';
  const screen = screenText(game);
  const how = howText(game);
  return h('li', { class: 'avrana-game-card', 'data-id': game.id, 'data-outcome': installed ? result.outcome : 'unavailable',
    'data-party': mode ? mode.kind : null },
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

// ---- Party mode -------------------------------------------------------------------------------

function enteredSession() {
  try { return window.sessionStorage.getItem(ENTERED_KEY); } catch { return undefined; }
}
function markEntered(sid, game) {
  try { window.sessionStorage.setItem(ENTERED_KEY, sid); } catch { /* then a reopened page only offers */ }
  try { profile.remember(game); } catch { /* the recent list is a nicety */ }
}

/** A party game's tile action. The host's start is the only way a party game begins. */
function partyAction(game, mode) {
  if (mode.kind === 'join') {
    return h('button', { type: 'button', class: 'btn btn-outline', text: 'Join the party to play',
      onclick: () => $('party-name').focus() });
  }
  if (mode.kind === 'start') {
    return h('button', { type: 'button', class: 'btn btn-primary', disabled: state.partyBusy,
      onclick: () => hostStart(game, mode.game) }, icon('play'), 'Start for everyone');
  }
  if (mode.kind === 'switch') {
    return h('button', { type: 'button', class: 'btn btn-primary', disabled: state.partyBusy,
      'aria-label': `Switch everyone from ${mode.name} to ${game.name}`,
      onclick: () => hostStart(game, mode.game, true) }, icon('play'), 'Switch everyone to this');
  }
  if (mode.kind === 'rejoin') {
    return h('a', { class: 'btn btn-primary', href: mode.href, onclick: () => markEntered(mode.session, game) },
      icon('play'), 'Rejoin');
  }
  const text = mode.kind === 'wait' ? 'The host starts it' : mode.kind === 'starting' ? 'Starting…'
    : 'Party is playing ' + mode.name;
  return h('button', { type: 'button', class: 'btn', disabled: true, text });
}

async function hostStart(game, id, switching = false) {
  if (state.partyBusy) return;
  state.partyBusy = true;
  $('party-note').textContent = '';
  renderGames(false);
  const res = await (switching ? party.switchTo(id) : party.launch(id));
  state.partyBusy = false;
  if (!res.ok) $('party-note').textContent = res.message || `${game.name} didn’t start. Please try again.`;
  renderGames(false);
}

function renderParty(view, previous) {
  const me = view.me;
  $('party').hidden = false;
  $('party-join').hidden = Boolean(me);
  $('party-in').hidden = !me;
  if (!me && !$('party-name').value) $('party-name').value = profile.snapshot().name.slice(0, 16);
  const count = view.members.length;
  $('party-count').textContent = count === 1 ? '1 person' : `${count} people`;
  const host = view.members.find((m) => m.host);
  $('party-host').textContent = me && me.host ? 'You’re the host: start a party game below and everyone joins in.'
    : host ? `${host.name} is the host and starts the party games.` : 'Nobody is hosting right now.';
  $('party-members').replaceChildren(...view.members.map((m) => h('li', {
    class: 'inline-flex min-h-11 items-center gap-1.5 rounded-field bg-base-300 px-3 text-[0.9375rem]', 'data-presence': m.presence },
  h('strong', { class: 'font-semibold', text: m.name + (me && m.id === me.id ? ' (you)' : '') }),
  m.host ? h('span', { class: 'text-secondary', text: 'host' }) : null,
  h('span', { class: 'text-muted', text: PRESENCE_WORDS[m.presence] }))));

  const s = liveSession(view);
  const game = s ? partyGame(state.catalog, s.game) : null;
  const name = game ? game.name : s ? s.game : '';
  $('party-now').hidden = !s;
  $('party-rejoin').hidden = !(s && view.state === 'active' && me && game);
  $('party-end').hidden = !(s && view.state === 'active' && me && me.host);
  if (s) {
    const next = view.switching_to ? partyGame(state.catalog, view.switching_to) : null;
    $('party-now-text').textContent = view.state === 'launching' ? `Starting ${name}…`
      : view.switching_to ? `Switching from ${name} to ${next ? next.name : view.switching_to}…`
      : view.state === 'ending' ? `Ending ${name}…`
        : me ? `Your party is playing ${name}.` : `The party is playing ${name}. Join to play along.`;
    if (game) {
      $('party-rejoin').href = launchTarget(game);
      $('party-rejoin').onclick = () => markEntered(s.id, game);
      $('party-rejoin-text').textContent = `Rejoin ${name}`;
    }
  }
  // Announcements (a live region), only for changes this page watched happen.
  if (previous && previous.party === view.party) {
    const was = liveSession(previous);
    if (me && me.host && previous.me && !previous.me.host) $('party-live').textContent = 'You’re the host now.';
    else if (was && !s) {
      const old = partyGame(state.catalog, was.game);
      $('party-live').textContent = `${old ? old.name : was.game} is over.`;
    }
  }
  const failed = !s && view.session && view.session.outcome === 'launch_failed' && me && me.host;
  const known = previous && previous.session && previous.session.id === (view.session && view.session.id)
    && previous.session.outcome === 'launch_failed';
  if (failed && !known) {
    const g = partyGame(state.catalog, view.session.game);
    const why = view.session.detail;
    $('party-note').textContent = why ? `${g ? g.name : view.session.game} didn’t start. ${why}`
      : `${g ? g.name : view.session.game} didn’t start.`;
  }
}

/** Take this member into the party's game: announce it, remember it for this tab, then go. */
function enterGame(view, previous) {
  const s = view.session;
  const game = partyGame(state.catalog, s.game);
  if (!game || state.entering === s.id) return;
  state.entering = s.id;
  const watched = previous && previous.party === view.party;
  $('party-live').textContent = watched
    ? `${view.me.host ? 'You started' : 'The host started'} ${game.name}. Joining…`
    : `Your party is playing ${game.name}. Joining…`;
  markEntered(s.id, game);
  setTimeout(() => {
    const now = party.view();
    if (state.partyMode && now && now.state === 'active' && now.session && now.session.id === s.id) {
      location.assign(launchTarget(game));
    } else {
      state.entering = null;
    }
  }, ENTER_DELAY_MS);
}

function onPartyView(view, previous) {
  if (!state.partyMode) return;
  renderParty(view, previous);
  renderGames(false);
  if (arrival(view, { previous, entered: enteredSession() }) === 'enter') enterGame(view, previous);
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
  party.stop();
  const [reachable, catalog, report, partyView] = await Promise.all([
    checkReach(), getJSON('catalog.json').catch(() => null), probeCapabilities(), party.probe(),
  ]);
  state.reachable = reachable;
  state.catalog = catalog;
  catalog.games.forEach((game) => profile.keyFor(game));
  state.report = report;
  $('away').hidden = reachable;
  $('chat').hidden = !reachable;
  syncChat();
  $('games-section').hidden = !reachable || !catalog;
  // Party mode only when the Pi answered, the catalog loaded and Party Core gave a real view.
  state.partyMode = Boolean(reachable && catalog && partyView);
  document.documentElement.dataset.party = state.partyMode ? 'on' : 'off';
  $('party').hidden = !state.partyMode;
  if (state.partyMode) party.start(partyView);
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
const party = createPartyClient({ onView: onPartyView });
$('party-join').onsubmit = async (event) => {
  event.preventDefault();
  $('party-note').textContent = '';
  const res = await party.join($('party-name').value);
  if (!res.ok) $('party-note').textContent = res.message || 'Couldn’t join. Please try again.';
};
$('party-leave').onclick = async () => {
  const res = await party.leave();
  $('party-note').textContent = res.ok ? '' : res.message || 'Please try again.';
  if (res.ok) $('party-live').textContent = 'You left the party.';
};
$('party-end').onclick = async () => {
  $('party-end').disabled = true;
  const res = await party.end();
  $('party-end').disabled = false;
  $('party-note').textContent = res.ok ? '' : res.message || 'Please try again.';
};
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
window.addEventListener('pagehide', () => { chat.close(); party.stop(); });

$('retry').addEventListener('click', () => { boot(); });
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return;
  if (state.partyMode) party.poke();          // a phone waking up asks Party Core at once
  (state.reachable === false ? boot() : refreshHealth());
});
window.addEventListener('pageshow', (event) => { if (event.persisted) boot(); else syncChat(); });
window.addEventListener('online', () => { if (state.reachable === false) boot(); });
state.healthTimer = setInterval(refreshHealth, HEALTH_EVERY_MS);
boot();
