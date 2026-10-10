// The Party bridge (ADR 0013, AVR-226): web/party/lib/bridge.js in a frame on the Party origin,
// web/party/bridge/shim.js in a game page on another origin, and the postMessage contract
// between them (contracts/vectors/party-bridge.v1.json). Two fake windows wired the way a
// browser wires a page and its frame: each sees the other's origin and window on every message.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PROTOCOL, parseRequest, publicView, originAllows, startBridge } from '../../web/party/lib/bridge.js';
import { PROTOCOL as SHIM_PROTOCOL, parsePush, connectParty } from '../../web/party/bridge/shim.js';

const vectors = JSON.parse(readFileSync(new URL('../../contracts/vectors/party-bridge.v1.json', import.meta.url)));
const PARTY = 'https://party.avrana.net', GAMES = 'https://games.avrana.net', EVIL = 'https://evil.example';
const ORIGINS = { [GAMES]: '*', 'https://arcade-only.avrana.net': ['arcade-gauntlet2'] };
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0)); };

const ana = { id: 'member-a', name: 'Ana', host: true }, ben = { id: 'member-b', name: 'Ben', host: false };
function coreView({ version = 7, me = ben, at = 'game', game = 'bluff' } = {}) {
  const location = { at, game: at === 'home' ? null : game, session: at === 'home' ? null : 'session-0123' };
  return { party: 'party-0123', version, state: at === 'game' ? 'active' : 'lobby', host: 'member-a',
    members: [{ ...ana, presence: 'here' }, { ...ben, presence: 'here' }], me,
    session: at === 'home' ? null : { id: 'session-0123', game, state: at === 'game' ? 'active' : 'ended', outcome: null, my_role: 'player' },
    games: ['bluff', 'arcade-gauntlet2'], nav: { seq: 1, to: at === 'home' ? 'home' : 'game', game, session: 'session-0123' }, location };
}

/** A window: listeners, and a postMessage that delivers to it with the sender's origin. */
function fakeWindow(origin) {
  const listeners = new Set();
  const win = {
    origin, received: [],
    addEventListener: (type, fn) => { if (type === 'message') listeners.add(fn); },
    removeEventListener: (type, fn) => listeners.delete(fn),
    setTimeout: (fn, ms) => setTimeout(fn, ms), clearTimeout: (t) => clearTimeout(t),
    deliver(data, from, targetOrigin) {
      if (targetOrigin !== '*' && targetOrigin !== origin) return;       // the browser drops it
      win.received.push({ data, origin: from.origin });
      for (const fn of [...listeners]) fn({ data, origin: from.origin, source: from.handle });
    },
  };
  win.handle = { postMessage: (data, targetOrigin) => win.deliver(data, win.sender, targetOrigin) };
  return win;
}

/** The Party API as the bridge sees it. */
function partyApi({ first = coreView(), polls = [], origins = ORIGINS, ticket = [200, { ticket: 'aps0.e30.AAAA', role: 'player', expires_in: 120, session: 'session-0123', game: 'bluff' }], answer = () => [200, first] } = {}) {
  const queue = [...polls], posts = [];
  const fetch = (url, init = {}) => {
    const reply = (status, body) => Promise.resolve({ ok: status < 300, status, json: async () => body });
    if (url === '/party/api/bridge') return reply(200, { schema: PROTOCOL, origins });
    if (init.method === 'POST') {
      posts.push([url, JSON.parse(init.body)]);
      return url === '/party/api/session/ticket' ? reply(...ticket) : reply(...answer(url));
    }
    if (url === '/party/api/state') return first ? reply(200, first) : reply(404, {});
    if (url.startsWith('/party/api/state?') && queue.length) return reply(200, queue.shift());
    return new Promise((_, reject) => init.signal?.addEventListener('abort', () => reject(new Error('aborted'))));
  };
  return { fetch, posts };
}

/** A game page on `pageOrigin` with the bridge frame inside it. */
function world({ pageOrigin = GAMES, api = partyApi(), storage = { getItem: () => null, setItem() {} } } = {}) {
  const page = fakeWindow(pageOrigin), frame = fakeWindow(PARTY);
  frame.parent = { postMessage: (data, target) => page.deliver(data, { origin: PARTY, handle: frameHandle }, target) };
  const frameHandle = { postMessage: (data, target) => frame.deliver(data, { origin: pageOrigin, handle: frame.parent }, target) };
  const bridge = startBridge({ win: frame, fetch: api.fetch, storage });
  const say = (data, { from = frame.parent, origin = pageOrigin } = {}) => frame.deliver(data, { origin, handle: from }, PARTY);
  return { page, frame, bridge, api, say, frameHandle, stop: () => bridge.stop() };
}
const msg = (type, more = {}) => ({ avrana: PROTOCOL, type, ...more });
const pushed = (w, type) => w.page.received.map((m) => m.data).filter((d) => d.type === type);

// ---- the contract -------------------------------------------------------------------------------

test('both sides name the same protocol as the vectors', () => {
  assert.equal(PROTOCOL, vectors.protocol);
  assert.equal(SHIM_PROTOCOL, vectors.protocol);
});

test('the bridge accepts exactly the requests the vectors say', () => {
  for (const v of vectors.requests) assert.deepEqual(parseRequest(v.message), v.accept, v.name);
});

test('the shim accepts exactly the pushes the vectors say', () => {
  for (const v of vectors.pushes) assert.equal(parsePush(v.message) !== null, v.accept, v.name);
});

test('a game page is shown a view with no id of any kind', () => {
  for (const v of vectors.views) {
    const out = publicView(v.core);
    assert.deepEqual(out, v.public, v.name);
    assert.notEqual(parsePush(msg('view', { view: out })), null, v.name);       // and the shim takes it
    const text = JSON.stringify(out);
    for (const bad of vectors.forbidden_in_a_view) assert.ok(!text.includes(bad), `${v.name}: ${bad}`);
  }
});

test('an origin speaks only for the games registered to it', () => {
  assert.ok(originAllows(ORIGINS, GAMES, 'bluff'));
  assert.ok(originAllows(ORIGINS, 'https://arcade-only.avrana.net', 'arcade-gauntlet2'));
  assert.ok(!originAllows(ORIGINS, 'https://arcade-only.avrana.net', 'bluff'));
  assert.ok(!originAllows(ORIGINS, EVIL, 'bluff'));
  assert.ok(!originAllows(ORIGINS, 'constructor', 'bluff'));
  assert.ok(!originAllows(null, GAMES, 'bluff'));
  assert.ok(!originAllows({}, GAMES, 'bluff'));
});

test('Party member result summaries never cross the game bridge', () => {
  const view = coreView({ at: 'results' });
  const before = publicView(view);
  view.session.result_summary = { game: 'bluff', mode: 'competitive',
    players: [{ name: 'Private result name', standing: 'won', rank: 1 }] };
  assert.deepEqual(publicView(view), before);
  assert.ok(!JSON.stringify(publicView(view)).includes('Private result name'));
});

// ---- the bridge frame ---------------------------------------------------------------------------

test('a registered game page says hello and is pushed the view, to its origin only', async () => {
  const w = world();
  w.say(msg('hello', { game: 'bluff' }));
  await settle();
  assert.deepEqual(w.bridge.bound(), { origin: GAMES, game: 'bluff' });
  const views = pushed(w, 'view');
  assert.equal(views.length, 1);
  assert.deepEqual(views[0].view, publicView(coreView()));
  assert.ok(w.page.received.every((m) => m.origin === PARTY));
  assert.equal(pushed(w, 'navigate').length, 0);                    // the party is here
  w.stop();
});

test('an unregistered parent gets silence, whatever it says', async () => {
  const w = world({ pageOrigin: EVIL });
  w.say(msg('hello', { game: 'bluff' }));
  w.say(msg('ticket', { id: 'r1' }));
  w.say(msg('end', { id: 'r2' }));
  await settle();
  assert.equal(w.bridge.bound(), null);
  assert.deepEqual(w.page.received, []);
  assert.deepEqual(w.api.posts, []);
  w.stop();
});

test('an origin registered for one game cannot speak for another', async () => {
  const w = world({ pageOrigin: 'https://arcade-only.avrana.net' });
  w.say(msg('hello', { game: 'bluff' }));
  await settle();
  assert.equal(w.bridge.bound(), null);
  assert.deepEqual(w.page.received, []);
  w.stop();
});

test('only the parent window is heard: a message from any other window is ignored', async () => {
  const w = world();
  const stranger = { postMessage() {} };
  w.say(msg('hello', { game: 'bluff' }), { from: stranger });              // right origin, wrong window
  await settle();
  assert.equal(w.bridge.bound(), null);
  w.say(msg('hello', { game: 'bluff' }));
  await settle();
  w.say(msg('end', { id: 'r1' }), { from: stranger });
  w.say(msg('end', { id: 'r2' }), { origin: EVIL });                        // the parent, after navigating away
  await settle();
  assert.deepEqual(w.api.posts, []);
  assert.equal(pushed(w, 'result').length, 0);
  w.stop();
});

test('the first hello binds the frame; a later hello for another game changes nothing', async () => {
  const w = world();
  w.say(msg('hello', { game: 'bluff' }));
  await settle();
  w.say(msg('hello', { game: 'arcade-gauntlet2' }));
  await settle();
  assert.deepEqual(w.bridge.bound(), { origin: GAMES, game: 'bluff' });
  w.stop();
});

test('nothing is answered before hello', async () => {
  const w = world();
  w.say(msg('ticket', { id: 'r1' }));
  await settle();
  assert.deepEqual(w.page.received, []);
  assert.deepEqual(w.api.posts, []);
  w.stop();
});

test('a ticket is asked for with the bound game and the page origin the browser reported', async () => {
  const w = world();
  w.say(msg('hello', { game: 'bluff' }));
  await settle();
  w.say(msg('ticket', { id: 'r1' }));
  await settle();
  assert.deepEqual(w.api.posts, [['/party/api/session/ticket', { game: 'bluff', origin: GAMES }]]);
  assert.deepEqual(pushed(w, 'ticket'), [msg('ticket', { id: 'r1', ok: true, ticket: 'aps0.e30.AAAA', role: 'player', expiresIn: 120 })]);
  assert.ok(!JSON.stringify(pushed(w, 'ticket')).includes('session-'));       // no session id either
  w.stop();
});

test('a refused ticket says why and carries no ticket', async () => {
  const w = world({ api: partyApi({ ticket: [409, { error: 'no_game', message: 'The party is playing another game.' }] }) });
  w.say(msg('hello', { game: 'bluff' }));
  await settle();
  w.say(msg('ticket', { id: 'r9' }));
  await settle();
  assert.deepEqual(pushed(w, 'ticket'), [msg('ticket', { id: 'r9', ok: false, error: 'no_game' })]);
  w.stop();
});

test('the host verbs go to Party Core, which decides; the answer is ok or the refusal', async () => {
  const refused = partyApi({ first: coreView({ me: ben }), answer: () => [403, { error: 'not_host', message: 'Only the host.' }] });
  const w = world({ api: refused });
  w.say(msg('hello', { game: 'bluff' }));
  await settle();
  w.say(msg('end', { id: 'r1' }));
  await settle();
  assert.deepEqual(w.api.posts.map((p) => p[0]), ['/party/api/session/end']);
  assert.deepEqual(pushed(w, 'result'), [msg('result', { id: 'r1', ok: false, error: 'not_host' })]);
  w.stop();

  const host = partyApi({ first: coreView({ me: ana, at: 'results' }) });
  const h = world({ api: host });
  h.say(msg('hello', { game: 'bluff' }));
  await settle();
  h.say(msg('home', { id: 'r1' }));
  await settle();
  h.say(msg('playAgain', { id: 'r2' }));
  await settle();
  assert.deepEqual(host.posts.map((p) => p[0]), ['/party/api/home', '/party/api/session/launch']);
  assert.equal(host.posts[1][1].game, 'bluff');                               // this game, never another
  assert.deepEqual(pushed(h, 'result').map((r) => [r.id, r.ok]), [['r1', true], ['r2', true]]);
  h.stop();
});

test('play again is refused when the party is not on this game', async () => {
  const api = partyApi({ first: coreView({ me: ana, at: 'home' }) });
  const w = world({ api });
  w.say(msg('hello', { game: 'bluff' }));
  await settle();
  w.say(msg('playAgain', { id: 'r1' }));
  await settle();
  assert.deepEqual(api.posts, []);
  assert.deepEqual(pushed(w, 'result'), [msg('result', { id: 'r1', ok: false, error: 'no_game' })]);
  w.stop();
});

test('when the party is elsewhere the page is told to go to Party Home, never given a URL', async () => {
  for (const first of [coreView({ at: 'home' }), coreView({ at: 'game', game: 'arcade-gauntlet2' })]) {
    const w = world({ api: partyApi({ first }) });
    w.say(msg('hello', { game: 'bluff' }));
    await settle();
    assert.deepEqual(pushed(w, 'navigate'), [msg('navigate', { to: 'party' })]);
    assert.ok(!JSON.stringify(w.page.received.map((m) => m.data)).includes('http'));
    w.stop();
  }
});

test('a phone with a profile is made present by the bridge; one without is not joined', async () => {
  const profile = { getItem: (k) => ({ 'wc-name': 'Ben', 'wc-avatar': 'gaze-12' })[k] ?? null, setItem() {} };
  const api = partyApi({ first: coreView({ me: null }), answer: () => [200, coreView({ version: 8 })] });
  const w = world({ api, storage: profile });
  w.say(msg('hello', { game: 'bluff' }));
  await settle();
  assert.deepEqual(api.posts[0], ['/party/api/join', { name: 'Ben', avatar: 'gaze-12' }]);
  assert.equal(pushed(w, 'view').at(-1).view.member, true);
  w.stop();

  const none = partyApi({ first: coreView({ me: null }) });
  const n = world({ api: none });
  n.say(msg('hello', { game: 'bluff' }));
  await settle();
  assert.deepEqual(none.posts, []);
  assert.equal(pushed(n, 'view').at(-1).view.member, false);
  n.stop();
});

test('with no Party Core the page is told so and nothing else happens', async () => {
  const w = world({ api: partyApi({ first: null }) });
  w.say(msg('hello', { game: 'bluff' }));
  await settle();
  assert.deepEqual(pushed(w, 'view').map((v) => v.view.party), [false]);
  w.stop();
});

// ---- the shim in a game page --------------------------------------------------------------------

function gamePage({ api = partyApi(), partyOrigin = PARTY, pageOrigin = GAMES } = {}) {
  const w = world({ pageOrigin, api });
  const went = [], frames = [];
  const doc = {
    createElement: () => {
      const attrs = {}, on = {};
      const el = { attrs, hidden: false, contentWindow: w.frameHandle, setAttribute: (k, v) => { attrs[k] = v; },
        addEventListener: (t, fn) => { on[t] = fn; }, remove() { el.removed = true; }, load: () => on.load && on.load() };
      frames.push(el);
      return el;
    },
    body: { append() {} },
  };
  const party = connectParty({ partyOrigin, game: 'bluff', window: w.page, document: doc, go: (url) => went.push(url), timeoutMs: 50 });
  return { ...w, party, went, frame0: frames[0], doc };
}

test('the shim embeds the Party bridge, sandboxed, and says hello when it has loaded', async () => {
  const g = gamePage();
  assert.equal(g.frame0.src, PARTY + '/party/bridge.html');
  assert.equal(g.frame0.attrs.sandbox, 'allow-scripts allow-same-origin');
  assert.equal(g.frame0.hidden, true);
  assert.equal(g.party.view(), null);
  g.frame0.load();
  await settle();
  assert.deepEqual(g.bridge.bound(), { origin: GAMES, game: 'bluff' });
  assert.deepEqual(g.party.view(), publicView(coreView()));
  assert.equal(g.party.active(), true);
  assert.equal(g.party.isHost(), false);
  assert.equal(g.party.hostName(), 'Ana');
  assert.deepEqual(g.party.location(), { at: 'game', game: 'bluff' });
  g.party.stop(); g.stop();
});

test('a game page gets its ticket through the shim and never sees an id or a cookie', async () => {
  const g = gamePage();
  g.frame0.load();
  await settle();
  const t = await g.party.ticket();
  assert.deepEqual(t, { ok: true, ticket: 'aps0.e30.AAAA', role: 'player', expiresIn: 120 });
  const everything = JSON.stringify(g.page.received);
  for (const bad of vectors.forbidden_in_a_view) assert.ok(!everything.includes(bad), bad);
  g.party.stop(); g.stop();
});

test('a ticket asked for before the frame has loaded is sent after the hello, not lost', async () => {
  const g = gamePage();
  const asked = g.party.ticket();                       // a game client connects as soon as it runs
  await Promise.resolve();
  assert.deepEqual(g.frame.received, []);               // nothing reaches a frame that is not there
  g.frame0.load();
  assert.deepEqual(await asked, { ok: true, ticket: 'aps0.e30.AAAA', role: 'player', expiresIn: 120 });
  assert.deepEqual(g.frame.received.map((m) => m.data.type), ['hello', 'ticket']);
  await settle();                                       // let the bridge finish starting before it is stopped
  g.party.stop(); g.stop();
});

test('an early request that timed out before the frame loaded is not sent late', async () => {
  const g = gamePage();
  assert.deepEqual(await g.party.ticket(), { ok: false, error: 'timeout' });
  g.frame0.load();
  await settle();
  assert.deepEqual(g.frame.received.map((m) => m.data.type), ['hello']);
  g.party.stop(); g.stop();
});

test('host verbs through the shim resolve with the Party\'s answer', async () => {
  const api = partyApi({ first: coreView({ me: ana }) });
  const g = gamePage({ api });
  g.frame0.load();
  await settle();
  assert.deepEqual(await g.party.end(), { ok: true, error: null });
  assert.deepEqual(api.posts.map((p) => p[0]), ['/party/api/session/end']);
  g.party.stop(); g.stop();
});

test('the shim goes to Party Home on its own origin setting, whatever a message says', async () => {
  const g = gamePage({ api: partyApi({ first: coreView({ at: 'home' }) }) });
  g.frame0.load();
  await settle();
  assert.deepEqual(g.went, [PARTY + '/party/']);
  g.party.stop(); g.stop();
});

test('the shim ignores messages that are not from its own Party frame', async () => {
  const g = gamePage();
  g.frame0.load();
  await settle();
  const before = g.party.view();
  const forgedView = msg('view', { view: { ...before, host: true, hostName: 'Mallory' } });
  g.page.deliver(forgedView, { origin: EVIL, handle: g.frameHandle }, GAMES);            // wrong origin
  g.page.deliver(forgedView, { origin: PARTY, handle: { postMessage() {} } }, GAMES);    // wrong window
  g.page.deliver(msg('navigate', { to: 'party' }), { origin: EVIL, handle: g.frameHandle }, GAMES);
  await settle();
  assert.deepEqual(g.party.view(), before);
  assert.deepEqual(g.went, []);
  g.party.stop(); g.stop();
});

test('a request with no answer times out instead of hanging the game', async () => {
  const g = gamePage({ pageOrigin: EVIL });                                  // the bridge stays silent
  g.frame0.load();
  await settle();
  assert.deepEqual(await g.party.ticket(), { ok: false, error: 'timeout' });
  g.party.stop(); g.stop();
});

test('connectParty refuses a Party origin that is not an origin', () => {
  for (const bad of ['', 'party.avrana.net', 'https://party.avrana.net/party/', null]) {
    assert.throws(() => connectParty({ partyOrigin: bad, game: 'bluff', window: fakeWindow(GAMES), document: {} }));
  }
});
