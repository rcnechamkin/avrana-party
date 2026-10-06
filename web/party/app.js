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
import { donorAvailability, visibleGames, launchTarget } from './lib/catalog-view.js';
import { HOME, destination, locationOf, partyGame, roster, roundToRemember, setupPanel, tileMode } from './lib/party-mode.js';
import { createPartyClient } from './lib/party-client.js';
import { LIMITED, blockedGames, limitedNotice, modeOf, seatChoice } from './lib/limited.js';
import { VIEW_NAMES, arrange, consequence, filterLabel, fitLine, homeShelves, leadLine, seatsMark, seatsPhrase, viewOf } from './lib/library.js';
import { backWord, chatGivesUp, chatOffered, gameOf, hereLine, hostLine, hudLabel, namesLine, pageOf, pageTitle, startTab } from './lib/frame.js';

const $ = (id) => document.getElementById(id);
// "This phone" list, most useful first. Labels come from the catalog (contracts/capabilities.v0.json).
const PHONE_CHECKS = ['secure_context', 'webrtc', 'video.h264', 'wake_lock', 'web_audio', 'gamepad', 'vibration'];
const ESSENTIAL = ['secure_context', 'webrtc', 'video.h264'];
const HEALTH_EVERY_MS = 15000;

const state = { catalog: null, report: null, shell: null, reachable: null, healthTimer: null, donor: null, healths: new Map(), view: 'all',
  partyMode: false, partyBusy: false, joining: false, failShown: null, acked: false, rulesThen: null,
  mode: 'full', page: 'home', tab: 'people', chatStatus: 'closed', chatFails: 0,
  polled: false, libView: 'medium', filters: { players: 0, screen: 'any' },
  // screen: what has the frame's middle (main: a place; scene: the briefing; going: on the way to a game)
  // game: the title whose page is open; back: where that page was opened from, to return there exactly
  screen: 'main', game: null, back: null, rulesGame: null };

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
    // No answer at all (out of range, a slow box): the tile still cannot be played from here, but
    // nobody knows the game is off, and the shelf does not say so (lib/library.js consequence).
    return { running: false, unknown: true };
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

/** Keep or drop a favourite: a toggle with a name per game. Focus stays on it after the redraw. */
function favButton(game, cls = '') {
  const on = profile.isFavorite(game);
  return h('button', { type: 'button', class: 'btn btn-ghost btn-square avrana-fav ' + cls, 'data-fav': game.id,
    'aria-label': (on ? 'Remove ' : 'Add ') + game.name + (on ? ' from favorites' : ' to favorites'),
    'aria-pressed': String(on), onclick: (event) => {
      const within = event.currentTarget.closest('#game-detail, #games');
      try { profile.toggleFavorite(game); renderProfile(); renderGames(false); }
      catch (err) { $('profile-note').textContent = err.message; }
      // The redraw replaced this button. When its row has left the shelf (un-kept in Favorites),
      // focus goes to the tab that is showing, never nowhere.
      const again = within && within.querySelector(`[data-fav="${CSS.escape(game.id)}"]`);
      (again || (within && within.id === 'games' ? $('game-views').querySelector('[aria-pressed="true"]') : null))?.focus();
    } }, icon('heart'));
}

/** A cover: the title's own art, else its kind icon on its own colour. `mark` is the player
 * range for the corner (lib/library.js seatsMark), or null. `shape`: 'wide' for the lead cover on
 * Home, a game's page and the briefing; square otherwise. */
function tileCover(game, mark, shape = '') {
  const art = ARTWORK.test(game.artwork || '') ? game.artwork : null;
  const el = h('span', { class: 'avrana-cover' + (shape ? ' ' + shape : '') + (art ? ' has-art' : '') + (art && art.startsWith('art/kenney-') ? ' icon-art' : '') },
    art ? h('img', { src: art, alt: '', loading: 'lazy', decoding: 'async' }) : icon(kindIcon(game)),
    mark ? h('span', { class: 'seats' + (mark.ok ? '' : ' no') }, icon(mark.ok ? 'users' : 'triangle-alert'), mark.text) : null);
  if (ACCENT.test(game.accent || '')) el.style.setProperty('--game-accent', game.accent);
  return el;
}

const warnLine = (note, cls) => (note ? h('span', { class: cls }, icon(note.icon), note.text) : null);
/** What a cover says to a screen reader: the title, who can play, where it is seen, and anything
 * that stands in the way on this phone. */
const spoken = ({ game, note }, people) => [game.name,
  seatsMark(game, people).ok ? playersText(game.players) : seatsPhrase(game, people),
  screenText(game).text, note && note.text].filter(Boolean).join('. ');

/** Where a cover leads: the game's own page. The link is a real one (the phone's Back returns);
 * the click only notes where it was opened from, so Back lands on the same cover. */
const gameLink = (game) => ({ href: '#game/' + game.id, onclick: (event) => leaveFor(game.id, event.currentTarget) });

/** A cover on a shelf. It opens the game's page; it never starts one. */
function tile(entry, people, { seats = true, meta = true } = {}) {
  const { game, note } = entry;
  return h('li', {}, h('a', { class: 'avrana-tile', 'data-game': game.id, 'data-note': note ? note.kind : null,
    'aria-label': spoken(entry, people), ...gameLink(game) },
  tileCover(game, seats ? seatsMark(game, people) : null),
  h('span', { class: 't', text: game.name }),
  meta ? h('span', { class: 'm', text: screenText(game).text }) : null,
  warnLine(note, 'm warn')));
}

/** The same title as a row of the list, with its sentence and its facts in words. */
function row(entry, people) {
  const { game, note } = entry;
  const mark = seatsMark(game, people), screen = screenText(game);
  return h('li', { class: 'avrana-row' },
    h('a', { class: 'open', 'data-game': game.id, 'data-note': note ? note.kind : null,
      'aria-label': spoken(entry, people), ...gameLink(game) },
    tileCover(game, null),
    h('span', {}, h('span', { class: 't', text: game.name }),
      game.summary ? h('span', { class: 'd', text: game.summary }) : null,
      h('span', { class: 'f' },
        h('span', { class: mark.ok ? null : 'no' }, icon(mark.ok ? 'users' : 'triangle-alert'), seatsPhrase(game, people)),
        h('span', {}, icon(screen.icon), screen.text),
        warnLine(note, 'no')))),
    favButton(game));
}

/** Put `next` where `parent`'s children are, touching only what changed, so a periodic refresh
 * never moves keyboard focus off an unchanged control. A child marked data-sync="list" is kept and
 * its own children are compared the same way. */
function sync(parent, next) {
  const old = [...parent.children];
  if (old.length !== next.length || old.some((el, i) => el.tagName !== next[i].tagName || el.className !== next[i].className)) {
    parent.replaceChildren(...next);
    return;
  }
  next.forEach((node, i) => {
    if (old[i].isEqualNode(node)) return;
    if (node.dataset.sync !== 'list') { old[i].replaceWith(node); return; }
    for (const attr of [...old[i].attributes]) if (!node.hasAttribute(attr.name)) old[i].removeAttribute(attr.name);
    for (const attr of node.attributes) old[i].setAttribute(attr.name, attr.value);
    sync(old[i], [...node.children]);
  });
}

function liveText(hp) {
  if (!hp) return null;
  if (!hp.running) return 'Not running right now';
  if (hp.players !== null && hp.max !== null) {
    return hp.players >= hp.max ? 'Full right now' : `${hp.players} of ${hp.max} playing`;
  }
  return 'Running';
}

/** A game's own page: what it is, whether it suits the people here and this phone, and its one
 * button. The facts, the fit, the live state and the button are the ones the Library's tile has
 * always had; only the Host's button moves the Party, and it does what it did. */
function detailNodes(entry, people) {
  const { game, result, live: hp, note } = entry;
  const ob = ONBOARDING.get(game.id) || null;
  const target = launchTarget(game);
  const installed = Boolean(game.installed && game.entry);
  const why = installed ? explain(result, state.catalog.labels || {}) : '';
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
  const view = state.partyMode ? party.view() : null;
  const mode = view ? tileMode(game, view) : null;
  const action = mode ? partyAction(game, mode, view.members.find((m) => m.host))
    : running && fits
    ? h('a', { class: 'btn btn-primary', href: target, onclick: remember }, icon(label === 'Watch' ? 'eye' : 'play'), label)
    : running
      ? h('a', { class: 'btn btn-outline', href: target, onclick: remember, text: 'Try anyway' })
      : h('button', { type: 'button', class: 'btn', disabled: true, text: installed ? 'Play' : 'Not installed' });
  // What the Host's button does to everyone, said beside it (it moves the whole Party at once).
  const helper = !mode ? null : mode.kind === 'start' ? 'Moves everyone to this game.'
    : mode.kind === 'wait' ? null : 'Everyone plays together: the host starts it.';
  const live = mode ? null
    : installed && hp?.integration === false ? 'Games update needed before opening here' : installed ? liveText(hp) : 'Experimental · Not installed on this Party box';
  const screen = screenText(game);
  const how = howText(game);
  const fit = view && view.me ? fitLine(game, people) : null;
  const premise = (ob && ob.premise) || game.summary || '';
  return [
    tileCover(game, null, 'wide'),
    h('h1', { id: 'game-title', tabindex: '-1', text: game.name }),
    premise ? h('p', { class: 'avrana-premise', text: premise }) : null,
    h('p', { class: 'avrana-game-facts m-0' },
      h('span', {}, icon('users'), playersText(game.players)),
      h('span', {}, icon(screen.icon), screen.text)),
    how ? h('p', { class: 'avrana-line quiet', text: capitalize(how) }) : null,
    game.hardwareValidationRequired ? h('p', { class: 'avrana-line quiet', text: 'Needs a device check before use.' }) : null,
    fit ? h('p', { class: 'avrana-line' + (fit.ok ? '' : ' warn'), 'data-suits': String(fit.ok) }, icon(fit.icon), h('span', { text: fit.text })) : null,
    // where the page does not already say it in the game's own words (a Party game, whose live
    // line is the Host's): the same words as its cover
    mode && note && note.kind === 'off' ? h('p', { class: 'avrana-line warn', 'data-note': note.kind }, icon(note.icon), h('span', { text: note.text })) : null,
    installed ? h('div', { class: 'grid gap-1' }, chipFor(result), why ? h('p', { class: 'why m-0', text: why }) : null) : null,
    live ? h('p', { class: 'avrana-line quiet', text: live }) : null,
    h('div', { class: 'avrana-act' }, action, favButton(game)),
    helper ? h('p', { class: 'avrana-helper', text: helper }) : null,
    ob ? h('ul', { class: 'avrana-list' }, h('li', {}, h('button', { type: 'button', 'data-rules': game.id, 'aria-haspopup': 'dialog',
      onclick: () => openRules(game, ob) }, icon('book-open'), h('span', { text: 'How to play' }), h('span', { class: 'val' }, icon('chevron-right'))))) : null,
  ].filter(Boolean);
}

// ---- Party mode (ADR 0011: one party, one place, the host moves it) ---------------------------

/** A party game's button, while the party is home. The host's start is the only way it begins;
 * everyone else reads who starts it, as a sentence and not a button that cannot be pressed. */
function partyAction(game, mode, host) {
  if (mode.kind === 'profile') {
    return h('button', { type: 'button', class: 'btn btn-outline', text: 'Choose your name to play',
      onclick: () => openProfile() });
  }
  if (mode.kind === 'start') {
    return h('button', { type: 'button', class: 'btn btn-primary', disabled: state.partyBusy,
      onclick: () => hostStart(game, mode.game) }, icon('play'), 'Start for everyone');
  }
  if (mode.kind === 'wait') {
    return h('p', { class: 'wait', 'data-wait': '' }, icon('users'),
      h('span', { text: `The host starts it. ${host ? `${host.name} chooses what the Party plays.` : 'Nobody is hosting right now.'}` }));
  }
  return h('button', { type: 'button', class: 'btn', disabled: true, text: 'Starting…' });
}

async function hostStart(game, id) {
  if (state.partyBusy) return;
  state.partyBusy = true;
  $('party-note').textContent = '';
  renderGames(false);
  const res = await party.launch(id);
  state.partyBusy = false;
  if (!res.ok) {
    $('party-note').textContent = res.message || `${game.name} didn’t start. Please try again.`;
    $('content').scrollTop = 0;                  // the reason is at the top of the page, in sight
  }
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
  // The briefing has no Home to say it on, so it carries the mark; its sheet has no link that
  // leaves the page (GAME-UX-CONTRACT rule 3.2).
  const brief = state.screen === 'scene';
  $('limited-mark').hidden = !on || (!brief && state.page === 'home');
  $('about-leave').hidden = brief;
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
function showPage(page, focus = false, game = null) {
  state.page = page;
  state.game = page === 'game' ? game : null;
  if (page !== 'game') {                       // nothing of the last game's page is kept behind
    state.back = null;
    $('game-detail').replaceChildren();
    for (const key of ['id', 'outcome', 'party']) delete $('game-detail').dataset[key];
  }
  for (const el of $('content').querySelectorAll('[data-page]')) el.hidden = el.dataset.page !== page;
  // A game's page is not a place of its own: the bar keeps the place it was opened from.
  const under = page === 'game' ? (state.back ? state.back.page : 'library') : page;
  for (const link of $('nav').querySelectorAll('a')) {
    if (link.dataset.go === under) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
  }
  document.documentElement.dataset.place = page;
  if (page === 'game') document.documentElement.dataset.game = game; else delete document.documentElement.dataset.game;
  renderTop();
  renderLimited();
  if (page === 'game') renderGames(false);
  if (focus) { $('content').scrollTop = 0; titleEl().focus({ preventScroll: true }); }
}

/** The heading that names what is on screen, for focus after a move: the top bar's title, or on a
 * game's page the game's own name (the bar there holds the way back). */
const titleEl = () => (state.screen === 'main' && state.page === 'game' ? $('game-title') || $('top-back') : $('top-title'));

/** The top bar: the place's title; on a game's page, the way back; on a briefing, "Getting ready". */
function renderTop() {
  const brief = state.screen === 'scene', game = !brief && state.page === 'game';
  const from = state.back ? state.back.page : 'library';
  $('top-back').hidden = !game;
  $('top-back').setAttribute('href', '#' + from);
  $('top-back-word').textContent = backWord(from);
  $('top-title').hidden = game;
  const title = brief ? 'Getting ready' : pageTitle(state.page);
  $('top-title').textContent = title;
  $('top-title').classList.toggle('brand', !brief && state.page === 'home');
  $('top-title').classList.toggle('quiet', brief);
  if (!game) document.title = !brief && state.page === 'home' ? title : `${title} · Avrana Party`;
}

/** A cover was tapped: note where, so the way back lands on the same cover at the same scroll. */
function leaveFor(id, cover) {
  state.back = { page: state.page === 'game' ? 'library' : state.page, scroll: $('content').scrollTop, id,
    within: cover.closest('#games, #home-games')?.id || null };
}

/** Show what the address names: a game's page, or one of the four places. Coming back from a
 * game's page to the place it was opened from restores that place as it was. */
function go(focus = true) {
  const id = gameOf(location.hash);
  if (id) { showPage('game', focus, id); return; }
  const page = pageOf(location.hash), back = state.back;
  const returning = Boolean(back && back.page === page);
  showPage(page, focus && !returning);
  if (!returning || !focus) return;
  $('content').scrollTop = back.scroll;
  const cover = (back.within ? $(back.within) : $('content')).querySelector(`[data-game="${CSS.escape(back.id)}"]`);
  (cover || $('top-title')).focus({ preventScroll: true });
}

/** Your name and avatar live on the Party page. */
function openProfile() {
  closeSheets();
  if (state.page !== 'party') { history.replaceState(null, '', '#party'); showPage('party'); }
  $('profile').open = true;
  $('profile-name').focus();
}

const chatOn = () => chatOffered({ reachable: state.reachable, hub: state.donor !== null && state.donor !== undefined, status: state.chatStatus });

/** Home's own words: a nameless phone's first step. Its shelves are drawn with the Library. */
function renderHome() {
  $('home-name').hidden = Boolean(profile.snapshot().name);
  if (state.reachable === false) $('home-games').hidden = true;   // nothing to browse while the Pi is out of reach
}

/** Everything open over the frame. None of it may stay over a place that changed underneath, or
 * over the Party moving (to a briefing, to a game, home again). */
const SHEETS = ['social', 'about-limited', 'lib-filters', 'lib-views'];
function closeSheets() {
  for (const id of SHEETS) if ($(id).open) $(id).close();
  if ($('rules').open) $('rules').close();
}

/** The Party control: faces and a count while there is a party; a chat mark when there is only
 * the chat; nothing when there is neither. */
function renderHud() {
  const view = state.partyMode ? party.view() : null;
  const people = view ? roster(view) : [];
  $('party-chat-row').hidden = !chatOn();
  const chatting = chatOn() && state.screen !== 'scene';      // people only over a briefing
  $('hud').hidden = !(people.length || chatting);
  $('hud').setAttribute('aria-label', hudLabel({ party: people.length > 0, count: people.length, chat: chatting }));
  $('hud-faces').replaceChildren(...(people.length
    ? people.slice(0, 3).map((m) => avatarNode({ avatar: m.avatar || '' }, 'xs'))
    : [icon('message-circle')]));
  $('hud-count').textContent = people.length > 3 ? `+${people.length - 3}` : '';
  if ($('social').open) renderSocial();
}

function renderSocial() {
  const view = state.partyMode ? party.view() : null;
  // Over a briefing the drawer is the people here and nothing else (GAME-UX-CONTRACT rule 3.2):
  // no chat, no way out. It says where the Party is.
  const brief = state.screen === 'scene';
  const chatting = chatOn() && !brief;
  const tab = startTab({ party: Boolean(view), chat: chatting, want: brief ? 'people' : state.tab });
  if (!tab) { $('social').close(); return; }
  state.tab = tab;
  const playing = brief && view ? partyGame(state.catalog, view.session && view.session.game) : null;
  $('social-where').hidden = !brief;
  $('social-where').textContent = brief ? `Getting ready${playing ? ` for ${playing.name}` : ''}.` : '';
  $('social-tabs').hidden = !(view && chatting);
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
  const chatting = chatOn() && state.screen !== 'scene';
  if (startTab({ party: state.partyMode && Boolean(party.view()), chat: chatting, want }) && !$('social').open) $('social').showModal();
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
    closeSheets();
    $('content').scrollTop = 0;                  // the reason is at the top of the page, in sight
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
  state.rulesGame = game;
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
  sync($('scene-cover'), [tileCover(game, null, 'wide')]);
  const ob = await onboardingFor(game);
  $('scene-premise').textContent = (ob && ob.premise) || game.summary || '';
  // Each person's answer is an icon and a word; the Host is marked by the word.
  const words = { player: ['check', 'Playing'], spectator: ['eye', 'Watching'] };
  const people = roster(view);
  $('scene-count').textContent = `${panel.players} playing · ${panel.spectators} watching`;
  $('scene-roster').replaceChildren(...people.map((m) => {
    const [ic, text] = words[m.choice] || ['hourglass', 'Choosing'];
    return h('li', { 'data-choice': m.choice || null, 'data-away': m.away ? '' : null, 'data-host': m.host ? '' : null },
      avatarNode({ avatar: m.avatar || '' }),
      h('span', { class: 'who' }, h('span', { text: m.me ? 'You' : m.name }),
        m.host ? h('span', { class: 'avrana-tag', text: 'Host' }) : null),
      h('span', { class: 'ans' }, icon(ic), h('span', { text: text })),
      m.away ? h('span', { class: 'avrana-tag quiet', text: 'Away' }) : null);
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

/** Which screen has the phone: a place of the frame (main), the briefing (scene) or the way to a
 * game (going). Where the Party is decides, never the address. The briefing keeps the frame's top
 * bar (who is here, the Limited mark) and nothing else of it. */
function show(which) {
  const moved = which !== state.screen;
  // Whatever was open belonged to the screen that was there: an authoritative move closes it, so
  // nothing stands between a person and where the Party now is. (While the screen stays, the
  // drawer and the sheet stay open over it: a briefing keeps its place under them.)
  if (moved) closeSheets();
  state.screen = which;
  $('main').hidden = which === 'going';
  $('content').hidden = which !== 'main';
  $('nav').hidden = which !== 'main';
  $('scene').hidden = which !== 'scene';
  $('going').hidden = which !== 'going';
  $('skip').hidden = which !== 'main';
  document.documentElement.dataset.screen = which;
  if (!moved) return;
  renderTop();
  renderLimited();
  if (which === 'scene') $('scene-scroll').scrollTop = 0;
  if (which !== 'going') titleEl().focus({ preventScroll: true });
}

function onPartyView(view) {
  if (!state.partyMode) return;
  ensurePresent(view);
  const url = destination(view, HOME, state.catalog);
  if (url) {                                  // the party is in a round: this phone goes there
    const g = partyGame(state.catalog, locationOf(view).game);
    const round = roundToRemember(view);       // a round that is on, not its held results
    if (g && round) recordRound(g, round);
    $('going-text').textContent = `Taking you to ${g ? g.name : 'your party'}…`;
    show('going');
    location.replace(url);
    return;
  }
  if (view.me && locationOf(view).at === 'setup') {
    show('scene');
    renderHud();                              // who is here, over the briefing too
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
        // an error status, or an answer that is not the list, is an answer; only silence is silence
        .then(donorAvailability).catch((err) => (err && (err.status || err instanceof SyntaxError) ? null : SILENT)),
      ...installed.map((g) => health(g.health)),
    ]);
    state.donor = donor === SILENT ? null : donor;
    state.donorSilent = donor === SILENT;       // no answer at all, which is not "off"
    state.healths = new Map(installed.map((g, i) => [g.id, healths[i]]));
    state.polled = true;
    renderHud();                        // the chat is offered only while its own runtime answers
  }
  if (state.reachable === false || !state.polled) return;      // nothing is "off" before the first answer
  const caps = statuses(state.report);
  const entries = new Map();
  for (const game of visibleGames(state.catalog)) {
    profile.keyFor(game);
    const live = game.legacySlug ? state.donor?.get(game.legacySlug) || { running: false, unknown: state.donorSilent }
      : state.healths?.get(game.id);
    const result = evaluateSeat(game, caps, 'player');
    const installed = Boolean(game.installed && game.entry);
    entries.set(game.id, { game, live, result, note: consequence({ installed, outcome: result.outcome, live }) });
  }
  const view = state.partyMode ? party.view() : null;
  const people = view ? view.members.length : 0;
  const me = profile.snapshot();
  const all = [...entries.values()].map((entry) => entry.game);
  renderShelf(entries, arrange({ all, people, tab: state.view, query: $('game-search').value, filters: state.filters,
    keyOf: profile.keyFor, favorites: me.favorites, recent: me.recent }), people);
  renderHomeShelves(entries, homeShelves({ all, people, keyOf: profile.keyFor, recent: me.recent }), people);
  renderDetail(entries, people);
}

const SILENT = Symbol('no answer');
const VIEW_ICONS = { large: 'grid-2x2', medium: 'grid-3x3', compact: 'layout-grid', list: 'list' };
const gamesWord = (n) => (n === 1 ? '1 game' : `${n} games`);

/** The Library: its shelves (or what stands in for them), and controls that say the same thing. */
function renderShelf(entries, shelf, people) {
  const of = (game) => entries.get(game.id);
  const reset = () => { state.filters = { players: 0, screen: 'any' }; renderGames(false); };
  const nodes = [];
  if (shelf.empty) {
    const undo = { search: () => { $('game-search').value = ''; renderGames(false); $('game-search').focus(); },
      filters: () => { reset(); $('lib-filter').focus(); },
      favorites: () => seeAll(), recent: () => seeAll() }[shelf.empty.kind];
    // (#game-count announces the same title; this block is not a second live region)
    nodes.push(h('div', { class: 'avrana-blank', 'data-empty': shelf.empty.kind }, icon(shelf.empty.icon),
      h('h3', { text: shelf.empty.title }), h('p', { text: shelf.empty.text }),
      h('button', { type: 'button', class: 'btn', text: shelf.empty.action, onclick: undo })));
  } else if (!shelf.total) {
    // no list at all: #catalog-error says so, and nothing here pretends otherwise
  } else if (state.libView === 'list') {
    const group = shelf.groups.length === 1 ? shelf.groups[0] : { title: 'All games', meta: `${shelf.count}, best fit first` };
    nodes.push(secHead(group, reset),
      h('ul', { class: 'avrana-rows', 'data-sync': 'list', 'aria-label': group.title }, shelf.flat.map((g) => row(of(g), people))));
  } else {
    for (const group of shelf.groups) {
      nodes.push(secHead(group, reset),
        h('ul', { class: 'avrana-grid ' + state.libView, 'data-sync': 'list', 'aria-label': group.title },
          group.games.map((g) => tile(of(g), people))));
    }
  }
  if (!shelf.empty && shelf.hidden) {
    nodes.push(h('p', { class: 'avrana-hid' }, `${gamesWord(shelf.hidden)} hidden by ${shelf.filtersOn === 1 ? 'this filter' : 'these filters'}. `,
      h('button', { type: 'button', class: 'avrana-textlink', text: 'Show all', onclick: () => { reset(); $('lib-filter').focus(); } })));
  }
  sync($('games'), nodes);
  $('games').setAttribute('aria-busy', 'false');
  $('games').dataset.view = state.libView;
  $('game-count').textContent = !shelf.total ? '' : shelf.empty ? shelf.empty.title : shelf.filtersOn || shelf.count !== shelf.total
    ? `${gamesWord(shelf.count)} of ${shelf.total}` : gamesWord(shelf.count);
  // the controls and the sheets agree with the results
  $('lib-filter').setAttribute('aria-label', filterLabel(state.filters));
  $('lib-filter-count').textContent = String(shelf.filtersOn);
  $('lib-filter-count').hidden = !shelf.filtersOn;
  $('filters-show').textContent = `Show ${gamesWord(shelf.count)}`;
  $('filters-party').textContent = people >= 1 ? `Your Party is ${people}` : '';
  for (const b of $('filter-players').querySelectorAll('button')) b.setAttribute('aria-pressed', String(Number(b.dataset.players) === state.filters.players));
  for (const b of $('filter-screens').querySelectorAll('button')) b.setAttribute('aria-pressed', String(b.dataset.screen === state.filters.screen));
  for (const b of $('view-choices').querySelectorAll('button')) b.setAttribute('aria-pressed', String(b.dataset.v === state.libView));
  $('lib-view').setAttribute('aria-label', 'View: ' + VIEW_NAMES[state.libView].toLowerCase());
  if ($('lib-view').dataset.shown !== state.libView) {
    $('lib-view').dataset.shown = state.libView;
    $('lib-view').replaceChildren(icon(VIEW_ICONS[state.libView]));
  }
}

function secHead(group, reset) {
  return h('div', { class: 'avrana-sec' }, h('h3', { text: group.title }),
    group.reset ? h('button', { type: 'button', class: 'avrana-textlink', text: 'Reset', onclick: () => { reset(); $('lib-filter').focus(); } })
      : h('span', { class: 'meta', text: group.meta }));
}

function setTab(name) {
  state.view = name;
  for (const item of $('game-views').querySelectorAll('button'))
    item.setAttribute('aria-pressed', String(item.dataset.view === name));
  renderGames(false);
}

/** "See all games" from an empty Favorites or Recent: the button goes away, so focus goes to All. */
function seeAll() {
  setTab('all');
  $('game-views').querySelector('[data-view="all"]').focus();
}

/** Home's shelves, from the same titles and the same words as the Library. */
function renderHomeShelves(entries, shelves, people) {
  const of = (game) => entries.get(game.id);
  $('home-games').hidden = !shelves.lead;
  if (!shelves.lead) return;
  const lead = of(shelves.lead);
  const line = leadLine(lead.game, { people, played: shelves.leadPlayed }) || playersText(lead.game.players);
  sync($('home-lead'), [h('a', { class: 'avrana-hero', 'data-game': lead.game.id, 'data-note': lead.note ? lead.note.kind : null,
    'aria-label': [lead.game.name, line, lead.note && lead.note.text].filter(Boolean).join(' '), ...gameLink(lead.game) },
  tileCover(lead.game, seatsMark(lead.game, people), 'wide'),
  h('span', { class: 'row' }, h('span', {}, h('span', { class: 't', text: lead.game.name }), h('span', { class: 'm', text: line }),
    warnLine(lead.note, 'm warn')), icon('chevron-right')))]);
  $('home-great-h').textContent = shelves.title;
  $('home-great-sec').hidden = !shelves.great.length;        // never a heading over nothing
  sync($('home-great'), shelves.great.map((g) => tile(of(g), people)));
  $('home-recent-sec').hidden = !shelves.played.length;
  sync($('home-recent'), shelves.played.map((g) => tile(of(g), people, { seats: false, meta: false })));
}

/** The game's page, when it is the one on screen. A title that is not on the shelf (an old link, a
 * typo) is the Library. Its premise comes with the game's onboarding, which arrives a moment
 * after the page: the catalog's own sentence stands in until then. */
function renderDetail(entries, people) {
  if (state.page !== 'game') return;
  const entry = entries.get(state.game);
  if (!entry) {
    history.replaceState(null, '', '#library');
    showPage('library', document.activeElement === document.body);
    return;
  }
  const { game, result } = entry, root = $('game-detail');
  const mode = state.partyMode && party.view() ? tileMode(game, party.view()) : null;
  root.dataset.id = game.id;
  root.dataset.outcome = game.installed && game.entry ? result.outcome : 'unavailable';
  if (mode) root.dataset.party = mode.kind; else delete root.dataset.party;
  sync(root, detailNodes(entry, people));
  document.title = `${game.name} · Avrana Party`;
  if (game.installed && game.entry && !ONBOARDING.has(game.id)) {
    onboardingFor(game).then((ob) => { if (ob && state.game === game.id) renderGames(false); });
  }
}

/** A round that takes this phone to a game is remembered on this phone (the same list, and the
 * same count, the Play button has always written), once per round however often, and in however
 * many tabs, the page is opened during it. Whoever the Party took there is recorded, players
 * and watchers alike. */
function recordRound(game, where) {
  const round = String(where.session || game.id);
  try {
    if (localStorage.getItem('avrana-recent-round') === round) return;
    localStorage.setItem('avrana-recent-round', round);
  } catch { /* a phone that keeps nothing: remember() below keeps nothing either */ }
  try { profile.remember(game); } catch { /* this phone keeps nothing */ }
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
$('rules-close').onclick = () => $('rules').close();
// Close, Escape or a tap outside: the rules go away and nothing is chosen for the reader.
$('rules').addEventListener('click', (event) => { if (event.target === $('rules')) $('rules').close(); });
$('rules').addEventListener('close', () => { state.rulesThen = null; });
$('rules-ok').onclick = async () => {
  const game = state.rulesGame;
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
  if (state.screen !== 'main') return;
  if (state.page !== 'library') { history.pushState(null, '', '#library'); showPage('library'); }
  ($('games-section').hidden ? $('top-title') : $('games-h')).focus();
};
$('limited-mark').onclick = () => { if (!$('about-limited').open) $('about-limited').showModal(); };
$('about-close').onclick = () => $('about-limited').close();
$('about-done').onclick = () => $('about-limited').close();
// A tap outside either one closes it (the dialog element itself is only its backdrop and edge).
for (const id of SHEETS)
  $(id).addEventListener('click', (event) => { if (event.target === $(id)) $(id).close(); });
$('home-name').onclick = () => openProfile();
window.addEventListener('hashchange', () => {
  if (location.hash === '#diag') { location.replace('diag/'); return; }
  // The phone's Back, or a link: nothing stays open over a place that changed underneath it.
  closeSheets();
  go();
});
// Back, on a game's page: the way it was reached, so the place is as it was left. Reached by a
// link from elsewhere (or a reload), it is simply a link to the Library.
$('top-back').onclick = (event) => {
  if (!state.back) return;
  event.preventDefault();
  history.back();
};
$('chat-form').onsubmit = (event) => {
  event.preventDefault();
  if (chat.send($('chat-text').value)) {
    $('chat-text').value = ''; $('chat-feedback').textContent = '';
  } else $('chat-feedback').textContent = 'Chat is not connected yet. Please try again.';
};
$('game-search').oninput = () => renderGames(false);
$('game-views').onclick = (event) => {
  const button = event.target.closest('button[data-view]');
  if (button) setTab(button.dataset.view);
};
// The Library's two sheets. A choice shows at once behind the sheet; the view is kept on this phone.
try { state.libView = viewOf(localStorage.getItem('avrana-library-view')); } catch { /* the medium grid */ }
$('lib-filter').onclick = () => { if (!$('lib-filters').open) $('lib-filters').showModal(); };
$('lib-view').onclick = () => { if (!$('lib-views').open) $('lib-views').showModal(); };
$('filter-players').onclick = (event) => {
  const button = event.target.closest('button[data-players]');
  if (!button) return;
  state.filters = { ...state.filters, players: Number(button.dataset.players) };
  renderGames(false);
};
$('filter-screens').onclick = (event) => {
  const button = event.target.closest('button[data-screen]');
  if (!button) return;
  state.filters = { ...state.filters, screen: button.dataset.screen };
  renderGames(false);
};
$('filters-reset').onclick = () => { state.filters = { players: 0, screen: 'any' }; renderGames(false); };
$('filters-show').onclick = () => $('lib-filters').close();
$('filters-close').onclick = () => $('lib-filters').close();
$('view-choices').onclick = (event) => {
  const button = event.target.closest('button[data-v]');
  if (!button) return;
  state.libView = viewOf(button.dataset.v);
  try { localStorage.setItem('avrana-library-view', state.libView); } catch { /* this phone keeps nothing */ }
  renderGames(false);
  $('lib-views').close();
};
$('views-close').onclick = () => $('lib-views').close();
window.addEventListener('pagehide', () => { chat.close(); party.stop(); });

$('retry').addEventListener('click', () => { boot(); });
$('catalog-retry').addEventListener('click', () => { boot(); });
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return;
  if (state.partyMode) party.poke();          // a phone waking up asks Party Core at once
  (state.reachable === false ? boot() : refreshHealth());
});
window.addEventListener('pageshow', (event) => { if (event.persisted) boot(); else syncChat(); });
go(false);
window.addEventListener('online', () => { if (state.reachable === false) boot(); });
state.healthTimer = setInterval(refreshHealth, HEALTH_EVERY_MS);
boot();
