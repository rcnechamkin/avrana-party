import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { readView, partyGame, tileMode, arrival, follow } from '../../web/party/lib/party-mode.js';
import { createPartyClient } from '../../web/party/lib/party-client.js';

const catalog = JSON.parse(readFileSync(new URL('../../web/party/catalog.json', import.meta.url)));
const byId = (id) => catalog.games.find((g) => g.id === id);

// A Party Core view (avrana/party/core.py PartyCore.view) with only what the page reads.
function view({ version = 5, state = 'lobby', me = { id: 'member-a', name: 'Ana', host: true }, session = null,
  games = ['bluff'], party = 'party-1', nav = { seq: 0, to: 'home', game: null, session: null, from: null },
  switching_to = null } = {}) {
  return { party, version, state, members: me ? [{ id: me.id, name: me.name, presence: 'here', host: me.host }] : [],
    host: me && me.host ? me.id : 'member-x', me, session, games, nav, switching_to };
}
const active = (id = 'session-1', game = 'bluff', state = 'active') =>
  ({ id, game, state, outcome: null, detail: null, players: 2, my_role: 'player' });
const ben = { id: 'member-b', name: 'Ben', host: false };

test('only a real Party Core view turns Party mode on; anything else keeps the catalog', () => {
  assert.ok(readView(view()));
  for (const body of [null, 'x', {}, { detail: 'Not Found' }, { error: 'not_found' },
    { party: 'p', version: '5', members: [], games: [] }, { party: 3, version: 1, members: [], games: [] },
    { party: 'p', version: 1, members: 'x', games: [] }, { party: 'p', version: 1, members: [], games: 'bluff' }]) {
    assert.equal(readView(body), null, JSON.stringify(body));
  }
});

test('a Party Core game maps to its catalog title and launch path, never a hard-coded one', () => {
  assert.equal(partyGame(catalog, 'bluff').id, 'bluff');
  assert.equal(partyGame(catalog, 'chess').id, 'lan-chess');            // by the provider's slug
  assert.equal(partyGame(catalog, 'nope'), null);
  assert.equal(partyGame(catalog, 'ps1-worms'), null);                  // not installed: not offered
});

test('lobby: the host starts a party game, others wait, strangers are asked to join; standalone titles are untouched', () => {
  const bluff = byId('bluff'), chess = byId('lan-chess');
  assert.equal(tileMode(bluff, view()).kind, 'start');
  assert.equal(tileMode(bluff, view({ me: ben })).kind, 'wait');
  assert.equal(tileMode(bluff, view({ me: null })).kind, 'join');
  assert.equal(tileMode(chess, view()), null);                          // not a party game here
  assert.equal(tileMode(bluff, null), null);                            // catalog mode: today's tile
  assert.equal(tileMode(chess, view({ games: ['bluff', 'chess'] })).kind, 'start');
  assert.equal(tileMode(byId('ps1-worms'), view({ games: ['ps1-worms'] })), null);   // not installed here
});

test('while a party game is on: its tile rejoins, other party games are closed, standalone titles stay as they are', () => {
  const bluff = byId('bluff'), chess = byId('lan-chess'), orbit = byId('lan-orbitriot');
  const v = view({ state: 'active', session: active(), games: ['bluff', 'chess'], me: ben });
  assert.deepEqual(tileMode(bluff, v), { kind: 'rejoin', href: '/games/bluff/?avrana=1', session: 'session-1' });
  assert.deepEqual(tileMode(chess, v, catalog), { kind: 'busy', name: 'BLUFF' });
  assert.deepEqual(tileMode(chess, v), { kind: 'busy', name: 'bluff' });   // no catalog: the id
  assert.equal(tileMode(orbit, v), null);
  const host = view({ state: 'active', session: active(), games: ['bluff', 'chess'] });
  // the host never starts a second one: the tile switches (Party Core ends BLUFF first; AVR-128)
  assert.deepEqual(tileMode(chess, host, catalog), { kind: 'switch', game: 'chess', name: 'BLUFF' });
  assert.equal(tileMode(chess, view({ state: 'active', session: active(), games: ['bluff', 'chess'],
    switching_to: 'chess' })).kind, 'busy');                            // one switch at a time
  for (const s of ['launching', 'ending']) {
    const w = view({ state: s, session: active('session-1', 'bluff', s), games: ['bluff', 'chess'] });
    assert.equal(tileMode(bluff, w).kind, 'starting');
    assert.equal(tileMode(chess, w).kind, 'busy');
  }
  assert.equal(tileMode(bluff, view({ me: null, state: 'active', session: active() })).kind, 'join');
});

test('arrival: a live transition enters; a reload enters unless this tab already went in; storage failure only offers', () => {
  const lobby = view({ version: 5 });
  const launching = view({ version: 6, state: 'launching', session: active('session-1', 'bluff', 'launching') });
  const on = view({ version: 7, state: 'active', session: active() });
  assert.equal(arrival(on, { previous: launching, entered: null }), 'enter');     // watched it start
  assert.equal(arrival(on, { previous: lobby, entered: 'session-1' }), 'enter');   // a new start always enters
  assert.equal(arrival(on, { previous: null, entered: null }), 'enter');          // reopened /party/: resolve to it
  assert.equal(arrival(on, { previous: null, entered: 'session-0' }), 'enter');   // stale tab memory converges
  assert.equal(arrival(on, { previous: null, entered: 'session-1' }), 'offer');   // Back to Party: no bounce
  assert.equal(arrival(on, { previous: null, entered: undefined }), 'offer');     // no storage: never trap
  assert.equal(arrival(on, { previous: on, entered: null }), null);               // nothing changed
  assert.equal(arrival(launching, { previous: lobby, entered: null }), null);     // only a committed start moves anyone
  assert.equal(arrival(view({ version: 7, state: 'active', session: active(), me: null }), { previous: null, entered: null }), null);
  const other = view({ version: 9, state: 'active', session: active('session-1', 'ghost') });
  assert.equal(arrival(other, { previous: null, entered: null }), 'enter');       // the page checks the target
  const newParty = view({ version: 2, state: 'active', session: active(), party: 'party-2' });
  assert.equal(arrival(newParty, { previous: on, entered: null }), 'enter');
});

test('follow (AVR-128): a page inside a game moves only on a committed move it watched', () => {
  const nav = (seq, to, game = null, from = null) => ({ seq, to, game, session: game ? `session-${seq}` : null, from });
  const inBluff = view({ version: 7, state: 'active', session: active(), me: ben, nav: nav(1, 'game', 'bluff') });
  const toChess = view({ version: 9, state: 'active', session: active('session-2', 'chess'), me: ben, nav: nav(2, 'game', 'chess') });
  const home = view({ version: 8, me: ben, nav: nav(2, 'home', null, 'bluff') });
  assert.deepEqual(follow(toChess, inBluff, 'bluff'), { to: 'game', game: 'chess' });   // the host switched
  assert.deepEqual(follow(home, inBluff, 'bluff'), { to: 'home' });                     // the host ended it
  assert.equal(follow(home, inBluff, null), null);                   // the arcade / a standalone title stays
  assert.equal(follow(home, inBluff, 'chess'), null);                // another game's end is not this page's
  assert.deepEqual(follow(toChess, inBluff, null), { to: 'game', game: 'chess' });   // but a start pulls it in
  assert.equal(follow(toChess, inBluff, 'chess'), null);             // already there
  assert.equal(follow(inBluff, null, 'bluff'), null);                // opening or reloading never moves
  assert.equal(follow(toChess, null, 'bluff'), null);
  assert.equal(follow(toChess, toChess, 'bluff'), null);             // nothing new
  assert.equal(follow(inBluff, toChess, 'chess'), null);             // an older seq never moves anyone
  assert.equal(follow({ ...toChess, party: 'party-2' }, inBluff, 'bluff'), null);   // keyed by party (R5)
  assert.equal(follow({ ...toChess, me: null }, inBluff, 'bluff'), null);            // left: Leave is personal
  const selfEnded = view({ version: 8, me: ben, nav: nav(1, 'game', 'bluff') });     // BLUFF ended by its rules
  assert.equal(follow(selfEnded, inBluff, 'bluff'), null);            // its end screen stays
  const noNav = { ...toChess }; delete noNav.nav;
  assert.equal(follow(noNav, inBluff, 'bluff'), null);                // an older Party Core: no moves
});

// ---- the client: one long poll, actions win over polls, stale host actions retried once ------------

function fakeServer(views) {
  const calls = [];
  let pending = [];
  const fetch = (url, init = {}) => {
    calls.push({ url, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null });
    const route = views(url, init, calls.length);
    if (route === 'hang') {
      return new Promise((resolve, reject) => {
        pending.push(reject);
        init.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
      });
    }
    const [status, body] = route;
    return Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => body });
  };
  return { fetch, calls, release: () => { pending.forEach((r) => r(new Error('gone'))); pending = []; } };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

test('probe: a 404 or a non-Party answer is catalog mode', async () => {
  for (const route of [[404, { detail: 'Not Found' }], [200, { hello: 1 }], [502, null]]) {
    const srv = fakeServer(() => route);
    const client = createPartyClient({ fetch: srv.fetch, onView() {} });
    assert.equal(await client.probe(), null);
  }
  const srv = fakeServer(() => { throw new TypeError('offline'); });
  assert.equal(await createPartyClient({ fetch: srv.fetch, onView() {} }).probe(), null);
});

test('a stale host start is re-checked against a fresh view and tried once more', async () => {
  let version = 5;
  const srv = fakeServer((url, init) => {
    if (url.endsWith('state')) return [200, view({ version })];
    if (url.includes('state?')) return 'hang';
    const body = JSON.parse(init.body);
    if (body.if_version !== version) { version++; return [409, { error: 'stale', message: 'The party changed.' }]; }
    return [200, view({ version: version + 2, state: 'active', session: active() })];
  });
  const seen = [];
  const client = createPartyClient({ fetch: srv.fetch, onView: (v) => seen.push(v) });
  client.start(view({ version: 4 }));
  const res = await client.launch('bluff');
  assert.equal(res.ok, true);
  const posts = srv.calls.filter((c) => c.method === 'POST');
  assert.deepEqual(posts.map((c) => c.body.if_version), [4, 6]);
  assert.equal(client.view().state, 'active');
  client.stop(); srv.release();
});

test('a start refused for a real reason (not the host, busy) is never retried', async () => {
  for (const [error, status] of [['not_host', 403], ['busy', 409]]) {
    const srv = fakeServer((url) => url.includes('state?') ? 'hang'
      : url.endsWith('state') ? [200, view()] : [status, { error, message: 'No.' }]);
    const client = createPartyClient({ fetch: srv.fetch, onView() {} });
    client.start(view());
    const res = await client.launch('bluff');
    assert.equal(res.ok, false);
    assert.equal(res.error, error);
    assert.equal(srv.calls.filter((c) => c.method === 'POST').length, 1);
    client.stop(); srv.release();
  }
});

test('a poll that was already in flight when an action ran never overwrites the action result', async () => {
  const polls = [];
  const srv = fakeServer((url) => url.includes('state?') ? 'hang' : [200, view({ version: 7 })]);
  const fetch = (url, init = {}) => {
    if (!url.includes('state?')) return srv.fetch(url, init);
    return new Promise((resolve, reject) => {                         // answered by the test
      polls.push(resolve);
      init.signal?.addEventListener('abort', () => setTimeout(() => reject(new Error('aborted')), 50));
    });
  };
  const seen = [];
  const client = createPartyClient({ fetch, onView: (v) => seen.push(v) });
  client.start(view({ version: 6, me: null }));
  await tick();
  assert.equal(polls.length, 1);                                     // the observer's poll is out
  await client.act('join', { name: 'Ana' });
  assert.equal(client.view().me.name, 'Ana');
  // it comes back after the Join, newer but without the cookie's view: discarded
  polls[0]({ ok: true, status: 200, json: async () => view({ version: 8, me: null }) });
  await tick(); await tick();
  assert.equal(client.view().me.name, 'Ana');
  assert.ok(polls.length >= 2);                                      // and a fresh poll went out
  polls.at(-1)({ ok: true, status: 200, json: async () => view({ version: 9 }) });
  await tick(); await tick();
  assert.equal(client.view().version, 9);
  assert.equal(seen.at(-1).version, 9);
  client.stop();
});

test('the host switch goes to session/switch with the version and is retried once only when stale', async () => {
  let version = 7;
  const on = (v) => view({ version: v, state: 'active', session: active(), games: ['bluff', 'chess'] });
  const srv = fakeServer((url, init) => {
    if (url.endsWith('state')) return [200, on(version)];
    if (url.includes('state?')) return 'hang';
    const body = JSON.parse(init.body);
    if (body.if_version !== version) { version++; return [409, { error: 'stale', message: 'The party changed.' }]; }
    return [200, view({ version: version + 3, state: 'active', session: active('session-2', 'chess') })];
  });
  const client = createPartyClient({ fetch: srv.fetch, onView() {} });
  client.start(on(6));
  const res = await client.switchTo('chess');
  assert.equal(res.ok, true);
  const posts = srv.calls.filter((c) => c.method === 'POST');
  assert.deepEqual(posts.map((c) => [c.url, c.body.game, c.body.if_version]),
    [['api/session/switch', 'chess', 6], ['api/session/switch', 'chess', 8]]);
  client.stop(); srv.release();
});
