// Avrana Party page (Full Mode shell at https://party.avrana.net/party/).
//
// What it does, in order: check that the Pi answers, load the game catalog, observe this phone's
// capabilities, and show each installed game with what it will be like on *this* phone. Profiles
// and chat share donor adapters. Guest copy only.
//
// The page is a frame with four places (Home, Party, Library, System: lib/frame.js) that are views
// of this one document, and two things that open over whichever is on screen: the Party drawer
// (people, and today's chat while the old chat still answers) and the Limited Mode sheet.
//
// Party mode (ADR 0011, the console model) is progressive enhancement: only when Party Core answers
// /party/api/state is this page the party's home screen. A phone with a profile is in the party on
// its own (no Join). The party is in one place and only its host moves it: home (this catalog), a
// round's setup (this page's full-screen setup scene) or a round and its results (the game's page,
// where every member's phone goes at once). Without Party Core the page is the catalog it always was.

import { probeCapabilities, statuses } from './lib/capabilities.js';
import { evaluateSeat, explain } from './lib/evaluate.js';
import { registerShell } from './lib/shell.js';
import { capitalize, h, howText, kindIcon, playersText, screenText } from './lib/ui.js';
import { hydrateIcons, icon } from './lib/icons.js';

import { createProfile } from './lib/profile.js';
import { avatarNode, wireProfile } from './lib/profile-ui.js';
import { createPartyChat } from './lib/party-chat.js';
import { loadCatalog } from './lib/catalog-load.js';
import { donorAvailability, visibleGames, filterGames, launchTarget } from './lib/catalog-view.js';
import { HOME, destination, locationOf, partyGame, roster, setupPanel, tileMode } from './lib/party-mode.js';
import { createPartyClient } from './lib/party-client.js';
import { LIMITED, blockedGames, limitedNotice, modeOf, seatChoice } from './lib/limited.js';
import { chatGivesUp, chatOffered, hereLine, hostLine, hudLabel, namesLine, pageOf, pageTitle, startTab } from './lib/frame.js';

const $ = (id) => document.getElementById(id);
// "This phone" list, most useful first. Labels come from the catalog (contracts/capabilities.v0.json).
const PHONE_CHECKS = ['secure_context', 'webrtc', 'video.h264', 'wake_lock', 'web_audio', 'gamepad', 'vibration'];
const ESSENTIAL = ['secure_context', 'webrtc', 'video.h264'];
const HEALTH_EVERY_MS = 15000;

const state = { catalog: null, report: null, shell: null, reachable: null, healthTimer: null, donor: null, healths: new Map(), view: 'all',
  partyMode: false, partyBusy: false, joining: false, failShown: null, acked: false, rulesThen: null,
  mode: 'full', page: 'home', tab: 'people', chatStatus: 'closed', chatFails: 0 };

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
        event.preventDefault(); openProfile();
        $('profile-note').textContent = 'Choose your Party name before opening a game.';
        return;
      }
      profile.ensureToken(); profile.remember(game); renderProfile();
    }
    catch (err) { event.preventDefault(); $('profile-note').textContent = err.message; }
  };
  const label = result.outcome === 'watch' ? 'Watch' : 'Play';
  const mode = state.partyMode ? tileMode(game, party.view()) : null;
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
  const live = mode ? 'Everyone plays together: the host starts it'
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

// ---- Party mode (ADR 0011: one party, one place, the host moves it) ---------------------------

/** A party game's tile, while the party is home. The host's start is the only way it begins. */
function partyAction(game, mode) {
  if (mode.kind === 'profile') {
    return h('button', { type: 'button', class: 'btn btn-outline', text: 'Choose your name to play',
      onclick: () => openProfile() });
  }
  if (mode.kind === 'start') {
    return h('button', { type: 'button', class: 'btn btn-primary', disabled: state.partyBusy,
      onclick: () => hostStart(game, mode.game) }, icon('play'), 'Start for everyone');
  }
  const text = mode.kind === 'wait' ? 'The host starts it' : 'Starting…';
  return h('button', { type: 'button', class: 'btn', disabled: true, text });
}

async function hostStart(game, id) {
  if (state.partyBusy) return;
  state.partyBusy = true;
  $('party-note').textContent = '';
  renderGames(false);
  const res = await party.launch(id);
  state.partyBusy = false;
  if (!res.ok) $('party-note').textContent = res.message || `${game.name} didn’t start. Please try again.`;
  renderGames(false);
}

/** This phone's profile, as Party Core takes it (16 characters, a bundled avatar). */
function partyIdentity() {
  const me = profile.snapshot();
  const name = (me.name || '').trim().slice(0, 16).trim();
  return name ? { name, avatar: me.avatar } : null;
}

/** Presence is automatic (ADR 0011): once this phone has a profile it is in the party. Called on
 * every view, so a reopened page, a new party after a restart or a fresh profile all just join. */
async function ensurePresent(view) {
  if (view.me || state.joining) return;
  const who = partyIdentity();
  if (!who) return;
  state.joining = true;
  const res = await party.join(who.name, who.avatar);
  state.joining = false;
  if (!res.ok) $('party-note').textContent = res.message ? `${res.message} Change it in your profile.` : '';
}

/** A person at the party: face, name, and what is true of them in words (never colour or an
 * icon alone). The same item serves the Party page (large faces) and the drawer (rows). */
function personItem(m, size = '') {
  return h('li', { 'data-choice': m.choice || null, 'data-away': m.away ? '' : null,
    'data-mode': m.limited ? LIMITED : null },
    avatarNode({ avatar: m.avatar || '' }, size),
    h('span', { class: 'who', text: m.name + (m.me ? ' (you)' : '') }),
    h('span', { class: 'tags' },
      m.host ? h('span', { class: 'avrana-tag', text: 'Host' }) : null,
      // ADR 0012 D4: how each member reaches the party is visible to everyone
      m.limited ? h('span', { class: 'avrana-tag mode', text: 'Limited' }) : null,
      m.away ? h('span', { class: 'avrana-tag quiet', text: 'Away' }) : null));
}

/** The Limited Mode banner (ADR 0012): shown only when Party Core says this phone reached it
 * over the plain-HTTP fallback. Plain words, what is missing on this phone, how it is restored. */
function renderLimited() {
  const on = state.mode === LIMITED && Boolean(state.report);
  $('limited').hidden = !on;
  // The mode is always marked on the phone it applies to: in full on Home, and by the mark in the
  // top bar on every other page, which opens the same words over that page.
  $('limited-mark').hidden = !on || state.page === 'home';
  if (!on) { if ($('about-limited').open) $('about-limited').close(); return; }
  const caps = statuses(state.report);
  const notice = limitedNotice({ caps, blocked: state.catalog ? blockedGames(visibleGames(state.catalog), caps) : [] });
  for (const where of ['limited', 'about']) {
    $(`${where}-intro`).textContent = notice.intro;
    $(`${where}-list`).replaceChildren(...notice.missing.map((text) => h('li', { text })));
    $(`${where}-restore`).textContent = notice.restore;
  }
}

// ---- the frame: four places, the Party control, the drawer ---------------------------------------

/** Show one of the shell's places. The party's own location is not this function's business:
 * show() hides the whole frame while the party is anywhere but home. */
function showPage(page, focus = false) {
  state.page = page;
  for (const el of $('content').querySelectorAll('[data-page]')) el.hidden = el.dataset.page !== page;
  for (const link of $('nav').querySelectorAll('a')) {
    if (link.dataset.go === page) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
  }
  const title = pageTitle(page);
  $('top-title').textContent = title;
  $('top-title').classList.toggle('brand', page === 'home');
  document.title = page === 'home' ? title : `${title} · Avrana Party`;
  document.documentElement.dataset.place = page;
  renderLimited();
  if (focus) { $('content').scrollTop = 0; $('top-title').focus({ preventScroll: true }); }
}

/** Your name and avatar live on the Party page. */
function openProfile() {
  if (state.page !== 'party') { history.replaceState(null, '', '#party'); showPage('party'); }
  $('profile').open = true;
  $('profile-name').focus();
}

const chatOn = () => chatOffered({ reachable: state.reachable, hub: state.donor !== null && state.donor !== undefined, status: state.chatStatus });

/** Home's own words: who you are here, and the way to the games. */
function renderHome() {
  const view = state.partyMode ? party.view() : null;
  $('home-name').hidden = Boolean(profile.snapshot().name);
  $('home-library').hidden = state.reachable === false;      // nothing to browse while the Pi is out of reach
  $('home-library-text').textContent = view && view.me && view.me.host ? 'Pick a game' : 'Open the Library';
  $('home-library').classList.toggle('btn-primary', Boolean(view && view.me && view.me.host));
}

/** The Party control: faces and a count while there is a party; a chat mark when there is only
 * the chat; nothing when there is neither. */
function renderHud() {
  const view = state.partyMode ? party.view() : null;
  const people = view ? roster(view) : [];
  const chatting = chatOn();
  $('hud').hidden = !(people.length || chatting);
  $('party-chat-row').hidden = !chatting;
  $('hud').setAttribute('aria-label', hudLabel({ party: people.length > 0, count: people.length, chat: chatting }));
  $('hud-faces').replaceChildren(...(people.length
    ? people.slice(0, 3).map((m) => avatarNode({ avatar: m.avatar || '' }, 'xs'))
    : [icon('message-circle')]));
  $('hud-count').textContent = people.length > 3 ? `+${people.length - 3}` : '';
  if ($('social').open) renderSocial();
}

function renderSocial() {
  const view = state.partyMode ? party.view() : null;
  const tab = startTab({ party: Boolean(view), chat: chatOn(), want: state.tab });
  if (!tab) { $('social').close(); return; }
  state.tab = tab;
  $('social-tabs').hidden = !(view && chatOn());
  for (const button of $('social-tabs').querySelectorAll('button'))
    button.setAttribute('aria-pressed', String(button.dataset.tab === tab));
  $('pane-people').hidden = tab !== 'people';
  $('chat').hidden = tab !== 'chat';
  $('chat-form').hidden = tab !== 'chat';
  $('social-h').textContent = view ? 'Your Party' : 'Party chat';
  if (view) {
    const limited = new Set(view.members.filter((m) => m.mode === LIMITED).map((m) => m.id));
    $('social-people').replaceChildren(...roster(view).map((m) => personItem({ ...m, limited: limited.has(m.id) }, 'sm')));
  }
  syncChat();           // the side on screen may have changed by itself (chat's runtime went away)
}

function openSocial(want) {
  state.tab = want;
  state.chatFails = 0;
  if (startTab({ party: state.partyMode && Boolean(party.view()), chat: chatOn(), want }) && !$('social').open) $('social').showModal();
  renderSocial();
}

function renderParty(view) {
  const me = view.me;
  $('party').hidden = false;
  $('party-people').hidden = false;
  const count = view.members.length;
  $('party-count').textContent = count === 1 ? '1 person' : `${count} people`;
  const host = view.members.find((m) => m.host);
  const people = roster(view);
  $('party-lede').textContent = me ? hereLine(count)
    : partyIdentity() ? 'Joining the party…' : 'Choose your name to join the party.';
  $('party-names').textContent = me ? namesLine(people) : '';
  $('party-host').textContent = hostLine(me, host);
  const limited = new Set(view.members.filter((m) => m.mode === LIMITED).map((m) => m.id));
  $('party-members').replaceChildren(...people.map((m) => personItem({ ...m, limited: limited.has(m.id) }, 'xl')));
  renderHome();
  renderHud();
  const s = view.session;
  const failed = s && s.outcome === 'launch_failed' && me && me.host && s.id !== state.failShown;
  if (failed) {
    state.failShown = s.id;
    const g = partyGame(state.catalog, s.game);
    $('party-note').textContent = `${g ? g.name : s.game} didn’t start.` + (s.detail ? ` ${s.detail}` : '');
  }
}

// ---- the setup scene ----------------------------------------------------------------------------
const ONBOARDING = new Map();       // game id -> onboarding.json (or null), fetched once

/** The game's onboarding (avrana.onboarding/v0), served beside its entry: /games/<slug>/. */
async function onboardingFor(game) {
  if (ONBOARDING.has(game.id)) return ONBOARDING.get(game.id);
  ONBOARDING.set(game.id, null);
  try {
    const url = new URL('onboarding.json', new URL(launchTarget(game), location.href)).pathname;
    const data = await getJSON(url, { cache: 'no-store' });
    if (data && data.schema === 'avrana.onboarding/v0' && Array.isArray(data.rules)) ONBOARDING.set(game.id, data);
  } catch { /* the catalog's summary is enough to choose */ }
  return ONBOARDING.get(game.id);
}

function acknowledged(ob) {
  if (!ob || !ob.ack) return true;
  try { return window.localStorage.getItem(ob.ack.key) === ob.ack.version; } catch { return state.acked; }
}
function acknowledge(ob) {
  state.acked = true;
  if (!ob || !ob.ack) return;
  try { window.localStorage.setItem(ob.ack.key, ob.ack.version); } catch { /* memory only */ }
}

/** Open How to play. `then`: an action to run on "Got it" (a first-timer's Play). */
function openRules(game, ob, then = null) {
  const facts = (ob && ob.facts) || {};
  const fill = (text) => String(text).replace(/\{(\w+)\}/g, (m, k) => (k in facts ? facts[k] : m));
  $('rules-title').textContent = `How to play ${game.name}`;
  $('rules-body').replaceChildren(...(ob ? ob.rules : [{ title: game.name, points: [game.summary || ''] }])
    .map((sec) => h('section', { class: 'avrana-rules' }, h('h3', { text: fill(sec.title) }),
      h('ul', {}, ...sec.points.map((p) => h('li', { text: fill(p) }))))));
  $('rules-ok').textContent = then ? 'Got it, I’ll play' : 'Got it';
  state.rulesThen = then;
  $('rules').showModal();
}

async function choose(choice) {
  const view = party.view();
  const game = view && partyGame(state.catalog, view.session && view.session.game);
  const ob = game ? await onboardingFor(game) : null;
  if (choice === 'player' && game && !seatChoice(state.mode, game, statuses(state.report)).play) return;
  if (choice === 'player' && game && !acknowledged(ob)) return openRules(game, ob, () => choose('player'));
  const res = await party.choose(choice);
  if (!res.ok) $('scene-status').textContent = res.message || 'Please try again.';
}

async function renderScene(view) {
  const panel = setupPanel(view);
  const game = partyGame(state.catalog, panel ? panel.game : null);
  if (!panel || !game) return;
  $('scene').dataset.game = game.id;
  $('scene-title').textContent = game.name;
  const art = ARTWORK.test(game.artwork || '') ? game.artwork : 'icon.svg';
  if ($('scene-art').getAttribute('src') !== art) $('scene-art').src = art;
  if (ACCENT.test(game.accent || '')) $('scene-cover').style.setProperty('--game-accent', game.accent);
  $('scene-host-name').textContent = panel.host ? 'You’re the host' : panel.hostName ? `Hosted by ${panel.hostName}` : 'Nobody is hosting';
  const ob = await onboardingFor(game);
  $('scene-premise').textContent = (ob && ob.premise) || game.summary || '';
  const words = { player: ['play', 'Playing'], spectator: ['eye', 'Watching'] };
  const people = roster(view);
  $('scene-count').textContent = `${panel.players} playing · ${panel.spectators} watching`;
  $('scene-roster').replaceChildren(...people.map((m) => {
    const [ic, text] = words[m.choice] || ['hourglass', 'Choosing'];
    return h('li', { 'data-choice': m.choice || null, 'data-away': m.away ? '' : null },
      h('span', { class: 'face' }, avatarNode({ avatar: m.avatar || '' }),
        m.host ? h('span', { class: 'crown' }, icon('crown', { label: 'host' })) : null,
        h('span', { class: 'badge' }, icon(ic, { label: text }))),
      h('span', { class: 'who', text: m.me ? 'You' : m.name }));
  }));
  $('choose-play').setAttribute('aria-pressed', String(panel.mine === 'player'));
  $('choose-watch').setAttribute('aria-pressed', String(panel.mine === 'spectator'));
  // One seat, one decision (ADR 0012): in Limited Mode, a phone that cannot play this game here
  // may still watch. Full Mode is not gated.
  const limits = seatChoice(state.mode, game, statuses(state.report), state.catalog.labels || {});
  $('choose-play').disabled = panel.starting || !limits.play;
  $('choose-watch').disabled = panel.starting || !limits.watch;
  $('scene-seat').textContent = limits.play ? '' : limits.why || 'This phone can only watch this one.';
  $('scene-start').hidden = !panel.host;
  $('scene-cancel').hidden = !panel.host || panel.starting;
  $('scene-start').disabled = !panel.canStart || state.partyBusy;
  $('scene-status').textContent = panel.starting ? 'Starting…'
    : panel.host ? panel.blocker || ''
      : `Waiting for ${panel.hostName || 'the host'} to start`;
}

function show(which) {
  // The drawer and the sheet belong to the frame: they never stay open over a round's setup or
  // the way to a game, where they would stand between a person and their answer.
  if (which !== 'main') for (const id of ['social', 'about-limited']) if ($(id).open) $(id).close();
  $('main').hidden = which !== 'main';
  $('scene').hidden = which !== 'scene';
  $('going').hidden = which !== 'going';
  document.documentElement.dataset.screen = which;
}

function onPartyView(view) {
  if (!state.partyMode) return;
  ensurePresent(view);
  const url = destination(view, HOME, state.catalog);
  if (url) {                                  // the party is in a round: this phone goes there
    const g = partyGame(state.catalog, locationOf(view).game);
    $('going-text').textContent = `Taking you to ${g ? g.name : 'your party'}…`;
    show('going');
    location.replace(url);
    return;
  }
  if (view.me && locationOf(view).at === 'setup') {
    show('scene');
    renderScene(view);
    return;
  }
  show('main');
  renderParty(view);
  renderGames(false);
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
    renderHud();                        // the chat is offered only while its own runtime answers
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
  const [reachable, loaded, report, partyView] = await Promise.all([
    checkReach(), loadCatalog(fetch), probeCapabilities(), party.probe(),
  ]);
  state.reachable = reachable;
  const catalog = loaded.catalog;       // empty, never null, when catalog.json is missing or corrupt (AVR-220)
  state.catalog = catalog;
  $('catalog-error').hidden = loaded.ok || !reachable;
  catalog.games.forEach((game) => profile.keyFor(game));
  state.report = report;
  $('away').hidden = reachable;
  $('games-section').hidden = !reachable;
  // Party mode only when the Pi answered, the catalog loaded and Party Core gave a real view.
  state.partyMode = Boolean(reachable && catalog && partyView);
  state.mode = modeOf(partyView);
  document.documentElement.dataset.mode = state.mode;
  document.documentElement.dataset.party = state.partyMode ? 'on' : 'off';
  $('party').hidden = !state.partyMode;
  $('party-people').hidden = !state.partyMode;
  if (state.partyMode) party.start(partyView);
  if (!reachable) {
    setStatus('away', 'Not connected to the party');
  } else {
    setStatus('ok', state.mode === LIMITED ? 'Connected in Limited Mode'
      : window.isSecureContext ? 'Connected to the party'
        : 'Connected. Open party.avrana.net for the full experience');
  }
  if (catalog) renderPhone();
  renderLimited();
  if (reachable && catalog) await renderGames();
  renderHome();
  renderHud();
  syncChat();
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
    const was = chatOn();
    state.chatStatus = snapshot.status;
    if (was !== chatOn()) renderHud();
    if (snapshot.status === 'connected') state.chatFails = 0;
    else if (snapshot.status === 'unavailable' && chatGivesUp(++state.chatFails)) { chat.close(); return; }
    const labels = { closed: chatGivesUp(state.chatFails) ? 'Chat isn’t available right now.' : 'Open to chat',
      connecting: 'Connecting…', unavailable: 'Chat is reconnecting…', profile_required: 'Save your profile to chat' };
    $('chat-status').textContent = snapshot.status === 'connected'
      ? snapshot.online + ' in chat' : labels[snapshot.status];
    $('chat-send').disabled = snapshot.status !== 'connected';
    const list = $('chat-messages');
    const atEnd = $('chat').scrollHeight - $('chat').scrollTop - $('chat').clientHeight < 40;
    list.replaceChildren(...snapshot.messages.map((m) =>
      h('li', { class: 'flex gap-3 py-2' }, avatarNode(m, 'sm'), h('div', { class: 'min-w-0' },
        h('strong', { class: 'text-[0.8125rem] font-medium text-muted', text: m.name }),
        h('p', { class: 'm-0 whitespace-pre-wrap', text: m.text }),
        m.photo ? h('p', { class: 'm-0 inline-flex items-center gap-1.5 text-[0.9375rem] text-muted' }, icon('image'), 'Photo shared') : null))));
    const pane = $('chat');
    if (atEnd) { list.scrollTop = list.scrollHeight; pane.scrollTop = pane.scrollHeight; }
  },
});
const renderProfile = wireProfile(profile, () => { renderGames(false); renderHome(); syncChat(true); syncPresence(); });
/** A saved profile is who this phone is at the party: join with it, or show the new name. */
function syncPresence() {
  const view = party.view(), who = partyIdentity();
  if (!state.partyMode || !view || !who) return;
  if (view.me) party.rename(who.name, who.avatar); else ensurePresent(view);
}
const party = createPartyClient({ onView: onPartyView });
$('choose-play').onclick = () => choose('player');
$('choose-watch').onclick = () => choose('spectator');
$('scene-start').onclick = async () => {
  if (state.partyBusy) return;
  state.partyBusy = true;
  $('scene-start').disabled = true;
  const res = await party.startRound();
  state.partyBusy = false;
  if (!res.ok) $('scene-status').textContent = res.message || 'The round didn’t start. Please try again.';
  const view = party.view();
  if (view) onPartyView(view);
};
$('scene-cancel').onclick = async () => {        // the host: back home, everyone with them
  const res = await party.end();
  if (!res.ok) $('scene-status').textContent = res.message || 'Please try again.';
};
$('scene-rules').onclick = async () => {
  const view = party.view();
  const game = view && partyGame(state.catalog, view.session && view.session.game);
  if (game) openRules(game, await onboardingFor(game));
};
$('rules-close').onclick = () => { state.rulesThen = null; $('rules').close(); };
$('rules-ok').onclick = async () => {
  const view = party.view();
  const game = view && partyGame(state.catalog, view.session && view.session.game);
  if (game) acknowledge(await onboardingFor(game));
  const then = state.rulesThen;
  state.rulesThen = null;
  $('rules').close();
  if (then) then();
};
/** Today's chat is connected only while it is on screen: the drawer open, on its Chat side. */
function syncChat(reconnect = false) {
  const showing = $('social').open && state.tab === 'chat';
  const nameless = showing && state.reachable && !profile.snapshot().name;
  $('chat-name').hidden = !nameless;
  if (state.reachable && showing && !nameless) {
    if (chatGivesUp(state.chatFails)) return;                 // it said so; opening the side again tries again
    const opened = chat.open();
    if (reconnect && !opened) chat.reconnect();
  } else {
    chat.close();
    if (nameless) $('chat-status').textContent = 'Choose your name to chat.';
  }
}
$('hud').onclick = () => openSocial(null);
$('party-chat').onclick = () => openSocial('chat');
$('social-tabs').onclick = (event) => {
  const button = event.target.closest('button[data-tab]');
  if (!button) return;
  state.tab = button.dataset.tab;
  state.chatFails = 0;
  renderSocial();
};
$('social-close').onclick = () => $('social').close();
$('social').addEventListener('close', () => syncChat());
$('chat-name').onclick = () => { $('social').close(); openProfile(); };
// "Skip to the games": the Library, with focus on its heading (the title, when there are none to show).
$('skip').onclick = (event) => {
  event.preventDefault();
  if ($('main').hidden) return;
  if (state.page !== 'library') { history.pushState(null, '', '#library'); showPage('library'); }
  ($('games-section').hidden ? $('top-title') : $('games-h')).focus();
};
$('limited-mark').onclick = () => { if (!$('about-limited').open) $('about-limited').showModal(); };
$('about-close').onclick = () => $('about-limited').close();
$('about-done').onclick = () => $('about-limited').close();
// A tap outside either one closes it (the dialog element itself is only its backdrop and edge).
for (const id of ['social', 'about-limited'])
  $(id).addEventListener('click', (event) => { if (event.target === $(id)) $(id).close(); });
$('home-name').onclick = () => openProfile();
window.addEventListener('hashchange', () => {
  if (location.hash === '#diag') { location.replace('diag/'); return; }
  // The phone's Back, or a link: nothing stays open over a place that changed underneath it.
  for (const id of ['social', 'about-limited']) if ($(id).open) $(id).close();
  showPage(pageOf(location.hash), true);
});
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
$('catalog-retry').addEventListener('click', () => { boot(); });
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return;
  if (state.partyMode) party.poke();          // a phone waking up asks Party Core at once
  (state.reachable === false ? boot() : refreshHealth());
});
window.addEventListener('pageshow', (event) => { if (event.persisted) boot(); else syncChat(); });
showPage(pageOf(location.hash));
window.addEventListener('online', () => { if (state.reachable === false) boot(); });
state.healthTimer = setInterval(refreshHealth, HEALTH_EVERY_MS);
boot();
