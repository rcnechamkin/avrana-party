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
 * host), rejoin (this game is on), starting (it is starting or ending), switch (the host, while
 * another party game is on: ends it, then starts this one for everyone; AVR-128), busy (another
 * party game is on and this phone is not the host). */
export function tileMode(game, view, catalog = null) {
  const id = coreId(game, view);
  if (!id || !game.installed || !launchTarget(game)) return null;   // not here: today's tile says so
  if (!view.me) return { kind: 'join' };
  const s = liveSession(view);
  if (s && s.game !== id) {
    const on = catalog ? partyGame(catalog, s.game) : null;
    const name = on ? on.name : s.game;
    if (view.me.host && view.state === 'active' && !view.switching_to) return { kind: 'switch', game: id, name };
    return { kind: 'busy', name };
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

/** Where a page inside a game should go after a Party Core view (AVR-128). Party Core's `nav`
 * says where the party is; it moves only on committed transitions (a game became active, the
 * host ended it, a start failed). A page follows only a move it watched happen in this party
 * (R2, R5: keyed by party and seq), so opening or reloading a page never throws anyone out.
 *   {to: 'game', game}  the party went to another game (a switch, or a start while this page
 *                       showed something else): go there
 *   {to: 'home'}        the host ended the game this page is: back to Party Home
 *   null                stay. Also for a game that ended by its own rules (its end screen is the
 *                       intermission) and for anyone who is not a member (Leave is personal).
 * `here` is this page's Party Core game id, or null for a page that is not a party game (a
 * standalone title, the arcade): those follow a start, never an end. */
export function follow(view, previous, here = null) {
  if (!view || !view.me || !view.nav || !previous || !previous.nav || previous.party !== view.party) return null;
  const n = view.nav;
  if (n.seq <= previous.nav.seq) return null;
  if (n.to === 'game') return n.game && n.game !== here ? { to: 'game', game: n.game } : null;
  if (n.to === 'home') return here && n.from === here ? { to: 'home' } : null;
  return null;
}
