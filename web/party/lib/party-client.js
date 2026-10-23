// Party Core client for Party Home (AVR-20, AVR-127). One long poll of /party/api/state
// (?since=V&wait=S, the service's existing sync; a member's poll is also their heartbeat) and the
// few actions the page offers: join, leave, and the host's start and end. The device cookie
// (Path=/party/, HttpOnly) is the only identity; this module never sees or sends a token.
//
// Views only move forward: a newer version, or a new party. An action's own answer always wins
// over a poll that was already on its way (that poll may predate the Join cookie).
//
// The poll is also how the page knows whether Party Core still answers: `onLink` hears every try
// that ends, { ok, answered } (answered: something answered, only not with a view).
import { readView } from './party-mode.js';

const WAIT_S = 20;              // long-poll wait; the service caps it at 25 s
const RETRY_MS = [1000, 2000, 5000];
// A page's FIRST contact, retried while nothing answered or the answer was a server error (a Wi-Fi
// blip, a Party Core restart): a game page that missed it would otherwise never follow the party,
// and Party Core ends a round whose every page went silent (AVR-475). About a minute in all.
export const FIRST_RETRY_MS = [1000, 2000, 5000, 10000, 20000, 30000];
export const transient = (res) => !res.ok && !res.signin && (res.status === 0 || res.status >= 500);
// Party Core never redirects an API request. A redirect means something in front of the Party asks the
// person to sign in again (a hosted site's access gateway whose session ran out); retrying cannot fix
// that, only a page load can. Asked with redirect: 'manual', a browser answers it as an opaque
// redirect instead of following it into a cross-origin page that would fail as "offline".
export const NO_FOLLOW = 'manual';
export const signinRedirect = (res) => Boolean(res) && (res.type === 'opaqueredirect' || (res.status >= 300 && res.status < 400));

export function createPartyClient({ fetch = globalThis.fetch.bind(globalThis), base = 'api/', onView, onLink = () => {},
  schedule = setTimeout, cancel = clearTimeout, departure = null } = {}) {
  const settle = (v) => (departure ? departure.apply(v) : v);   // left-by-choice (AVR-580) rides on every view
  let view = null, gen = 0, epoch = 0, poll = null, wake = null;

  async function request(path, body) {
    try {
      const res = await fetch(base + path, body === undefined ? { cache: 'no-store', credentials: 'same-origin', redirect: NO_FOLLOW } : {
        method: 'POST', cache: 'no-store', credentials: 'same-origin', redirect: NO_FOLLOW,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (signinRedirect(res)) {
        onLink({ ok: false, answered: true, signin: true });
        return { ok: false, status: res.status, body: null, signin: true, error: 'signin', message: '' };
      }
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
    settle(v);
    if (!force && view && v.party === view.party && v.version <= view.version) return false;
    const previous = view;
    view = v;
    onView(v, previous);
    return true;
  }

  /** The pause between two tries after one failed. poke() ends it early. */
  const sleep = (ms) => new Promise((resolve) => {
    const timer = schedule(() => { wake = null; resolve(); }, ms);
    wake = () => { cancel(timer); wake = null; resolve(); };
  });

  async function loop(g) {
    let failures = 0;
    while (g === gen) {
      const e = epoch;
      const ctl = typeof AbortController === 'function' ? new AbortController() : null;
      const current = { ctl, poked: false };
      poll = current;
      const timer = schedule(() => ctl && ctl.abort(), (WAIT_S + 10) * 1000);
      let v = null, answered = false, signin = false;
      try {
        // After a try that failed, the next one does not wait for a change: the first answer
        // is what says the box is back, and it must not sit on the box for WAIT_S to say so.
        const res = await fetch(`${base}state?since=${view ? view.version : 0}&wait=${failures ? 0 : WAIT_S}`,
          { cache: 'no-store', credentials: 'same-origin', redirect: NO_FOLLOW, signal: ctl ? ctl.signal : undefined });
        answered = true;
        signin = signinRedirect(res);
        v = res.ok ? settle(readView(await res.json().catch(() => null))) : null;
      } catch { /* aborted, offline, or the Pi is restarting */ }
      cancel(timer);
      if (g !== gen) return;
      if (v) {
        failures = 0;
        onLink({ ok: true, answered: true });
        if (e === epoch) accept(v);
      } else if (!current.poked) {
        onLink(signin ? { ok: false, answered, signin } : { ok: false, answered });
        await sleep(RETRY_MS[Math.min(failures++, RETRY_MS.length - 1)]);
      }
    }
  }

  /** Stop waiting on the current poll, or on the pause after a failed one, and ask again at once
   * (after an action, on wake, when the network returns, or "Try again"). */
  function poke() {
    const current = poll;
    if (current) { current.poked = true; if (current.ctl) current.ctl.abort(); }
    if (wake) wake();
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
      return res.ok ? settle(readView(res.body)) : null;
    },
    /** probe(), retried on a transient failure (FIRST_RETRY_MS); null once Party Core answers that
     * it is not here (a 4xx) or the retries are used up. */
    async probeRetrying(delays = FIRST_RETRY_MS) {
      for (let i = 0; ; i++) {
        const res = await request('state');
        if (res.ok) return settle(readView(res.body));
        if (!transient(res) || i >= delays.length) return null;
        await sleep(delays[i]);
      }
    },
    /** One look now, without the long poll's wait: an answer counts as a link answer (onLink) and its
     * view is accepted even when unchanged, so the page decides again from it. True when Party Core answered. */
    async refresh() {
      epoch++;
      const fresh = await request('state');
      epoch++;
      const v = fresh.ok ? readView(fresh.body) : null;
      if (!v) return false;
      onLink({ ok: true, answered: true });
      accept(v, true);
      return true;
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
    /** Presence (ADR 0011): a phone with a profile joins on its own; the same call is idempotent,
     * so reopening a page simply restores it. */
    join: (name, avatar) => act('join', { name, avatar }),
    rename: (name, avatar) => act('rename', { name, avatar }),
    /** Leave Party: the person's intentional departure (AVR-580). Only a 200 means Core removed
     * them; anything else is unconfirmed and the page must say so. */
    leave: () => act('leave', {}),
    /** The Host hands hosting to someone who is here (Party Core's transfer_host). */
    handHost: (to) => act('host', { to, if_version: view ? view.version : null }),
    /** A guest's exit request from a game page of another origin: it asks only; this device's pages
     * go to Party Home, where Leave is confirmed (AVR-580 guest exit). */
    requestExit: () => act('leave/request', {}),
    /** Stay in the Party: closes that request, and the pages follow the party again. */
    stay: () => act('leave/stay', {}),
    /** The person's own opt back in after Leave: the only way back (an automatic join is refused). */
    async reconnect(name, avatar) {
      const res = await act('reconnect', { name, avatar });
      if (res.ok && res.body && res.body.me && departure) departure.clear();
      return res;
    },
    /** The host, from a round's results: everyone back to Party Home. */
    goHome: () => act('home', { if_version: view ? view.version : null }),
    end: () => act('session/end', { if_version: view ? view.version : null }),
    /** The host, from anywhere (a setup, a round, its results): everyone back to Party Home. The
     * Party's own way out; it asks nothing of the game's page. */
    async lobby() {
      let res = await act('lobby', { if_version: view ? view.version : null });
      if (res.ok || res.error !== 'stale') return res;
      epoch++;
      const fresh = await request('state');
      epoch++;
      if (fresh.ok) accept(readView(fresh.body), true);
      const v = view;                           // still the host, and the party still not home
      if (!v || !v.me || !v.me.host || !v.location || v.location.at === 'home') return res;
      return act('lobby', { if_version: v.version });
    },
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
