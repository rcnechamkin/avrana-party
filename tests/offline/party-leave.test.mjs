// Leave Party and Reconnect on the phone's side (AVR-580): a device that left on purpose is not
// joined again by any page (Party Home, a game page, the bridge frame), whatever the reason a view
// arrives (refresh, another tab, a wake, a restarted Pi), until the person reconnects.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDeparture, LEFT_KEY } from '../../web/party/lib/departure.js';
import { createPartyClient } from '../../web/party/lib/party-client.js';
import { startPartyFollow } from '../../web/party/lib/party-follow.js';
import { startBridge, publicView } from '../../web/party/lib/bridge.js';
import { tileMode } from '../../web/party/lib/party-mode.js';
import { leaveWords } from '../../web/party/lib/states.js';

const ben = { id: 'member-b', name: 'Ben', host: false };
const game = { id: 'bluff', name: 'BLUFF' };
const view = (extra = {}) => ({ party: 'party-1', version: 3, state: 'lobby', members: [{ ...ben, presence: 'here' }],
  host: 'member-b', me: ben, session: null, games: ['bluff'], nav: { seq: 0, to: 'home' },
  location: { at: 'home', game: null, session: null }, departed: false, ...extra });
const gone = (extra = {}) => view({ me: null, host: null, members: [], departed: true, ...extra });
const unknown = (extra = {}) => view({ me: null, host: null, members: [], departed: false, ...extra });
const store = (values = {}) => ({ getItem: (k) => values[k] ?? null, setItem: (k, v) => { values[k] = String(v); },
  removeItem: (k) => { delete values[k]; }, values });
const PROFILE = { 'wc-name': 'Ben', 'wc-avatar': 'gaze-12' };

test('the marker follows Core: set by a departed view, cleared by a member view, never hides a membership', () => {
  const s = store(), d = createDeparture(s);
  assert.equal(d.apply(unknown()).departed, false);
  assert.equal(d.apply(gone()).departed, true);
  assert.equal(s.values[LEFT_KEY], '1');
  assert.equal(d.apply(unknown()).departed, true);          // a restarted Pi: Core forgot, this browser remembers
  assert.equal(d.apply(view()).departed, false);           // a real membership always wins...
  assert.equal(s.values[LEFT_KEY], '1');                   // ...but a view that may be older than the Leave never clears it
  d.clear();                                               // only a confirmed Reconnect does
  assert.equal(d.apply(unknown()).departed, false);
});

test('storage that throws never breaks a view', () => {
  const broken = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }, removeItem() { throw new Error('denied'); } };
  const d = createDeparture(broken);
  assert.equal(d.apply(gone()).departed, true);             // Core alone decides
  assert.equal(d.apply(unknown()).departed, false);
  assert.equal(createDeparture(null).apply(view()).departed, false);
});

test('tiles say Reconnect, not "choose your name", for a phone that left', () => {
  assert.deepEqual(tileMode(game, gone()), null);           // not a party game here: the tile is today's
  const v = gone({ games: ['bluff'] });
  const g = { id: 'bluff', installed: true, launch: { kind: 'web', path: '/games/bluff/' }, legacySlug: 'bluff' };
  const mode = tileMode(g, v);
  if (mode) assert.equal(mode.kind, 'reconnect');
  const fresh = tileMode(g, unknown());
  if (fresh) assert.equal(fresh.kind, 'profile');
});

test('the confirmation says what Leave does, for a member and for a Host with and without a successor', () => {
  const member = leaveWords({ host: false, successor: null, round: true });
  assert.match(member.text, /Everyone else stays where they are, and the round goes on/);
  assert.equal(member.host, '');
  const withSuccessor = leaveWords({ host: true, successor: 'Cleo', round: true });
  assert.match(withSuccessor.host, /Cleo becomes the Host right away/);
  assert.match(withSuccessor.host, /won’t be the Host when you come back/);
  assert.match(withSuccessor.host, /round goes on/);
  const alone = leaveWords({ host: true, successor: null, round: true });
  assert.match(alone.host, /nobody else is here to take over/);
  assert.match(alone.host, /nobody able to end it/);
  assert.doesNotMatch(alone.host + alone.text, /will end|is ended|will stop/);   // no silent termination
});

/** A fake Party Core for the client: records every request. */
function core(handlers) {
  const calls = [];
  const fetch = (url, init = {}) => {
    calls.push([init.method || 'GET', url, init.body ? JSON.parse(init.body) : null]);
    if (url.startsWith('/party/api/state?')) {             // the long poll waits until it is aborted
      return new Promise((_, reject) => init.signal?.addEventListener('abort', () => reject(new Error('aborted'))));
    }
    const [status, body] = handlers(url, init);
    if (status === 0) return Promise.reject(new Error('offline'));
    return Promise.resolve({ ok: status < 300, status, json: async () => body });
  };
  return { fetch, calls };
}

test('client: leave marks the browser, reconnect clears it, and a failed leave claims nothing', async () => {
  const s = store(), d = createDeparture(s);
  let up = true;
  const c = core((url) => (!up ? [0, null] : url.endsWith('/leave') ? [200, gone()] : [200, view()]));
  const seen = [];
  const client = createPartyClient({ fetch: c.fetch, base: '/party/api/', onView: (v) => seen.push(v), departure: d });
  client.start(view());
  up = false;
  const failed = await client.leave().catch(() => ({ ok: false }));
  assert.equal(failed.ok, false);
  assert.equal(d.left(), false);                            // nothing confirmed, nothing remembered
  up = true;
  assert.equal((await client.leave()).ok, true);
  assert.equal(d.left(), true);
  assert.equal(client.view().departed, true);
  const back = await client.reconnect('Ben', 'gaze-12');
  assert.equal(back.ok, true);
  const posts = c.calls.filter(([method]) => method === 'POST');
  assert.deepEqual(posts.at(-1), ['POST', '/party/api/reconnect', { name: 'Ben', avatar: 'gaze-12' }]);
  assert.equal(d.left(), false);
  client.stop();
});

async function run(first, here, { storage = store({ ...PROFILE }), answer } = {}) {
  const went = [], posts = [];
  const fetch = (url, init = {}) => {
    const reply = (status, body) => Promise.resolve({ ok: status < 300, status, json: async () => body });
    if (url === '/party/catalog.json') return reply(200, { games: [] });
    if (init.method === 'POST') { posts.push(url); return reply(...(answer ? answer(url) : [200, view()])); }
    if (url === '/party/api/state') return reply(200, first);
    return new Promise((_, reject) => init.signal?.addEventListener('abort', () => reject(new Error('aborted'))));
  };
  const api = await startPartyFollow({ here, fetch, go: (u) => went.push(u), storage, root: null, partyOrigin: 'http://party.test' });
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
  api?.stop();
  return { api, went, posts, storage };
}

test('a game page for a phone that left sends it to Party Home and never joins', async () => {
  const { api, went, posts } = await run(gone(), 'bluff');
  assert.equal(api, null);
  assert.deepEqual(went, ['/party/']);
  assert.deepEqual(posts, []);
});

test('a game page after a Pi restart: Core forgot the device, this browser did not; no join', async () => {
  const storage = store({ ...PROFILE, [LEFT_KEY]: '1' });
  const { api, went, posts } = await run(unknown(), 'bluff', { storage });
  assert.equal(api, null);
  assert.deepEqual(went, ['/party/']);
  assert.deepEqual(posts, []);
});

test('a game page for an unknown phone with a profile still joins on its own (nothing left)', async () => {
  const { posts } = await run(unknown(), 'bluff');
  assert.deepEqual(posts, ['/party/api/join']);
});

test('a game page that hears of a Leave from another tab goes to Party Home and does not join', async () => {
  const went = [], posts = [];
  const polls = [gone({ version: 4 })];
  const fetch = (url, init = {}) => {
    const reply = (status, body) => Promise.resolve({ ok: status < 300, status, json: async () => body });
    if (url === '/party/catalog.json') return reply(200, { games: [] });
    if (init.method === 'POST') { posts.push(url); return reply(200, view()); }
    if (url === '/party/api/state') return reply(200, view({ session: { id: 's', game: 'bluff', state: 'active' } }));
    if (url.startsWith('/party/api/state?') && polls.length) return reply(200, polls.shift());
    return new Promise((_, reject) => init.signal?.addEventListener('abort', () => reject(new Error('aborted'))));
  };
  const api = await startPartyFollow({ here: 'bluff', fetch, go: (u) => went.push(u), storage: store({ ...PROFILE }), root: null, partyOrigin: 'http://party.test' });
  for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0));
  api.stop();
  assert.ok(went.includes('/party/'));
  assert.deepEqual(posts, []);
});

test('the bridge tells a game origin to go to Party Home when the phone left, and joins nobody', async () => {
  const messages = [], posts = [];
  const win = { parent: { postMessage: (m) => messages.push(m) }, addEventListener(type, fn) { this.on = fn; }, removeEventListener() {} };
  const fetch = (url, init = {}) => {
    const reply = (status, body) => Promise.resolve({ ok: status < 300, status, json: async () => body });
    if (url === '/party/api/bridge') return reply(200, { schema: 'avrana.party-bridge/v1', origins: { 'https://games.test': '*' } });
    if (init.method === 'POST') { posts.push(url); return reply(200, view()); }
    if (url === '/party/api/state') return reply(200, gone());
    return new Promise((_, reject) => init.signal?.addEventListener('abort', () => reject(new Error('aborted'))));
  };
  const b = startBridge({ win, fetch, storage: store({ ...PROFILE }), retryMs: [] });
  await win.on({ source: win.parent, origin: 'https://games.test', data: { avrana: 'avrana.party-bridge/v1', type: 'hello', game: 'bluff' } });
  for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0));
  b.stop?.();
  assert.deepEqual(posts, []);
  assert.ok(messages.some((m) => m.type === 'navigate' && m.to === 'party'));
  assert.equal(publicView(gone()).member, false);
});
