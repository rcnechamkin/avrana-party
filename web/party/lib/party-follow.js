// Party navigation inside a game (AVR-128). Any page that runs a game for the party (a LAN game
// at /games/<slug>/?avrana=1, the arcade) loads this module and gets the same rule Party Home
// already follows: Party Core decides where the party is, and a phone moves only on a committed
// transition it watched (party-mode.js follow()). Game-agnostic: a page says only which Party
// Core game it is, if any.
//
// Progressive enhancement, like Party Home: with no Party Core (a 404), or for someone who has not
// joined, this module shows nothing and never moves anyone. The device cookie (Path=/party/,
// HttpOnly) is the only identity; this module never sees or sends a token.
import { createPartyClient } from './party-client.js';
import { follow, liveSession, partyGame } from './party-mode.js';
import { launchTarget } from './catalog-view.js';

const ENTERED_KEY = 'avrana-party-entered';   // Party Home's reconnect memory (ADR 0007 §6)
const MOVE_DELAY_MS = 900;                    // time to hear the announcement before moving
const CONFIRM_MS = 4000;                      // a second tap within this ends the game

/** The page's Party Core game id from its path: /games/<slug>/ -> slug, else null. */
export function gameOfPath(pathname) {
  const m = /^\/games\/([a-z][a-z0-9_-]*)\//.exec(pathname || '');
  return m ? m[1] : null;
}

/** Start following. `here`: this page's Party Core game id (null for a page that is not a party
 * game). `container`: where the status line and the host's button go (the page's own
 * navigation). Returns {stop} or null when there is no Party here. */
export async function startPartyFollow({ here = null, container, fetch = globalThis.fetch.bind(globalThis),
  go = (url) => location.assign(url), storage = globalThis.sessionStorage, schedule = setTimeout } = {}) {
  const client = createPartyClient({ fetch, base: '/party/api/', onView });
  const first = await client.probe();
  if (!first) return null;                    // no Party Core here: the page stays as it is
  let catalog = null;
  try {
    const res = await fetch('/party/catalog.json', { credentials: 'same-origin' });
    catalog = res.ok ? await res.json() : null;
  } catch { /* then a move goes to Party Home, which knows where games open */ }

  const doc = container ? container.ownerDocument : null;
  const line = doc ? doc.createElement('span') : null;
  const endBtn = doc ? doc.createElement('button') : null;
  if (line) {
    line.id = 'avrana-party-follow';
    line.setAttribute('role', 'status');
    line.setAttribute('aria-live', 'polite');
    endBtn.type = 'button';
    endBtn.hidden = true;
    endBtn.id = 'avrana-party-end';
    endBtn.addEventListener('click', onEnd);
    container.append(line, endBtn);
  }
  let moving = false, armed = null;
  const isHost = (view) => Boolean(view.me && view.me.host);

  function say(text, link = null) {
    if (!line) return;
    line.replaceChildren(text);
    if (link) {
      const a = doc.createElement('a');
      a.href = link.href;
      a.textContent = link.text;
      line.append(' ', a);
    }
  }
  function nameOf(id) {
    const g = catalog ? partyGame(catalog, id) : null;
    return g ? g.name : id;
  }
  function remember(sid) {
    try { storage.setItem(ENTERED_KEY, sid); } catch { /* Party Home then only offers */ }
  }

  function render(view) {
    const s = liveSession(view);
    const me = view.me;
    const mine = Boolean(me && s && here && s.game === here);
    if (endBtn) endBtn.hidden = !(mine && me.host && view.state === 'active');
    if (moving) return;
    if (!me || !s) return say('');
    if (view.switching_to) return say(`Switching to ${nameOf(view.switching_to)}…`);
    if (mine) return say(me.host ? 'You’re the host.' : '');
    const g = catalog ? partyGame(catalog, s.game) : null;
    if (view.state === 'active' && g) {
      say(`Your party is playing ${g.name}.`, { href: launchTarget(g), text: 'Join them' });
    } else {
      say(`Your party is playing ${nameOf(s.game)}.`);
    }
  }

  function onView(view, previous) {
    render(view);
    const move = follow(view, previous, here);
    if (!move || moving) return;
    let url = '/party/';
    if (move.to === 'game') {
      const g = catalog ? partyGame(catalog, move.game) : null;
      if (g) url = launchTarget(g);
      remember(view.nav.session);
      say(`${isHost(view) ? 'You moved' : 'The host moved'} the party to ${nameOf(move.game)}. Joining…`);
    } else {
      say('The host ended the game. Back to Party…');
    }
    moving = true;
    schedule(() => {
      const now = client.view();
      if (now && now.party === view.party && now.nav.seq === view.nav.seq) go(url);
      else { moving = false; render(now || view); }   // the party moved again meanwhile
    }, MOVE_DELAY_MS);
  }

  async function onEnd() {
    const view = client.view();
    if (!view || !isHost(view)) return;
    if (!armed) {
      endBtn.textContent = 'Tap again to end it for everyone';
      armed = schedule(() => { armed = null; endBtn.textContent = 'End for everyone'; }, CONFIRM_MS);
      return;
    }
    armed = null;
    endBtn.disabled = true;
    const res = await client.end();
    endBtn.disabled = false;
    endBtn.textContent = 'End for everyone';
    if (!res.ok) say(res.message || 'Please try again.');
  }
  if (endBtn) endBtn.textContent = 'End for everyone';

  client.start(first);
  const wake = () => { if (doc && doc.visibilityState === 'visible') client.poke(); };
  if (doc) doc.addEventListener('visibilitychange', wake);
  return {
    stop() {
      client.stop();
      if (doc) doc.removeEventListener('visibilitychange', wake);
    },
  };
}
