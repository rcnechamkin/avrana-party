// The in-game follower (web/party/lib/party-follow.js, AVR-128) with a fake Party Core: a page
// inside a game moves only on a committed Party move it watched, and never without a Party.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { startPartyFollow, gameOfPath } from '../../web/party/lib/party-follow.js';

const catalog = JSON.parse(readFileSync(new URL('../../web/party/catalog.json', import.meta.url)));
const ben = { id: 'member-b', name: 'Ben', host: false };
const nav = (seq, to, game = null, from = null) => ({ seq, to, game, session: game ? `session-${seq}` : null, from });
function view({ version, state = 'lobby', game = null, me = ben, n, party = 'party-1', switching_to = null }) {
  const session = game ? { id: n.session || 'session-x', game, state, outcome: null, detail: null, players: 2,
    my_role: 'player' } : null;
  return { party, version, state, members: me ? [{ ...me, presence: 'here' }] : [], host: 'member-a', me,
    session, games: ['bluff', 'chess'], nav: n, switching_to };
}
const inBluff = view({ version: 7, state: 'active', game: 'bluff', n: nav(1, 'game', 'bluff') });

/** A fake origin: the probe answers `first`, then each long poll takes the next view (then hangs). */
function origin(first, polls, { party = true } = {}) {
  const queue = [...polls];
  const hanging = [];
  const fetch = (url, init = {}) => {
    if (url === '/party/catalog.json') return Promise.resolve({ ok: true, status: 200, json: async () => catalog });
    if (!party) return Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: 'Not Found' }) });
    if (url === '/party/api/state') return Promise.resolve({ ok: true, status: 200, json: async () => first });
    if (url.startsWith('/party/api/state?') && queue.length) {
      const v = queue.shift();
      return Promise.resolve({ ok: true, status: 200, json: async () => v });
    }
    return new Promise((_, reject) => {
      hanging.push(reject);
      init.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
    });
  };
  return { fetch };
}
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0)); };

async function run(first, polls, here, opts) {
  const went = [], stored = new Map(), timers = [];
  const f = await startPartyFollow({ here, container: null, fetch: origin(first, polls, opts).fetch,
    go: (url) => went.push(url), storage: { setItem: (k, v) => stored.set(k, v) },
    schedule: (fn) => timers.push(fn) });
  await settle();
  timers.splice(0).forEach((fn) => fn());
  if (f) f.stop();
  return { f, went, stored };
}

test('the page game comes from its path', () => {
  assert.equal(gameOfPath('/games/bluff/'), 'bluff');
  assert.equal(gameOfPath('/games/bluff/table'), 'bluff');
  assert.equal(gameOfPath('/arcade/'), null);
  assert.equal(gameOfPath('/games/'), null);
});

test('the host switched: a player inside BLUFF goes to the next game and Party Home remembers it', async () => {
  const toChess = view({ version: 9, state: 'active', game: 'chess', n: nav(2, 'game', 'chess') });
  const { went, stored } = await run(inBluff, [toChess], 'bluff');
  assert.deepEqual(went, ['/games/chess/?avrana=1']);
  assert.equal(stored.get('avrana-party-entered'), 'session-2');
});

test('the host ended the game: its players go back to Party Home; the arcade stays', async () => {
  const home = view({ version: 8, n: nav(2, 'home', null, 'bluff') });
  assert.deepEqual((await run(inBluff, [home], 'bluff')).went, ['/party/']);
  assert.deepEqual((await run(inBluff, [home], null)).went, []);
});

test('the host started a party game: someone on the arcade follows into it', async () => {
  const lobby = view({ version: 3, n: nav(0, 'home') });
  const on = view({ version: 5, state: 'active', game: 'bluff', n: nav(1, 'game', 'bluff') });
  assert.deepEqual((await run(lobby, [on], null)).went, ['/games/bluff/?avrana=1']);
});

test('opening a page, a game ending by its own rules, a stranger and no Party never move anyone', async () => {
  const toChess = view({ version: 9, state: 'active', game: 'chess', n: nav(2, 'game', 'chess') });
  assert.deepEqual((await run(toChess, [], 'bluff')).went, []);                   // a reload: offer only
  const over = view({ version: 8, n: nav(1, 'game', 'bluff') });                  // BLUFF finished
  assert.deepEqual((await run(inBluff, [over], 'bluff')).went, []);
  const stranger = { ...toChess, me: null };
  assert.deepEqual((await run({ ...inBluff, me: null }, [stranger], 'bluff')).went, []);
  const none = await run(inBluff, [toChess], 'bluff', { party: false });
  assert.equal(none.f, null);
  assert.deepEqual(none.went, []);
});

test('a move that is overtaken before the delay ends does not navigate to the old target', async () => {
  const toChess = view({ version: 9, state: 'active', game: 'chess', n: nav(2, 'game', 'chess') });
  const back = view({ version: 11, n: nav(3, 'home', null, 'chess') });
  const { went } = await run(inBluff, [toChess, back], 'bluff');
  assert.deepEqual(went, []);        // chess was already over when the delay ended; BLUFF is not the one ended
});
