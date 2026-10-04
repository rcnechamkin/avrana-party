// The Party's side of the seam between a game page and the Party (ADR 0013, AVR-226).
//
// A game page lives on another origin (games.avrana.net). It holds no Party identity and cannot
// call the Party API: the browser would attach the device cookie to its requests, so Party Core
// refuses them by Origin and Sec-Fetch-Site and sends no CORS headers. What a game page may
// have, it gets from this module, which runs in an invisible frame on the Party origin
// (bridge.html) and talks to its parent only through postMessage.
//
// The protocol is `avrana.party-bridge/v1`; contracts/vectors/party-bridge.v1.json pins it for
// the shim that game pages load from their own origin (web/party/bridge/shim.js, vendored).
//
//   game -> bridge   hello {game}              once; binds this frame to that origin and game
//                    ticket {id}               a ticket for the bound game's running session
//                    end | home | playAgain {id}   the host's verbs; Party Core checks the host
//   bridge -> game   view {view}               pushed on every change; no ids of any kind
//                    navigate {to: "party"}    the party is elsewhere: go to Party Home
//                    ticket {id, ok, ...}      answer
//                    result {id, ok, error}    answer
//
// Rules this file enforces, each with a test:
//  * only window.parent is ever listened to or written to;
//  * the parent's origin must be registered at Party Core for the game it names
//    (GET /party/api/bridge); anyone else gets silence, not an error;
//  * the first valid hello binds the frame; a second hello for another game is ignored;
//  * replies are posted to the bound origin only, never "*";
//  * a message with an unknown type, an unknown field or a malformed value is ignored whole;
//  * `navigate` carries a word from a closed set, never a URL, and the game supplies no URL.
import { createPartyClient } from './party-client.js';
import { destination, locationOf } from './party-mode.js';
import { profileIdentity } from './party-follow.js';

export const PROTOCOL = 'avrana.party-bridge/v1';
export const REQUESTS = ['hello', 'ticket', 'end', 'home', 'playAgain'];
const GAME = /^[a-z][a-z0-9_-]{0,39}$/;
const ID = /^[A-Za-z0-9_-]{1,32}$/;

/** A request from a game page, checked: {type, id?, game?}, or null for anything else. */
export function parseRequest(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data) || data.avrana !== PROTOCOL) return null;
  if (!REQUESTS.includes(data.type)) return null;
  const keys = Object.keys(data).sort().join(',');
  if (data.type === 'hello') {
    if (keys !== 'avrana,game,type' || typeof data.game !== 'string' || !GAME.test(data.game)) return null;
    return { type: 'hello', game: data.game };
  }
  if (keys !== 'avrana,id,type' || typeof data.id !== 'string' || !ID.test(data.id)) return null;
  return { type: data.type, id: data.id };
}

/** May a page on `origin` speak for `game`? `origins` is Party Core's {origin: '*' | [ids]}. */
export function originAllows(origins, origin, game) {
  if (!origins || typeof origins !== 'object' || !Object.prototype.hasOwnProperty.call(origins, origin)) return false;
  const games = origins[origin];
  return games === '*' || (Array.isArray(games) && games.includes(game));
}

/** What a game page is shown of a Party Core view: enough to draw the host's controls and to
 * know where the party is. No member, device, party or session id; no other member's name but
 * the host's, which every phone at the party already sees. */
export function publicView(view) {
  if (!view) return { party: false, member: false, host: false, hostName: null, location: { at: 'home', game: null }, round: null };
  const me = view.me || null;
  const host = Array.isArray(view.members) ? view.members.find((m) => m && m.host) : null;
  const loc = locationOf(view);
  const s = view.session || null;
  return {
    party: true,
    member: Boolean(me),
    host: Boolean(me && me.host),
    hostName: host && typeof host.name === 'string' ? host.name : null,
    location: { at: loc.at, game: loc.game || null },
    round: s ? { game: s.game || null, state: s.state || null, outcome: s.outcome || null, myRole: s.my_role || null } : null,
  };
}

/** Start the bridge in `win` (the frame). Returns {stop, bound()} for tests. */
export function startBridge({ win = globalThis, fetch = globalThis.fetch.bind(globalThis),
  storage = globalThis.localStorage } = {}) {
  let origins = null, bound = null, client = null, lastNavigate = false;
  const loaded = (async () => {
    try {
      const res = await fetch('/party/api/bridge', { cache: 'no-store', credentials: 'same-origin' });
      const body = res.ok ? await res.json() : null;
      origins = body && body.schema === PROTOCOL && body.origins && typeof body.origins === 'object' ? body.origins : {};
    } catch { origins = {}; }
  })();

  const post = (msg) => win.parent.postMessage({ avrana: PROTOCOL, ...msg }, bound.origin);

  function onView(v) {
    if (!bound) return;
    post({ type: 'view', view: publicView(v) });
    // With no catalog the answer is only ever "stay" or Party Home: where a game opens is
    // Party Home's business, and a game page is never handed a URL.
    const elsewhere = Boolean(destination(v, bound.game, null));
    if (elsewhere && !lastNavigate) post({ type: 'navigate', to: 'party' });
    lastNavigate = elsewhere;
  }

  async function follow() {
    client = createPartyClient({ fetch, base: '/party/api/', onView });
    let first = await client.probe();
    if (first && !first.me) {                 // presence is automatic once there is a profile
      const who = profileIdentity(storage);
      if (who) {
        const res = await client.join(who.name, who.avatar);
        if (res.ok && res.body && res.body.me) first = res.body;
      }
    }
    if (!first) { post({ type: 'view', view: publicView(null) }); return; }
    client.start(first);
  }

  async function ticket(id) {
    let res, body = null;
    try {
      res = await fetch('/party/api/session/ticket', {
        method: 'POST', cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ game: bound.game, origin: bound.origin }) });
      try { body = await res.json(); } catch { /* not JSON */ }
    } catch { return post({ type: 'ticket', id, ok: false, error: 'offline' }); }
    if (!res.ok || !body || typeof body.ticket !== 'string') {
      return post({ type: 'ticket', id, ok: false, error: (body && body.error) || 'unavailable' });
    }
    return post({ type: 'ticket', id, ok: true, ticket: body.ticket, role: body.role, expiresIn: body.expires_in });
  }

  async function hostVerb(type, id) {
    let res = { ok: false, error: 'unavailable' };
    if (client) {
      if (type === 'end') res = await client.end();
      else if (type === 'home') res = await client.goHome();
      else if (locationOf(client.view()).game === bound.game) res = await client.launch(bound.game);
      else res = { ok: false, error: 'no_game' };
    }
    post({ type: 'result', id, ok: Boolean(res.ok), error: res.ok ? null : res.error || 'unavailable' });
  }

  async function onMessage(ev) {
    if (!ev || ev.source !== win.parent || ev.source === win) return;       // the parent, only
    const req = parseRequest(ev.data);
    if (!req) return;
    await loaded;
    if (req.type === 'hello') {
      if (bound || !originAllows(origins, ev.origin, req.game)) return;      // silence
      bound = { origin: ev.origin, game: req.game };
      await follow();
      return;
    }
    if (!bound || ev.origin !== bound.origin) return;
    if (req.type === 'ticket') await ticket(req.id);
    else await hostVerb(req.type, req.id);
  }

  win.addEventListener('message', onMessage);
  const wake = () => { if (client && win.document && win.document.visibilityState === 'visible') client.poke(); };
  if (win.document && win.document.addEventListener) win.document.addEventListener('visibilitychange', wake);
  return {
    bound: () => bound,
    ready: loaded,
    stop() { win.removeEventListener('message', onMessage); if (client) client.stop(); },
  };
}
