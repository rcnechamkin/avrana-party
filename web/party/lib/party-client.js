// Party Core client for Party Home (AVR-20, AVR-127). One long poll of /party/api/state
// (?since=V&wait=S, the service's existing sync; a member's poll is also their heartbeat) and the
// few actions the page offers: join, leave, and the host's start and end. The device cookie
// (Path=/party/, HttpOnly) is the only identity; this module never sees or sends a token.
//
// Views only move forward: a newer version, or a new party. An action's own answer always wins
// over a poll that was already on its way (that poll may predate the Join cookie).
import { readView } from './party-mode.js';

const WAIT_S = 20;              // long-poll wait; the service caps it at 25 s
const RETRY_MS = [1000, 2000, 5000];

export function createPartyClient({ fetch = globalThis.fetch.bind(globalThis), base = 'api/', onView,
  schedule = setTimeout, cancel = clearTimeout } = {}) {
  let view = null, gen = 0, epoch = 0, poll = null;

  async function request(path, body) {
    try {
      const res = await fetch(base + path, body === undefined ? { cache: 'no-store', credentials: 'same-origin' } : {
        method: 'POST', cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      let data = null;
      try { data = await res.json(); } catch { /* not JSON */ }
      return { ok: res.ok, status: res.status, body: data,
        error: res.ok ? null : (data && data.error) || 'unavailable', message: (data && data.message) || '' };
    } catch {
      return { ok: false, status: 0, body: null, error: 'offline', message: '' };
    }
  }

  function accept(v, force = false) {
    if (!v) return false;
    if (!force && view && v.party === view.party && v.version <= view.version) return false;
    const previous = view;
    view = v;
    onView(v, previous);
    return true;
  }

  const sleep = (ms) => new Promise((resolve) => schedule(resolve, ms));

  async function loop(g) {
    let failures = 0;
    while (g === gen) {
      const e = epoch;
      const ctl = typeof AbortController === 'function' ? new AbortController() : null;
      const current = { ctl, poked: false };
      poll = current;
      const timer = schedule(() => ctl && ctl.abort(), (WAIT_S + 10) * 1000);
      let v = null;
      try {
        const res = await fetch(`${base}state?since=${view ? view.version : 0}&wait=${WAIT_S}`,
          { cache: 'no-store', credentials: 'same-origin', signal: ctl ? ctl.signal : undefined });
        v = res.ok ? readView(await res.json().catch(() => null)) : null;
      } catch { /* aborted, offline, or the Pi is restarting */ }
      cancel(timer);
      if (g !== gen) return;
      if (v) {
        failures = 0;
        if (e === epoch) accept(v);
      } else if (!current.poked) {
        await sleep(RETRY_MS[Math.min(failures++, RETRY_MS.length - 1)]);
      }
    }
  }

  /** Stop waiting on the current poll and ask again at once (after an action, or on wake). */
  function poke() {
    const current = poll;
    if (current) { current.poked = true; if (current.ctl) current.ctl.abort(); }
  }

  async function act(path, body = {}) {
    epoch++;
    try {
      const res = await request(path, body);
      if (res.ok) accept(readView(res.body), true);
      return res;
    } finally {
      epoch++;
      poke();
    }
  }

  /** A host move. A refusal only because the party moved on ("stale": someone joined, a phone
   * woke) is re-checked against a fresh view and tried once more, if this phone is still the
   * host and the party is still where the move expects it. Every other refusal stands. */
  async function hostMove(path, game, from) {
    let res = await act(path, { game, if_version: view ? view.version : null });
    if (res.ok || res.error !== 'stale') return res;
    epoch++;
    const fresh = await request('state');
    epoch++;
    if (fresh.ok) accept(readView(fresh.body), true);
    const v = view;
    if (!v || !v.me || !v.me.host || v.state !== from || !v.games.includes(game)) return res;
    res = await act(path, { game, if_version: v.version });
    return res;
  }

  return {
    view: () => view,
    /** The first look: a Party Core view, or null (no Party here: catalog mode). Observes only. */
    async probe() {
      const res = await request('state');
      return res.ok ? readView(res.body) : null;
    },
    start(first) {
      gen++;
      view = null;
      accept(first, true);
      loop(gen);
    },
    stop() { gen++; poke(); },
    poke,
    act,
    join: (name) => act('join', { name }),
    leave: () => act('leave', {}),
    end: () => act('session/end', { if_version: view ? view.version : null }),
    /** The host starts a party game for everyone (from the lobby). */
    launch: (game) => hostMove('session/launch', game, 'lobby'),
    /** The host moves everyone from the game that is on to another one (AVR-128): Party Core
     * ends the old game first, then starts this one. */
    switchTo: (game) => hostMove('session/switch', game, view && view.state === 'setup' ? 'setup' : 'active'),
    /** This member's own choice for the round being set up: 'player' or 'spectator' (AVR-129). */
    choose: (choice) => act('session/choice', { choice }),
    /** The host starts the round set up. Choices move the version often, so a refusal only for
     * "stale" is re-checked against a fresh view and tried once more while this phone is still
     * the host of a round in setup. Every other refusal (someone has not chosen, too few) stands. */
    async startRound() {
      let res = await act('session/start', { if_version: view ? view.version : null });
      if (res.ok || res.error !== 'stale') return res;
      epoch++;
      const fresh = await request('state');
      epoch++;
      if (fresh.ok) accept(readView(fresh.body), true);
      const v = view;
      if (!v || !v.me || !v.me.host || v.state !== 'setup') return res;
      return act('session/start', { if_version: v.version });
    },
  };
}
