// Where a game opens when Party Core registers it to a game origin (ADR 0013, AVR-303).
//
// The Party shell learns which origin serves a game from exactly one place: Party Core's own
// answer at GET /party/api/bridge ({schema, origins: {origin: '*' | [game ids]}}), the same
// answer the bridge frame checks a game page against. Nothing is taken from the address bar, a
// message, storage or the catalog, and no title is named here: a game is whatever id Party Core
// says it is. This file is the "origin is the trust tier" half only: it does not make a game
// page the top-level document a contract; it only says where a member's page is taken.
export const BRIDGE_SCHEMA = 'avrana.party-bridge/v1';
export const BRIDGE_URL = '/party/api/bridge';
const RETRY_MS = 3000;

/** A game origin as Party Core may register it: `http(s)://host[:port]` and nothing else (one
 * trailing slash is tolerated). Returns the canonical origin, or null. Strict on purpose: the
 * canonical form must equal what was written, so userinfo, a path, a query, a fragment, an
 * explicit default port, upper case or a backslash all fail. */
export function cleanOrigin(value) {
  if (typeof value !== 'string' || value.length > 255) return null;
  const text = value.endsWith('/') ? value.slice(0, -1) : value;
  if (!/^https?:\/\/[A-Za-z0-9.-]+(:[0-9]{1,5})?$/.test(text)) return null;
  let url;
  try { url = new URL(text); } catch { return null; }
  return url.origin === text ? text : null;
}

/** The same-origin entry path of a game: `/...` that is not protocol-relative and has no
 * backslash, control character or space. */
function plainPath(entry) {
  return typeof entry === 'string' && entry.startsWith('/') && !entry.startsWith('//')
    && !/[\\\u0000- \u007f]/.test(entry);
}

/** Where a member's page goes for `game`, from Party Core's registrations.
 *   game         the Party Core game id
 *   entry        the catalog's same-origin launch path for it
 *   origins      the bridge answer's `origins` ({origin: '*' | [ids]}), or null/{} when unknown
 *   partyOrigin  this page's own origin (location.origin)
 *   limited      Limited Mode: games stay same-origin, whatever is registered
 * Returns an absolute URL on the registered game origin; `entry` itself when the game is not
 * registered to an origin (today's behavior); or null: Party Core registered something this
 * shell will not navigate to (malformed, equal to the Party origin, two origins for one game,
 * an entry that is not a plain same-origin path). null means stay on Party Home. */
export function gameAddress({ game, entry, origins, partyOrigin, limited = false }) {
  if (limited || !origins || typeof origins !== 'object' || Array.isArray(origins)) return entry;
  const registered = Object.keys(origins).filter((o) => {
    const games = origins[o];
    return games === '*' || (Array.isArray(games) && games.includes(game));
  });
  if (!registered.length) return entry;
  const clean = registered.map(cleanOrigin);
  if (clean.some((o) => o === null)) return null;
  if (new Set(clean).size !== 1) return null;                   // ambiguous
  const origin = clean[0];
  const own = cleanOrigin(partyOrigin);
  if (!own || own === origin) return null;                      // a game origin is never a Party origin
  if (!plainPath(entry)) return null;
  let url;
  try { url = new URL(entry, origin); } catch { return null; }
  return url.origin === origin ? url.href : null;
}

/** Party Core's registrations, fetched once per page load and again when asked. A failed fetch
 * is "no game origins" for now (same-origin paths, today's behavior) and is tried again, never
 * kept as the answer. `settled()` resolves once the first attempt has finished either way, so a
 * page never navigates on a guess while that answer is still on its way. */
export function createGameOrigins({ fetch = globalThis.fetch.bind(globalThis), now = () => Date.now() } = {}) {
  let origins = null, ok = false, inflight = null, last = -Infinity, done = false;
  let release;
  const first = new Promise((resolve) => { release = resolve; });

  async function attempt() {
    last = now();
    try {
      const res = await fetch(BRIDGE_URL, { cache: 'no-store', credentials: 'same-origin' });
      const body = res.ok ? await res.json() : null;
      if (body && body.schema === BRIDGE_SCHEMA && body.origins && typeof body.origins === 'object'
          && !Array.isArray(body.origins)) { origins = body.origins; ok = true; } else { origins = null; ok = false; }
    } catch { origins = null; ok = false; }
    done = true;
    release();
  }

  function refresh() {
    if (!inflight) inflight = attempt().finally(() => { inflight = null; });
    return inflight;
  }
  return {
    refresh,
    /** Ask again only when the last answer failed (and not in the last few seconds). */
    retry() { if (!ok && !inflight && now() - last >= RETRY_MS) refresh(); },
    settled: () => (done ? Promise.resolve() : (refresh(), first)),
    isSettled: () => done,
    get: () => origins,
    ok: () => ok,
  };
}
