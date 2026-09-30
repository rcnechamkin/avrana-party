// The Party underneath a game page (web/party/lib/party-follow.js, ADR 0011) with a fake Party
// Core: a member's page is always where the party is (on load, and on every move), presence is
// automatic with a profile, and game shells get the host's controls through window.AvranaParty.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { startPartyFollow, gameOfPath, profileIdentity } from '../../web/party/lib/party-follow.js';

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
function origin(first, polls = [], { party = true, answer = () => [200, first] } = {}) {
  const queue = [...polls], posts = [];
  const fetch = (url, init = {}) => {
    const reply = (status, body) => Promise.resolve({ ok: status < 300, status, json: async () => body });
    if (url === '/party/catalog.json') return reply(200, catalog);
    if (!party) return reply(404, { detail: 'Not Found' });
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
  const api = await startPartyFollow({ here, fetch: o.fetch, go: (url) => went.push(url), storage, root: null });
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
