import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { HOME, readView, partyGame, tileMode, destination, roster, roundToRemember, setupPanel } from '../../web/party/lib/party-mode.js';
import { createPartyClient } from '../../web/party/lib/party-client.js';

const catalog = JSON.parse(readFileSync(new URL('../../web/party/catalog.json', import.meta.url)));
const byId = (id) => catalog.games.find((g) => g.id === id);

// A Party Core view (avrana/party/core.py PartyCore.view) with only what the page reads.
function view({ version = 5, state = 'lobby', me = { id: 'member-a', name: 'Ana', host: true }, session = null,
  games = ['bluff'], party = 'party-1', nav = { seq: 0, to: 'home', game: null, session: null, from: null },
  switching_to = null, location = { at: 'home', game: null, session: null } } = {}) {
  return { party, version, state, members: me ? [{ id: me.id, name: me.name, presence: 'here', host: me.host }] : [],
    host: me && me.host ? me.id : 'member-x', me, session, games, nav, switching_to, location };
}
const at = (where, game = 'bluff', session = 'session-1') => ({ at: where, game: where === 'home' ? null : game, session });
const active = (id = 'session-1', game = 'bluff', state = 'active') =>
  ({ id, game, state, outcome: null, detail: null, players: 2, my_role: 'player' });
const ben = { id: 'member-b', name: 'Ben', host: false };

test('a phone remembers a round only while it is on, and only as a member', () => {
  assert.deepEqual(roundToRemember(view({ state: 'active', session: active(), location: at('game') })), { game: 'bluff', session: 'session-1' });
  assert.deepEqual(roundToRemember(view({ me: ben, state: 'active', session: { ...active(), my_role: 'spectator' }, location: at('game') })),
    { game: 'bluff', session: 'session-1' });                              // a watcher was taken there too
  for (const where of ['home', 'setup', 'results'])                         // held results: a late phone was never in that round
    assert.equal(roundToRemember(view({ location: at(where) })), null, where);
  assert.equal(roundToRemember(view({ me: null, location: at('game') })), null);   // no profile, no record
  assert.equal(roundToRemember(null), null);
  assert.equal(roundToRemember({}), null);
});

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
  const donor = { ...catalog, games: [...catalog.games, { ...byId('bluff'), id: 'lan-chess', legacySlug: 'chess', entry: '/games/chess/', launchTarget: '/games/chess/' }] };
  assert.equal(partyGame(donor, 'chess').id, 'lan-chess');              // by the provider's slug
  assert.equal(partyGame(catalog, 'chess'), null);                      // a retired donor title is not offered
  assert.equal(partyGame(catalog, 'nope'), null);
  assert.equal(partyGame(catalog, 'ps1-worms'), null);                  // not installed: not offered
});

test('home: the host starts a party game, members wait, a phone without a profile is asked for a name', () => {
  const bluff = byId('bluff'), chess = { ...bluff, id: 'lan-chess', legacySlug: 'chess' };
  assert.equal(tileMode(bluff, view()).kind, 'start');
  assert.equal(tileMode(bluff, view({ me: ben })).kind, 'wait');
  assert.equal(tileMode(bluff, view({ me: null })).kind, 'profile');     // no Join: a profile is presence
  assert.equal(tileMode(chess, view()), null);                          // not a party game: today's tile
  assert.equal(tileMode(bluff, null), null);                            // catalog mode
  assert.equal(tileMode(byId('ps1-worms'), view({ games: ['ps1-worms'] })), null);
  assert.equal(tileMode(bluff, view({ state: 'launching', session: active('s', 'bluff', 'launching') })).kind, 'starting');
});

// ADR 0011 (the console model): one location for the whole party; a member's page is always there.
test('destination: every member page is where the party is, whatever page it is on', () => {
  const m = (loc, me = ben, games = ['bluff', 'arcade-gauntlet2']) => view({ me, games, location: loc });
  const BLUFF = '/games/bluff/?avrana=1', ARCADE = '/arcade/';
  const cases = [
    // [location, here, expected]
    [at('home'), HOME, null],
    [at('home'), 'bluff', '/party/'],              // a party game is never played alone in a party
    [at('home'), 'backgammon', null],              // a personal standalone game, while the party is home
    [at('setup'), HOME, null],                     // the setup scene is Party Home's
    [at('setup'), 'bluff', '/party/'],             // not the table: the setup scene
    [at('setup'), 'backgammon', '/party/'],        // the host took the party somewhere: go
    [at('game'), HOME, BLUFF],                     // Party Home cannot be browsed during a round
    [at('game'), 'bluff', null],
    [at('game'), 'backgammon', BLUFF],             // no "playing BLUFF" while in Backgammon
    [at('game'), 'arcade-gauntlet2', BLUFF],
    [at('results'), HOME, BLUFF],                  // results are the game's, until the host moves on
    [at('results'), 'bluff', null],
    [at('game', 'arcade-gauntlet2'), 'bluff', ARCADE],
    [at('game', 'arcade-gauntlet2'), HOME, ARCADE],
  ];
  for (const [loc, here, want] of cases) {
    assert.equal(destination(m(loc), here, catalog), want, `${loc.at}/${loc.game} on ${here}`);
    assert.equal(destination(m(loc, { ...ben, host: true }), here, catalog), want, 'the host too');
  }
  // nobody without a profile is moved; nor is anyone when Party Core has no location (older)
  assert.equal(destination(m(at('game'), null), 'backgammon', catalog), null);
  const old = m(at('game')); delete old.location;
  assert.equal(destination(old, HOME, catalog), null);
  // a game the catalog cannot open here: Party Home, never a dead link
  assert.equal(destination(m(at('game', 'nope')), 'bluff', catalog), '/party/');
  assert.equal(destination(m(at('game', 'nope')), HOME, catalog), null);
});

test('the roster: every member with avatar, host and round choice, from Party Core only', () => {
  const v = view({ me: ben });
  v.members = [{ id: 'member-a', name: 'Ana', avatar: 'gaze-07', presence: 'here', host: true },
    { id: 'member-b', name: 'Ben', avatar: null, presence: 'away', host: false }];
  v.session = { id: 's', game: 'bluff', state: 'setup', setup: { choices: { 'member-a': 'spectator' } } };
  assert.deepEqual(roster(v), [
    { id: 'member-a', name: 'Ana', avatar: 'gaze-07', host: true, me: false, away: false, choice: 'spectator' },
    { id: 'member-b', name: 'Ben', avatar: null, host: false, me: true, away: true, choice: null }]);
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

// ---- AVR-129: the Party's pregame -------------------------------------------------------------

const setupSession = (setup, id = 'session-1', game = 'bluff') =>
  ({ id, game, state: 'setup', outcome: null, detail: null, players: 0, my_role: null, setup });
function setupView({ me = ben, mine = null, waiting = ['member-a'], blocker = 'Waiting for Ana to choose Play or Watch.',
  version = 8, players = 1, spectators = 0 } = {}) {
  const v = view({ version, state: 'setup', me, session: setupSession({ min: 2, max: 6, mine, waiting, blocker,
    players, spectators, choices: {} }), nav: { seq: 1, to: 'game', game: 'bluff', session: 'session-1', from: null } });
  v.members = [{ id: 'member-a', name: 'Ana', presence: 'here', host: true }, { id: 'member-b', name: 'Ben', presence: 'here', host: false }];
  return v;
}

test('setupPanel: the decision and the host area, for members, only while a round is set up', () => {
  const p = setupPanel(setupView());
  assert.deepEqual(p, { game: 'bluff', mine: null, players: 1, spectators: 0, min: 2, max: 6, waiting: ['Ana'],
    host: false, hostName: 'Ana', canStart: false, starting: false, blocker: 'Waiting for Ana to choose Play or Watch.' });
  assert.equal(setupPanel(setupView({ me: null })), null);                  // no profile, no decision
  const host = { id: 'member-a', name: 'Ana', host: true };
  assert.equal(setupPanel(setupView({ me: host })).canStart, false);         // someone has not chosen
  assert.equal(setupPanel(setupView({ me: host, mine: 'player', waiting: [], blocker: null, players: 2 })).canStart, true);
  assert.equal(setupPanel(setupView({ mine: 'player', waiting: [], blocker: null, players: 2 })).canStart, false);
  const starting = setupView({ me: host, mine: 'player', waiting: [], blocker: null, players: 2 });
  starting.state = 'launching'; starting.session.my_role = 'player';
  assert.deepEqual([setupPanel(starting).starting, setupPanel(starting).canStart, setupPanel(starting).mine], [true, false, 'player']);
  assert.equal(setupPanel(view({ state: 'active', session: active() })), null);   // the round is on
});

test('choose and start: the member’s own choice; the host’s start retried once only when stale', async () => {
  let version = 8;
  const srv = fakeServer((url, init) => {
    if (url.endsWith('state')) return [200, setupView({ me: { id: 'member-a', name: 'Ana', host: true }, version })];
    if (url.includes('state?')) return 'hang';
    const body = JSON.parse(init.body);
    if (url.endsWith('session/choice')) {        // someone else joins right after: this answer is stale
      version += 2;
      return [200, setupView({ me: { id: 'member-a', name: 'Ana', host: true }, version: version - 1, mine: body.choice })];
    }
    if (body.if_version !== version) { version++; return [409, { error: 'stale', message: 'The party changed.' }]; }
    return [200, view({ version: version + 2, state: 'active', session: active() })];
  });
  const client = createPartyClient({ fetch: srv.fetch, onView() {} });
  client.start(setupView({ me: { id: 'member-a', name: 'Ana', host: true }, version: 7 }));
  assert.equal((await client.choose('spectator')).ok, true);
  const res = await client.startRound();
  assert.equal(res.ok, true);
  const posts = srv.calls.filter((c) => c.method === 'POST');
  assert.deepEqual(posts.map((c) => [c.url, c.body.choice || c.body.if_version]),
    [['api/session/choice', 'spectator'], ['api/session/start', 9], ['api/session/start', 11]]);
  client.stop(); srv.release();
});

test('a start refused because someone has not chosen is never retried', async () => {
  const srv = fakeServer((url) => url.includes('state?') ? 'hang'
    : url.endsWith('state') ? [200, setupView()] : [409, { error: 'unresolved', message: 'Waiting for Cy to choose Play or Watch.' }]);
  const client = createPartyClient({ fetch: srv.fetch, onView() {} });
  client.start(setupView({ me: { id: 'member-a', name: 'Ana', host: true } }));
  const res = await client.startRound();
  assert.equal(res.error, 'unresolved');
  assert.equal(srv.calls.filter((c) => c.method === 'POST').length, 1);
  client.stop(); srv.release();
});
