// The Party underneath a game page (ADR 0011, the console model). Every page that runs a game
// for the party (a LAN game at /games/<slug>/?avrana=1, the arcade) loads this module. It does
// three things and draws almost nothing:
//
//  1. Keeps this page where the party is. Party Core has one location (home, setup, game,
//     results) and only the Party Host moves it. On load, on reconnect and on every move, a
//     member's page that is in the wrong place goes to the right one at once (location.replace):
//     no offers, no banners. Home and a round's setup are Party Home; a round and its results
//     are the game's page.
//  2. Keeps this phone present. A phone with an Avrana profile joins on its own (the same call
//     Party Home makes); there is no Join ceremony.
//  3. Lends the game shell the Party's controls, without Party chrome on top of the game:
//        window.AvranaParty = { active, view(), isHost(), hostName(), location(),
//                               end(), goHome(), playAgain(), onChange(fn) }
//     and a document 'avrana-party' event on every change. A game that draws the host's
//     controls itself (End, Play again, Party Home) marks an element [data-avrana-party-shell];
//     otherwise the host gets one End control in the page's own navigation (`container`).
//
// Progressive enhancement: with no Party Core (a 404), or on a phone with no profile, this module
// returns null and the page stays what it always was (a standalone game with Back to Party).
// The device cookie (Path=/party/, HttpOnly) is the only identity; this module never sees or
// sends a token.
import { createPartyClient } from './party-client.js';
import { createProfile } from './profile.js';
import { destination, locationOf, partyGame } from './party-mode.js';

const CONFIRM_MS = 4000;                      // a second tap within this ends the game

/** The page's Party Core game id from its path: /games/<slug>/ -> slug, else null. */
export function gameOfPath(pathname) {
  const m = /^\/games\/([a-z][a-z0-9_-]*)\//.exec(pathname || '');
  return m ? m[1] : null;
}

/** The profile's Party name (Party Core allows 16 characters) and avatar, or null. */
export function profileIdentity(storage) {
  let snap;
  try { snap = createProfile(storage).snapshot(); } catch { return null; }
  const name = (snap.name || '').trim().slice(0, 16).trim();
  return name ? { name, avatar: snap.avatar } : null;
}

/** Start. `here`: this page's Party Core game id (a standalone title passes its slug).
 * `container`: the page's own navigation, for the fallback host control. Returns the Party API,
 * or null when there is no Party here for this phone. */
export async function startPartyFollow({ here = null, container = null, fetch = globalThis.fetch.bind(globalThis),
  go = (url) => location.replace(url), storage = globalThis.localStorage, root = globalThis.document } = {}) {
  const listeners = new Set();
  let ready = false, moving = false, endBtn = null, armed = null;
  const client = createPartyClient({ fetch, base: '/party/api/', onView });
  let first = await client.probe();
  if (!first) return null;                    // no Party Core here: the page stays as it is
  if (!first.me) {                            // presence is automatic once there is a profile
    const who = profileIdentity(storage);
    if (!who) return null;
    const res = await client.join(who.name, who.avatar);
    if (!res.ok || !res.body || !res.body.me) return null;
    first = res.body;
  }
  let catalog = null;
  try {
    const res = await fetch('/party/catalog.json', { credentials: 'same-origin' });
    catalog = res.ok ? await res.json() : null;
  } catch { /* then a move goes to Party Home, which knows where games open */ }

  const view = () => client.view();
  const api = {
    active: true,
    view,
    isHost: () => Boolean(view() && view().me && view().me.host),
    hostName: () => { const h = view() && view().members.find((m) => m.host); return h ? h.name : null; },
    location: () => locationOf(view()),
    /** The host: end the round for everyone (everyone goes back to Party Home). */
    end: () => client.end(),
    /** The host, from the results: everyone back to Party Home. */
    goHome: () => client.goHome(),
    /** The host, from the results: a new round of this game (its setup first, if it has one). */
    playAgain: () => client.launch(locationOf(view()).game),
    onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    gameName: () => { const g = partyGame(catalog, locationOf(view()).game); return g ? g.name : null; },
  };

  const doc = root || null;
  if (doc && doc.documentElement) doc.documentElement.dataset.avranaParty = 'on';   // chrome off
  globalThis.AvranaParty = api;

  function fallbackControls(v) {
    // Games that draw the host's controls themselves say so; the rest get one quiet End.
    if (!container || !doc || doc.querySelector('[data-avrana-party-shell]')) return;
    const loc = locationOf(v);
    const show = Boolean(v.me && v.me.host && loc.at === 'game' && loc.game === here);
    if (!endBtn && show) {
      endBtn = doc.createElement('button');
      endBtn.type = 'button';
      endBtn.id = 'avrana-party-end';
      endBtn.textContent = 'End game for everyone';
      endBtn.addEventListener('click', onEnd);
      container.append(endBtn);
    }
    if (endBtn) endBtn.hidden = !show;
    container.toggleAttribute('data-avrana-host', show);
  }

  async function onEnd() {
    if (!api.isHost()) return;
    if (!armed) {
      endBtn.textContent = 'Tap again to end it';
      armed = setTimeout(() => { armed = null; endBtn.textContent = 'End game for everyone'; }, CONFIRM_MS);
      return;
    }
    clearTimeout(armed);
    armed = null;
    endBtn.disabled = true;
    await client.end();
    endBtn.disabled = false;
    endBtn.textContent = 'End game for everyone';
  }

  function onView(v) {
    if (!ready || moving) return;           // the first join answers before the page is wired
    if (!v.me) {                              // no longer a member (a new party after a restart)
      const who = profileIdentity(storage);
      if (who) client.join(who.name, who.avatar);
      return;
    }
    const url = destination(v, here, catalog);
    if (url) {
      moving = true;
      // A move that arrives while this phone is offline (a Wi-Fi drop, a wake-up) waits for the
      // network, so the page never lands on the browser's own error screen.
      const nav = globalThis.navigator;
      if (nav && nav.onLine === false && typeof globalThis.addEventListener === 'function') {
        globalThis.addEventListener('online', () => go(url), { once: true });
      } else {
        go(url);
      }
      return;
    }
    fallbackControls(v);
    for (const fn of listeners) { try { fn(v); } catch { /* a listener's own problem */ } }
    if (doc && typeof CustomEvent === 'function') {
      doc.dispatchEvent(new CustomEvent('avrana-party', { detail: { location: locationOf(v), host: api.isHost() } }));
    }
  }

  ready = true;
  client.start(first);
  const wake = () => { if (doc && doc.visibilityState === 'visible') client.poke(); };
  if (doc) doc.addEventListener('visibilitychange', wake);
  api.stop = () => { client.stop(); if (doc) doc.removeEventListener('visibilitychange', wake); };
  return api;
}
