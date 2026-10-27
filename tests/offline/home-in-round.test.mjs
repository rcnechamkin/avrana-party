// PROPOSAL home_in_round (AVR-703, Concept K K2) on the phone's side: a visit to Party Home during a
// round is this device's own, the one navigation decision (destination()) keeps its pages on Home
// while it lasts, and the client's two calls are plain Party API posts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPartyClient } from '../../web/party/lib/party-client.js';
import { destination } from '../../web/party/lib/party-mode.js';

const ben = { id: 'member-b', name: 'Ben', host: false };
const view = (visit) => ({ party: 'party-1', version: 7, state: 'active', members: [{ ...ben, presence: 'here' }],
  host: 'member-a', me: { ...ben, exit: null, ...(visit === undefined ? {} : { home_visit: visit }) },
  session: { id: 'session-1', game: 'bluff', state: 'active', my_role: 'player' }, games: ['bluff'],
  nav: { seq: 2, to: 'game', game: 'bluff', session: 'session-1' },
  location: { at: 'game', game: 'bluff', session: 'session-1' }, departed: false });

test('destination(): a visit keeps Party Home; Back to game, or no proposal, follows the round', () => {
  assert.equal(destination(view(true), 'home', null), null);                   // stays on Home
  assert.equal(destination(view(true), 'bluff', null), '/party/');             // a game page of this device goes Home
  assert.equal(destination(view(false), 'bluff', null), null);                 // back: the game page stays
  assert.equal(destination(view(undefined), 'bluff', null), null);             // no proposal: exactly as before
});

test('client: visitHome and backToGame post to the Party API', async () => {
  const calls = [];
  const fetch = (url, init = {}) => {
    calls.push([init.method || 'GET', url]);
    return Promise.resolve({ ok: true, status: 200, json: async () => view(url.endsWith('visit')) });
  };
  const client = createPartyClient({ fetch, onView() {} });
  await client.visitHome();
  await client.backToGame();
  assert.deepEqual(calls.filter(([m]) => m === 'POST').map(([, u]) => u), ['api/home/visit', 'api/home/back']);
  client.stop();
});
