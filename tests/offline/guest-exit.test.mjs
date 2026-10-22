// A guest's exit from a game page of another origin (AVR-580 guest exit, Party PR #184), on the
// phone's side: the drawer only asks, the one navigation decision (destination()) sends this device's
// pages to Party Home while the request is live, and the bridge uses its existing `navigate` and
// tells the game page nothing new.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPartyClient } from '../../web/party/lib/party-client.js';
import { startBridge, publicView } from '../../web/party/lib/bridge.js';
import { destination } from '../../web/party/lib/party-mode.js';
import { exitOffered, actions } from '../../web/party/lib/layer.js';

const ana = { id: 'member-a', name: 'Ana', host: true };
const ben = { id: 'member-b', name: 'Ben', host: false };
const inRound = { at: 'game', game: 'bluff', session: 'session-1' };
const view = (me, extra = {}) => ({ party: 'party-1', version: 7, state: 'active',
  members: [{ ...ana, presence: 'here' }, { ...ben, presence: 'here' }], host: 'member-a',
  me: me && { ...me, exit: null, leave: { host: me.host, successor: me.host ? 'Ben' : null, round: true } },
  session: { id: 'session-1', game: 'bluff', state: 'active', my_role: 'player' }, games: ['bluff'],
  nav: { seq: 2, to: 'game', game: 'bluff', session: 'session-1' }, location: inRound, departed: false, ...extra });
const asking = (live = true) => { const v = view(ben); v.me.exit = { id: 'exit-1', live }; return v; };
const store = (values = {}) => ({ getItem: (k) => values[k] ?? null, setItem: (k, v) => { values[k] = String(v); },
  removeItem: (k) => { delete values[k]; }, values });

test('the drawer offers "Leave Party…" only to a guest over another origin, during a round or its results', () => {
  assert.equal(exitOffered(view(ben), { crossOrigin: true }), true);
  assert.equal(exitOffered(view(ben, { location: { at: 'results', game: 'bluff', session: 'session-1' } }), { crossOrigin: true }), true);
  assert.equal(exitOffered(view(ben), { crossOrigin: false }), false);          // a Party-origin page: #167's Leave
  assert.equal(exitOffered(view(ben), {}), false);                               // origin not known yet: fail closed
  assert.equal(exitOffered(view(ana), { crossOrigin: true }), false);           // never the Host's
  assert.equal(exitOffered(view(ben, { location: { at: 'home', game: null, session: null } }), { crossOrigin: true }), false);
  assert.equal(exitOffered(view(null), { crossOrigin: true }), false);
  assert.deepEqual(actions(view(ana), { crossOrigin: true }), ['end', 'lobby']);   // the Host's D3 limit is unchanged
});

test('destination(): a live request is Party Home from anywhere; a stale or closed one moves nothing', () => {
  assert.equal(destination(asking(), 'bluff', null), '/party/');
  assert.equal(destination(asking(), 'home', null), null);                         // already there: stay to ask
  assert.equal(destination(asking(false), 'bluff', null), null);                   // stale: the game page stays
  assert.equal(destination(view(ben), 'bluff', null), null);
});

test('client: the request and Stay are plain Party API posts with this phone’s own credentials', async () => {
  const calls = [];
  const fetch = (url, init = {}) => {
    calls.push([init.method || 'GET', url, init.credentials]);
    if (url.startsWith('/party/api/state?')) return new Promise((_, rej) => init.signal?.addEventListener('abort', () => rej(new Error('aborted'))));
    return Promise.resolve({ ok: true, status: 200, json: async () => (url.endsWith('/leave/request') ? asking() : view(ben)) });
  };
  const client = createPartyClient({ fetch, base: '/party/api/', onView: () => {} });
  client.start(view(ben));
  assert.equal((await client.requestExit()).ok, true);
  assert.equal((await client.stay()).ok, true);
  client.stop();
  const posts = calls.filter(([m]) => m === 'POST').map(([, u]) => u);
  assert.deepEqual(posts, ['/party/api/leave/request', '/party/api/leave/stay']);
});

function bridgeWith(stateView) {
  const messages = [];
  const win = { parent: { postMessage: (m) => messages.push(m) }, addEventListener(type, fn) { this.on = fn; }, removeEventListener() {} };
  const fetch = (url, init = {}) => {
    const reply = (status, body) => Promise.resolve({ ok: status < 300, status, json: async () => body });
    if (url === '/party/api/bridge') return reply(200, { schema: 'avrana.party-bridge/v1', origins: { 'https://games.test': '*' } });
    if (url === '/party/api/state') return reply(200, stateView);
    return new Promise((_, reject) => init.signal?.addEventListener('abort', () => reject(new Error('aborted'))));
  };
  return { messages, win, b: startBridge({ win, fetch, storage: store({ 'wc-name': 'Ben' }), retryMs: [] }) };
}

test('the bridge sends the game page its existing navigate, once, and tells it nothing about the request', async () => {
  const { messages, win, b } = bridgeWith(asking());
  await win.on({ source: win.parent, origin: 'https://games.test', data: { avrana: 'avrana.party-bridge/v1', type: 'hello', game: 'bluff' } });
  for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0));
  b.stop();
  const nav = messages.filter((m) => m.type === 'navigate');
  assert.deepEqual(nav, [{ avrana: 'avrana.party-bridge/v1', type: 'navigate', to: 'party' }]);
  for (const m of messages) assert.doesNotMatch(JSON.stringify(m), /exit/);       // no new word reaches the game
  assert.deepEqual(Object.keys(publicView(asking())).sort(), Object.keys(publicView(view(ben))).sort());
});

test('a stale request moves no game page', async () => {
  const { messages, win, b } = bridgeWith(asking(false));
  await win.on({ source: win.parent, origin: 'https://games.test', data: { avrana: 'avrana.party-bridge/v1', type: 'hello', game: 'bluff' } });
  for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0));
  b.stop();
  assert.equal(messages.some((m) => m.type === 'navigate'), false);
});
