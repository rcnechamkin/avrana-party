// Party mode (AVR-20, AVR-127): what Party Home shows and does when Party Core answers.
// Pure: no DOM, no network, no storage. Decisions come only from the Party Core view
// (avrana/party/core.py PartyCore.view) and the catalog; never from the browser or the user agent.
//
// Party mode is progressive enhancement. With no Party Core (production before AVR-51, or any
// answer that is not a Party Core view) Party Home stays the catalog it has always been.
import { launchTarget } from './catalog-view.js';

const LIVE = ['launching', 'active', 'ending'];

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

/** The party's current game (starting, on or ending), or null in the lobby. */
export function liveSession(view) {
  return view && view.session && LIVE.includes(view.state) ? view.session : null;
}

/** How a catalog tile behaves in Party mode, or null when it is not a party game (then the tile
 * is exactly today's). Kinds: join (not a member yet), start (the host), wait (a member, not the
 * host), rejoin (this game is on), starting (it is starting or ending), busy (another party game
 * is on: nobody can start this one until it ends). */
export function tileMode(game, view, catalog = null) {
  const id = coreId(game, view);
  if (!id || !game.installed || !launchTarget(game)) return null;   // not here: today's tile says so
  if (!view.me) return { kind: 'join' };
  const s = liveSession(view);
  if (s && s.game !== id) {
    const on = catalog ? partyGame(catalog, s.game) : null;
    return { kind: 'busy', name: on ? on.name : s.game };
  }
  if (s) {
    return view.state === 'active' ? { kind: 'rejoin', href: launchTarget(game), session: s.id } : { kind: 'starting' };
  }
  return { kind: view.me.host ? 'start' : 'wait', game: id };
}

/** Should this page take the member into the party's game now?
 *   'enter'  the host's start was committed (the game is active) and this page has not taken
 *            this tab into it: go. A start watched live always enters; a page opened while a
 *            game is on (reconnect, reopen, a late phone) enters unless this tab already went
 *            in (it came back with Back to Party: then it only offers).
 *   'offer'  show Rejoin, do not move.
 *   null     nothing to do.
 * `entered` is the session id this tab last entered, null if none, undefined when the tab
 * cannot remember (storage blocked): then a reopened page only offers, so it can never trap. */
export function arrival(view, { previous = null, entered } = {}) {
  if (!view || !view.me || view.state !== 'active' || !view.session) return null;
  const sid = view.session.id;
  if (previous && previous.party === view.party) {
    const was = previous.state === 'active' && previous.session && previous.session.id === sid;
    return was ? null : 'enter';
  }
  if (entered === undefined) return 'offer';
  return entered === sid ? 'offer' : 'enter';
}
