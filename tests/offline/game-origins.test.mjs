// Where a game opens when Party Core registers it to a game origin (ADR 0013, AVR-303).
// web/party/lib/game-origins.js: a pure decision plus a once-per-load fetch of GET /party/api/bridge.
// Game ids here are made up on purpose: the code names no title.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { cleanOrigin, gameAddress, createGameOrigins } from '../../web/party/lib/game-origins.js';
import { destination, HOME } from '../../web/party/lib/party-mode.js';

const PARTY = 'https://party.example.test', GAMES = 'https://games.example.test';
const ENTRY = '/games/alpha/?avrana=1';
const ask = (origins, extra = {}) => gameAddress({ game: 'alpha', entry: ENTRY, origins, partyOrigin: PARTY, ...extra });

test('a game registered to an origin opens at that origin, on the entry path', () => {
  assert.equal(ask({ [GAMES]: ['alpha'] }), GAMES + ENTRY);
  assert.equal(ask({ [GAMES]: ['alpha', 'beta'] }), GAMES + ENTRY);
  assert.equal(ask({ 'http://10.0.0.5:8081': ['alpha'] }), 'http://10.0.0.5:8081' + ENTRY);
  assert.equal(ask({ [GAMES + '/']: ['alpha'] }), GAMES + ENTRY);            // one trailing slash is tolerated
});

test('a game that is not registered, or no answer at all, is the same-origin path as today', () => {
  assert.equal(ask({ [GAMES]: ['beta'] }), ENTRY);
  assert.equal(ask({}), ENTRY);
  assert.equal(ask(null), ENTRY);
  assert.equal(ask(undefined), ENTRY);
  assert.equal(ask([GAMES]), ENTRY);                                          // not the answer's shape
  assert.equal(ask({ [GAMES]: 'alpha' }), ENTRY);                             // neither '*' nor a list
});

test("'*' registers an origin for every game, as Party Core's own game_allowed does", () => {
  assert.equal(ask({ [GAMES]: '*' }), GAMES + ENTRY);
  assert.equal(gameAddress({ game: 'zeta', entry: '/zeta/', origins: { [GAMES]: '*' }, partyOrigin: PARTY }), GAMES + '/zeta/');
});

test('an origin that is not http(s)://host[:port] and nothing else is never followed', () => {
  for (const bad of [
    GAMES + '/x', GAMES + '/?a=1', GAMES + '?a=1', GAMES + '#f', 'https://user@games.example.test',
    'https://user:pw@games.example.test', 'javascript:alert(1)', '//games.example.test', 'games.example.test',
    'ftp://games.example.test', 'https://', GAMES + '//', GAMES + ' ', ' ' + GAMES,
    'https://games.example.test:443', 'HTTPS://GAMES.EXAMPLE.TEST', 'https:\\\\games.example.test',
    'https://games.example.test\\@evil.test', 'data:text/html,x', 'null', '', 'https://[::1]',
  ]) {
    assert.equal(ask({ [bad]: ['alpha'] }), null, JSON.stringify(bad));
  }
});

test('an origin equal to the Party origin is refused', () => {
  assert.equal(ask({ [PARTY]: ['alpha'] }), null);
  assert.equal(ask({ [PARTY]: '*' }), null);
  assert.equal(gameAddress({ game: 'alpha', entry: ENTRY, origins: { [GAMES]: ['alpha'] }, partyOrigin: GAMES }), null);
  assert.equal(ask({ [GAMES]: ['alpha'] }, { partyOrigin: 'null' }), null);   // an opaque page cannot compare
  assert.equal(ask({ [GAMES]: ['alpha'] }, { partyOrigin: undefined }), null);
});

test('two origins for one game is ambiguous: refused; two for different games is fine', () => {
  assert.equal(ask({ [GAMES]: ['alpha'], 'https://other.example.test': ['alpha'] }), null);
  assert.equal(ask({ [GAMES]: ['alpha'], 'https://other.example.test': '*' }), null);
  assert.equal(ask({ [GAMES]: ['alpha'], 'https://other.example.test': ['beta'] }), GAMES + ENTRY);
  // the same origin written twice is still one origin
  assert.equal(ask({ [GAMES]: ['alpha'], [GAMES + '/']: ['alpha'] }), GAMES + ENTRY);
  // one registration that is malformed poisons the game: stay on Party Home
  assert.equal(ask({ [GAMES]: ['alpha'], 'https://x.example.test/p': ['alpha'] }), null);
});

test('an entry that is not a plain same-origin path is refused', () => {
  const origins = { [GAMES]: ['alpha'] };
  for (const entry of ['//evil.test/', '//evil.test/games/alpha/', 'https://evil.test/', 'javascript:alert(1)',
    '/\\evil.test/', '\\\\evil.test\\x', '/games/\\evil', 'games/alpha/', '', null, undefined, 7, '/a b', '/a\nb', '/\t/evil.test']) {
    assert.equal(gameAddress({ game: 'alpha', entry, origins, partyOrigin: PARTY }), null, JSON.stringify(entry));
  }
  assert.equal(gameAddress({ game: 'alpha', entry: '/', origins, partyOrigin: PARTY }), GAMES + '/');
});

test('Limited Mode never goes cross-origin, whatever is registered', () => {
  assert.equal(ask({ [GAMES]: ['alpha'] }, { limited: true }), ENTRY);
  assert.equal(ask({ [GAMES]: '*' }, { limited: true }), ENTRY);
  assert.equal(ask({ 'https://x/y': ['alpha'] }, { limited: true }), ENTRY);   // not even looked at
});

test('cleanOrigin: canonical origins only', () => {
  assert.equal(cleanOrigin('https://a.test'), 'https://a.test');
  assert.equal(cleanOrigin('http://a.test:8080/'), 'http://a.test:8080');
  assert.equal(cleanOrigin('https://a.test/x'), null);
  assert.equal(cleanOrigin(7), null);
  assert.equal(cleanOrigin('https://' + 'a'.repeat(300)), null);
});

// destination() asks the address function only for a round, and a refusal keeps Party Home.
const catalog = JSON.parse(readFileSync(new URL('../../web/party/catalog.json', import.meta.url)));
test('destination: the address function moves a round to the game origin; a refusal stays on Party Home', () => {
  const game = catalog.games.find((g) => g.installed && g.entry);
  const id = game.legacySlug || game.id;
  const view = { party: 'p', version: 1, members: [], games: [id], me: { id: 'm', host: false },
    location: { at: 'game', game: id, session: 's' } };
  const entry = destination(view, HOME, catalog);
  assert.ok(entry && entry.startsWith('/'));
  const go = (origins, here = HOME, limited = false) => destination(view, here, catalog,
    (g, e) => gameAddress({ game: g, entry: e, origins, partyOrigin: PARTY, limited }));
  assert.equal(go({ [GAMES]: [id] }), GAMES + entry);
  assert.equal(go({}), entry);
  assert.equal(go({ [GAMES]: [id] }, HOME, true), entry);
  assert.equal(go({ [PARTY]: [id] }), null, 'refused: the phone stays on Party Home');
  assert.equal(go({ [PARTY]: [id] }, 'some-standalone-title'), '/party/', 'refused: a game page is sent home');
  const home = { ...view, location: { at: 'home', game: null, session: null } };
  assert.equal(destination(home, HOME, catalog, () => { throw new Error('not asked'); }), null);
});

test('the fetch: once per load, the answer is the origins; a failure is no origins and is tried again', async () => {
  let calls = 0, mode = 'ok';
  const fetch = async (url, init) => {
    calls += 1;
    assert.equal(url, '/party/api/bridge');
    assert.equal(init.credentials, 'same-origin');
    if (mode === 'throw') throw new Error('offline');
    if (mode === 'bad') return { ok: true, json: async () => ({ schema: 'other', origins: { [GAMES]: '*' } }) };
    if (mode === '500') return { ok: false, json: async () => ({}) };
    return { ok: true, json: async () => ({ schema: 'avrana.party-bridge/v1', origins: { [GAMES]: ['alpha'] } }) };
  };
  let t = 0;
  const go = createGameOrigins({ fetch, now: () => t });
  assert.equal(go.isSettled(), false);
  await Promise.all([go.settled(), go.settled()]);
  assert.equal(calls, 1);
  assert.deepEqual(go.get(), { [GAMES]: ['alpha'] });
  go.retry(); await go.settled();
  assert.equal(calls, 1, 'a good answer is not asked for again by retry');
  for (const m of ['throw', 'bad', '500']) {
    mode = m; t += 10000;
    await go.refresh();
    assert.equal(go.get(), null, m);
    assert.equal(go.ok(), false);
    assert.equal(go.isSettled(), true);
  }
  const before = calls;
  go.retry(); go.retry();                                   // within the retry window: no hammering
  assert.equal(calls, before);
  mode = 'ok'; t += 10000;
  go.retry(); go.retry();
  await go.settled();
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(calls, before + 1, 'retry asks once; asks in flight are shared');
  assert.deepEqual(go.get(), { [GAMES]: ['alpha'] });
});

test('a slow answer: nothing is settled until it arrives', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  const go = createGameOrigins({ fetch: async () => { await gate; return { ok: true, json: async () => ({ schema: 'avrana.party-bridge/v1', origins: {} }) }; } });
  let settled = false;
  go.settled().then(() => { settled = true; });
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(settled, false);
  release();
  await go.settled();
  assert.equal(go.isSettled(), true);
});

test('a refresh or retry on its way is waited for: no leaving on the old or failed answer', async () => {
  const good = { ok: true, json: async () => ({ schema: 'avrana.party-bridge/v1', origins: { [GAMES]: '*' } }) };
  let release, calls = 0, clock = 0;
  const gate = new Promise((r) => { release = r; });
  const go = createGameOrigins({ now: () => clock, fetch: async () => { calls += 1; if (calls === 1) throw new Error('down'); await gate; return good; } });
  await go.settled();
  assert.equal(go.ok(), false);                    // the first ask failed
  await new Promise((r) => setTimeout(r, 0));      // the failed ask has fully finished
  clock = 10000;
  go.retry();                                      // the next view asks again
  let settled = false;
  const waiting = go.settled().then(() => { settled = true; });
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(settled, false);                    // not settled while that ask is on its way
  release();
  await waiting;
  assert.deepEqual(go.get(), { [GAMES]: '*' });
});

test('never the Party host on another scheme, nor a host written with a trailing dot', () => {
  const at = (origin, partyOrigin = PARTY) => gameAddress({ game: 'g', entry: '/games/g/', origins: { [origin]: '*' }, partyOrigin });
  assert.equal(at('http://party.example.test'), null);
  assert.equal(at('https://party.example.test.'), null);
  assert.equal(at('https://games.example.test.'), null);
  assert.equal(at('http://games.example.test', 'http://party.example.test'), 'http://games.example.test/games/g/');
});

test('no title is named by the shell code for this behavior', () => {
  for (const f of ['lib/game-origins.js', 'lib/party-mode.js']) {
    const src = readFileSync(new URL('../../web/party/' + f, import.meta.url), 'utf8');
    assert.doesNotMatch(src.replace(/\/\/.*|\/\*[\s\S]*?\*\//g, ''), /\b(bluff|expo|arcade|standin|gauntlet)\b/i, f);
  }
});
