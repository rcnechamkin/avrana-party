// Party mode: what a page shows and where it must be, from Party Core's view (ADR 0011, the
// console model). Pure: no DOM, no network, no storage. Decisions come only from the Party Core
// view (avrana/party/core.py PartyCore.view) and the catalog; never from the browser or the user
// agent.
//
// There is one party and it is in one place (view.location): home, setup, game or results. Every
// member's phone is a viewport onto that place; only the Party Host moves it. So a member's page
// never wanders: destination() says where it must be, and the page goes there at once, on load,
// on reconnect and on every move. Party mode is progressive enhancement: with no Party Core, or
// for someone who has no profile yet, pages stay what they always were.
import { launchTarget } from './catalog-view.js';

const LIVE = ['setup', 'launching', 'active', 'ending'];
export const HOME = 'home';            // `here` for Party Home itself

/** A Party Core view, or null for anything else (a 404 page, another service's JSON). */
export function readView(body) {
  if (!body || typeof body !== 'object' || typeof body.party !== 'string' || !Number.isInteger(body.version)
      || !Array.isArray(body.members) || !Array.isArray(body.games)) return null;
  return body;
}

/** The installed, launchable catalog title for a Party Core game id (the catalog id, or the
 * provider's slug for LAN titles). Party Core decides which games are party games; the catalog
 * decides where each one opens. */
export function partyGame(catalog, id) {
  if (!catalog || typeof id !== 'string') return null;
  const game = catalog.games.find((g) => g.id === id) || catalog.games.find((g) => g.legacySlug === id);
  return game && game.installed && launchTarget(game) ? game : null;
}

/** The Party Core game id of a catalog title, or null when it is not a party game here. */
export function coreId(game, view) {
  if (!view) return null;
  return view.games.find((id) => id === game.id) || view.games.find((id) => id === game.legacySlug) || null;
}

/** The party's current game (being set up, starting, on or ending), or null. */
export function liveSession(view) {
  return view && view.session && LIVE.includes(view.state) ? view.session : null;
}

/** Where the whole party is: {at: 'home'|'setup'|'game'|'results', game, session}. */
export function locationOf(view) {
  const loc = view && view.location;
  return loc && typeof loc.at === 'string' ? loc : { at: HOME, game: null, session: null };
}

/** The round this phone remembers having played ({ game, session }), or null. Only a member who
 * plays it (Party Core's own role for this member: `session.my_role`; the owner, 2026-10-06: a
 * round someone only watched is not in their "recently played"), and only while the round is on:
 * not its setup, and not its held results, which a phone can arrive at without having been in
 * the round. */
export function roundToRemember(view) {
  const loc = locationOf(view);
  if (!view || !view.me || loc.at !== 'game' || !loc.game) return null;
  if (!view.session || view.session.my_role !== 'player') return null;
  return { game: loc.game, session: loc.session || null };
}

/** Where this member's page must be, or null when it is already there.
 *   here: HOME on Party Home; the page's Party Core game id on a game page; for a page that is
 *         not a party game (a standalone title) its own slug, which is never a party game.
 * Home and setup are Party Home's (the setup scene is the Party's). A round, and its results, are
 * the game's page. A standalone title may stay open while the party is home (a personal game),
 * never once the host takes the party somewhere. Nobody without a profile is moved. */
export function destination(view, here, catalog) {
  if (!view || !view.me || !view.location) return null;
  const loc = locationOf(view);
  if (loc.at === HOME || loc.at === 'setup') {
    if (here === HOME) return null;
    if (loc.at === HOME && !view.games.includes(here)) return null;     // a personal standalone game
    return '/party/';
  }
  if (here === loc.game) return null;
  const game = partyGame(catalog, loc.game);
  return game ? launchTarget(game) : here === HOME ? null : '/party/';
}

/** How a catalog tile behaves while the party is home, or null when it is not a party game (then
 * the tile is exactly today's). Kinds: profile (no profile yet: choose a name first), start (the
 * host), wait (a member, not the host), starting (the host's direct start is on its way). */
export function tileMode(game, view) {
  const id = coreId(game, view);
  if (!id || !game.installed || !launchTarget(game)) return null;   // not here: today's tile says so
  if (!view.me) return { kind: 'profile' };
  if (liveSession(view)) return { kind: 'starting' };
  return { kind: view.me.host ? 'start' : 'wait', game: id };
}

/** The roster as the setup scene shows it: every member, with their round choice. */
export function roster(view) {
  const choices = (view.session && view.session.setup && view.session.setup.choices) || {};
  return view.members.map((m) => ({
    id: m.id, name: m.name, avatar: m.avatar || null, host: Boolean(m.host),
    me: Boolean(view.me && view.me.id === m.id), away: m.presence === 'away',
    choice: choices[m.id] || null,
  }));
}

/** The setup scene's decision and host area (AVR-129), or null when the party is not setting up
 * a round. Party Core decides; this only shapes its answer for the scene.
 *   game         the Party Core game id being set up
 *   mine         'player' | 'spectator' | null (not chosen yet)
 *   players, spectators, min, max   counts and the game's limits
 *   waiting      names of members who are here and have not chosen
 *   host         this phone is the Party Host; hostName: who is
 *   canStart     the host may start now; starting: the host's start is on its way
 *   blocker      why the round cannot start yet, in words, or null */
export function setupPanel(view) {
  const s = view && view.session;
  if (!view || !view.me || !s || !['setup', 'launching'].includes(view.state)) return null;
  const st = s.setup || {};
  const byId = new Map(view.members.map((m) => [m.id, m.name]));
  const host = view.members.find((m) => m.host);
  const starting = view.state === 'launching';
  return {
    game: s.game,
    mine: starting ? s.my_role : st.mine || null,
    players: st.players ?? s.players, spectators: st.spectators ?? 0, min: st.min, max: st.max,
    waiting: (st.waiting || []).map((id) => byId.get(id) || '?'),
    host: Boolean(view.me.host), hostName: host ? host.name : null,
    canStart: Boolean(view.me.host) && !starting && !st.blocker,
    starting,
    blocker: starting ? null : st.blocker || null,
  };
}
