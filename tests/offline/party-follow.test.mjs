// The Party underneath a game page (web/party/lib/party-follow.js, ADR 0011) with a fake Party
// Core: a member's page is always where the party is (on load, and on every move), presence is
// automatic with a profile, and game shells get the host's controls through window.AvranaParty.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { startPartyFollow, followTarget, gameOfPath, profileIdentity } from '../../web/party/lib/party-follow.js';

const catalog = JSON.parse(readFileSync(new URL('../../web/party/catalog.json', import.meta.url)));
const ana = { id: 'member-a', name: 'Ana', host: true }, ben = { id: 'member-b', name: 'Ben', host: false };
const at = (where, game = 'bluff') => ({ at: where, game: where === 'home' ? null : game, session: where === 'home' ? null : 'session-1' });
function view({ version = 7, me = ben, location = at('game') } = {}) {
  return { party: 'party-1', version, state: location.at === 'game' ? 'active' : 'lobby',
    members: [{ ...ana, presence: 'here' }, { ...ben, presence: 'here' }], host: 'member-a', me,
    session: { id: 'session-1', game: 'bluff', state: 'active' }, games: ['bluff', 'arcade-gauntlet2'],
    nav: { seq: 1, to: 'game', game: 'bluff', session: 'session-1' }, location };
}
const store = (values = {}) => ({ getItem: (k) => values[k] ?? null, setItem: (k, v) => { values[k] = v; } });
const PROFILE = store({ 'wc-name': 'Benjamin The Great', 'wc-avatar': 'gaze-12' });

/** A fake origin: the probe answers `first`; POSTs are recorded and answered by `answer`;
 * each long poll takes the next of `polls`, then hangs until aborted. */
function origin(first, polls = [], { party = true, answer = () => [200, first], bridge = { schema: 'avrana.party-bridge/v1', origins: {} } } = {}) {
  const queue = [...polls], posts = [];
  const fetch = (url, init = {}) => {
    const reply = (status, body) => Promise.resolve({ ok: status < 300, status, json: async () => body });
    if (url === '/party/catalog.json') return reply(200, catalog);
    if (!party) return reply(404, { detail: 'Not Found' });
    if (url === '/party/api/bridge') return bridge ? reply(200, bridge) : reply(503, {});
    if (init.method === 'POST') { posts.push([url, JSON.parse(init.body)]); return reply(...answer(url)); }
    if (url === '/party/api/state') return reply(200, first);
    if (url.startsWith('/party/api/state?') && queue.length) return reply(200, queue.shift());
    return new Promise((_, reject) => init.signal?.addEventListener('abort', () => reject(new Error('aborted'))));
  };
  return { fetch, posts };
}
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0)); };

async function run(first, here, { polls = [], storage = PROFILE, ...opts } = {}) {
  const went = [];
  const o = origin(first, polls, opts);
  const api = await startPartyFollow({ here, fetch: o.fetch, go: (url) => went.push(url), storage, root: null,
    partyOrigin: 'http://party.avrana.test' });
  await settle();
  api?.stop();
  return { api, went, posts: o.posts };
}

test('the page game comes from its path; the Party name is the profile\'s, cut to 16', () => {
  assert.equal(gameOfPath('/games/bluff/'), 'bluff');
  assert.equal(gameOfPath('/arcade/'), null);
  assert.deepEqual(profileIdentity(PROFILE), { name: 'Benjamin The Gre', avatar: 'gaze-12' });
  assert.equal(profileIdentity(store()), null);
});

test('on load, a page in the wrong place goes where the party is at once', async () => {
  assert.deepEqual((await run(view({ location: at('game') }), 'backgammon')).went, ['/games/bluff/?avrana=1']);
  assert.deepEqual((await run(view({ location: at('home') }), 'bluff')).went, ['/party/']);
  assert.deepEqual((await run(view({ location: at('setup') }), 'bluff')).went, ['/party/']);
  assert.deepEqual((await run(view({ location: at('results') }), 'arcade-gauntlet2')).went, ['/games/bluff/?avrana=1']);
  assert.deepEqual((await run(view({ location: at('game') }), 'bluff')).went, []);     // already there
  assert.deepEqual((await run(view({ location: at('home') }), 'backgammon')).went, []); // personal, at home
});

test('every host move takes this page along; the page never moves on its own', async () => {
  const home = view({ version: 9, location: at('home') });
  assert.deepEqual((await run(view(), 'bluff', { polls: [home] })).went, ['/party/']);        // host ended
  const setupAgain = view({ version: 9, location: at('setup') });
  assert.deepEqual((await run(view(), 'bluff', { polls: [setupAgain] })).went, ['/party/']); // play again
  const arcade = view({ version: 9, location: at('game', 'arcade-gauntlet2') });
  assert.deepEqual((await run(view(), 'bluff', { polls: [arcade] })).went, ['/arcade/']);    // next game
  const results = view({ version: 9, location: at('results') });
  assert.deepEqual((await run(view(), 'bluff', { polls: [results] })).went, []);             // results: stay
});

test('presence is automatic: a phone with a profile joins on its own, with its avatar', async () => {
  const stranger = view({ me: null, location: at('game') });
  const { went, posts } = await run(stranger, 'backgammon', { answer: () => [200, view({ location: at('game') })] });
  assert.deepEqual(posts, [['/party/api/join', { name: 'Benjamin The Gre', avatar: 'gaze-12' }]]);
  assert.deepEqual(went, ['/games/bluff/?avrana=1']);                                 // and is taken there
});

test('no profile, or no Party Core: nothing joins, nothing moves, the page stays standalone', async () => {
  const none = await run(view({ me: null }), 'bluff', { storage: store() });
  assert.equal(none.api, null);
  assert.deepEqual([none.went, none.posts], [[], []]);
  const no = await run(view(), 'bluff', { party: false });
  assert.equal(no.api, null);
  assert.deepEqual(no.went, []);
});

test('the game shell gets the host\'s controls; they go to Party Core as the host\'s moves', async () => {
  const o = origin(view({ me: ana, location: at('results') }), [], { answer: () => [200, view({ me: ana, location: at('setup') })] });
  const api = await startPartyFollow({ here: 'bluff', fetch: o.fetch, go: () => {}, storage: PROFILE, root: null });
  assert.equal(api.isHost(), true);
  assert.equal(api.hostName(), 'Ana');
  assert.deepEqual(api.location(), at('results'));
  assert.equal(api.gameName(), 'BLUFF');
  await api.playAgain();
  await api.goHome();
  await api.end();
  assert.deepEqual(o.posts.map(([url, body]) => [url, body.game ?? null]),
    [['/party/api/session/launch', 'bluff'], ['/party/api/home', null], ['/party/api/session/end', null]]);
  api.stop();
});

// AVR-307: a member on a Party-origin game page goes to a started game's registered origin
// (ADR 0013), decided the way Party Home decides it, and is never shown the game on this origin.
const GAMES = 'http://games.avrana.test';
const bridgeOf = (origins) => ({ schema: 'avrana.party-bridge/v1', origins });
const inLimited = (v) => ({ ...v, mode: 'limited' });

test('followTarget: a started game opens on its registered origin; otherwise as before', () => {
  const started = view({ location: at('game', 'bluff') }), me = 'http://party.avrana.test';
  const pick = (v, origins, here = 'arcade-gauntlet2') => followTarget({ view: v, here, catalog, origins, partyOrigin: me });
  assert.equal(pick(started, { [GAMES]: '*' }), `${GAMES}/games/bluff/?avrana=1`);
  assert.equal(pick(started, { [GAMES]: ['bluff'] }), `${GAMES}/games/bluff/?avrana=1`);
  assert.equal(pick(started, { [GAMES]: ['expo'] }), '/games/bluff/?avrana=1');       // not registered for this game
  assert.equal(pick(started, {}), '/games/bluff/?avrana=1');                          // no registrations: today's path
  assert.equal(pick(inLimited(started), { [GAMES]: '*' }), '/games/bluff/?avrana=1'); // Limited Mode stays same-origin
  assert.equal(pick(started, { [GAMES]: '*' }, 'bluff'), null);                       // already there
  assert.equal(pick(view({ location: at('home') }), { [GAMES]: '*' }), '/party/');   // Party Home is the Party's
  assert.equal(pick(view({ location: at('setup') }), { [GAMES]: '*' }), '/party/');
  assert.equal(pick(view({ location: at('results') }), { [GAMES]: '*' }), `${GAMES}/games/bluff/?avrana=1`);
});

test('followTarget: an answer the shell will not follow, or none at all, is Party Home, never the same-origin path of an origin game', () => {
  const started = view({ location: at('game', 'bluff') }), me = 'http://party.avrana.test';
  const pick = (origins, partyOrigin = me) => followTarget({ view: started, here: 'arcade-gauntlet2', catalog, origins, partyOrigin });
  assert.equal(pick(null), '/party/');                                                // the ask failed
  assert.equal(pick({ 'http://games.avrana.test/x': '*' }), '/party/');               // malformed
  assert.equal(pick({ [GAMES]: '*', 'http://other.avrana.test': '*' }), '/party/');   // ambiguous
  assert.equal(pick({ [me]: '*' }), '/party/');                                       // the Party's own origin
  assert.equal(pick({ [GAMES]: '*' }, null), '/party/');                              // this page's origin unknown
  assert.equal(followTarget({ view: inLimited(started), here: 'arcade-gauntlet2', catalog, origins: null, partyOrigin: me }),
    '/games/bluff/?avrana=1');                                                        // Limited needs no answer
});

test('a page on the Party origin goes straight to the registered origin on a host move, and on load', async () => {
  const bridge = bridgeOf({ [GAMES]: '*' });
  const moved = await run(view({ location: at('game', 'arcade-gauntlet2') }), 'arcade-gauntlet2', { bridge, polls: [view({ version: 9, location: at('game') })] });
  assert.deepEqual(moved.went, [`${GAMES}/games/bluff/?avrana=1`]);                  // one move, no stop on the Party origin
  const loaded = await run(view({ location: at('game') }), 'arcade-gauntlet2', { bridge });
  assert.deepEqual(loaded.went, [`${GAMES}/games/bluff/?avrana=1`]);
  const limited = await run(inLimited(view({ location: at('game') })), 'arcade-gauntlet2', { bridge });
  assert.deepEqual(limited.went, ['/games/bluff/?avrana=1']);
  const plain = await run(view({ location: at('game') }), 'arcade-gauntlet2');       // nothing registered
  assert.deepEqual(plain.went, ['/games/bluff/?avrana=1']);
});

test('a bridge answer that fails sends the page to Party Home to decide, once', async () => {
  const failed = await run(view({ location: at('game') }), 'arcade-gauntlet2', { bridge: null });
  assert.deepEqual(failed.went, ['/party/']);
  const odd = await run(view({ location: at('game') }), 'arcade-gauntlet2', { bridge: { schema: 'something/else', origins: {} } });
  assert.deepEqual(odd.went, ['/party/']);
  const refused = await run(view({ location: at('game') }), 'arcade-gauntlet2', { bridge: bridgeOf({ [GAMES]: '*', 'http://other.avrana.test': '*' }) });
  assert.deepEqual(refused.went, ['/party/']);
});

// AVR-290: a Limited Mode phone (plain HTTP, ADR 0012) inside a first-party game or the arcade
// follows the Party exactly as a Full Mode phone does, but always on its own origin, and with no
// bridge ask. The follower is the same module over the same same-origin long poll; nothing about
// the transport or the credential differs, and the loaders no longer withhold it.
test('Limited Mode: every host move takes the page along, on this origin, asking nothing of the bridge', async () => {
  const bridge = bridgeOf({ [GAMES]: '*' });          // a registration that must never be consulted or used
  const go = async (first, here, polls = []) => {
    const o = origin(first, polls, { bridge });
    const went = [];
    const api = await startPartyFollow({ here, fetch: o.fetch, go: (u) => went.push(u), storage: PROFILE, root: null,
      partyOrigin: 'http://10.42.0.1' });
    await settle();
    api?.stop();
    return { went, asked: o.posts.length };
  };
  const gamePage = 'bluff', arcade = 'arcade-gauntlet2';
  // on load / reconnect: Home, setup, another game
  assert.deepEqual((await go(inLimited(view({ location: at('home') })), gamePage)).went, ['/party/']);
  assert.deepEqual((await go(inLimited(view({ location: at('setup') })), arcade)).went, ['/party/']);
  assert.deepEqual((await go(inLimited(view({ location: at('game') })), arcade)).went, ['/games/bluff/?avrana=1']);
  assert.deepEqual((await go(inLimited(view({ location: at('game', arcade) })), gamePage)).went, ['/arcade/']);
  assert.deepEqual((await go(inLimited(view({ location: at('game') })), gamePage)).went, []);        // already there
  // on a move: Host End/Home -> Party Home; switch -> the other title; results hold the round's page
  const home = inLimited(view({ version: 9, location: at('home') }));
  const next = inLimited(view({ version: 9, location: at('game', arcade) }));
  const results = inLimited(view({ version: 9, location: at('results') }));
  assert.deepEqual((await go(inLimited(view()), gamePage, [home])).went, ['/party/']);
  assert.deepEqual((await go(inLimited(view()), gamePage, [next])).went, ['/arcade/']);
  assert.deepEqual((await go(inLimited(view({ location: at('game', arcade) })), arcade, [home])).went, ['/party/']);
  assert.deepEqual((await go(inLimited(view()), gamePage, [results])).went, []);
  // never an absolute address: a Limited phone stays on the origin it is on
  for (const v of [home, next, results, inLimited(view())]) {
    for (const here of [gamePage, arcade]) {
      const first = inLimited(view({ location: at('game', here) }));
      for (const to of (await go(first, here, [v])).went) assert.match(to, /^\/(party|games|arcade)\//);
    }
  }
});

test('Limited Mode: a watcher follows like a player; a title that is not here is Party Home', async () => {
  const watcher = inLimited(view({ location: at('game') }));
  watcher.session = { ...watcher.session, my_role: 'spectator' };
  assert.deepEqual((await run(watcher, 'arcade-gauntlet2')).went, ['/games/bluff/?avrana=1']);
  const gone = inLimited(view({ location: at('game', 'backgammon') }));    // no launchable catalog title
  assert.deepEqual((await run(gone, 'bluff')).went, ['/party/']);
});

test('Limited Mode: the arcade page and Games\' loaders never gate the follower on a secure context', () => {
  const arcadePage = readFileSync(new URL('../../arcade/index.html', import.meta.url), 'utf8');
  const sameOrigin = /function sameOrigin\(\)\{[\s\S]*?\n\}/.exec(arcadePage)[0];
  assert.match(sameOrigin, /party-follow\.js/);
  assert.match(sameOrigin, /^function sameOrigin\(\)\{\s*if\(followed\)return;/);          // no scheme test before the follower
  // Wake Lock stays a secure-context feature (ADR 0012 degrades it, never emulates it).
  assert.match(sameOrigin, /isSecureContext&&'wakeLock' in navigator/);
  // The follower module itself checks nothing about the scheme.
  const follower = readFileSync(new URL('../../web/party/lib/party-follow.js', import.meta.url), 'utf8');
  assert.doesNotMatch(follower.replace(/\/\/.*/g, ''), /isSecureContext|location\.protocol/);
});
