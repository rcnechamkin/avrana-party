// A sign-in redirect in front of Party Core (a hosted site's access gateway whose session ran out) is
// not "offline": it is said once, as 'signin', and no try counts as a transient failure. On the
// appliance Party Core never redirects, so nothing here changes what a Pi phone sees.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPartyClient, signinRedirect, transient, NO_FOLLOW } from '../../web/party/lib/party-client.js';
import { linkState, linkWords } from '../../web/party/lib/states.js';

const view = { party: 'party-1', version: 1, state: 'lobby', members: [], host: null, me: null, games: [],
  nav: { seq: 0, to: 'home', game: null, session: null, from: null }, location: { at: 'home', game: null, session: null } };
const json = (body) => ({ ok: true, status: 200, type: 'basic', json: async () => body });
const opaque = () => ({ ok: false, status: 0, type: 'opaqueredirect', json: async () => { throw new Error('opaque'); } });

test('an opaque redirect or a 3xx is a sign-in redirect; an answer, an error and a network failure are not', () => {
  assert.equal(signinRedirect(opaque()), true);
  assert.equal(signinRedirect({ ok: false, status: 302, type: 'basic' }), true);
  for (const res of [json(view), { ok: false, status: 0, type: 'error' }, { ok: false, status: 404, type: 'basic' },
    { ok: false, status: 503, type: 'basic' }, null])
    assert.equal(signinRedirect(res), false, JSON.stringify(res));
});

test('every Party Core request asks the browser not to follow a redirect', async () => {
  const seen = [];
  const party = createPartyClient({ fetch: async (url, init) => { seen.push(init.redirect); return json(view); }, onView() {} });
  await party.probe();
  await party.join('Ana', null);
  assert.ok(seen.length >= 2);
  assert.deepEqual([...new Set(seen)], [NO_FOLLOW]);
  assert.equal(NO_FOLLOW, 'manual');
});

test('an action answered by a sign-in redirect reports signin, is not transient, and tells the page', async () => {
  const links = [];
  const party = createPartyClient({ fetch: async () => opaque(), onView() {}, onLink: (l) => links.push(l) });
  const res = await party.join('Ana', null);
  assert.equal(res.ok, false);
  assert.equal(res.error, 'signin');
  assert.equal(res.signin, true);
  assert.equal(transient(res), false);            // probeRetrying gives up instead of retrying a minute
  assert.ok(links.some((l) => l.signin === true && l.ok === false));
  assert.equal(await party.probeRetrying([1, 1, 1]), null);
});

test('the long poll says signin, not offline, when a redirect answers it', async () => {
  const links = [];
  let calls = 0;
  let stopAfter;
  const done = new Promise((resolve) => { stopAfter = resolve; });
  const party = createPartyClient({
    fetch: async () => { calls++; return opaque(); },
    onView() {},
    onLink: (l) => { links.push(l); if (links.length >= 1) stopAfter(); },
    schedule: (fn) => setTimeout(fn, 0), cancel: clearTimeout });
  party.start(view);
  await done;
  party.stop();
  assert.ok(calls >= 1);
  assert.deepEqual(links[0], { ok: false, answered: true, signin: true });
});

test('a network failure is still offline, with no signin flag (the Pi path is unchanged)', async () => {
  const links = [];
  const party = createPartyClient({ fetch: async () => { throw new TypeError('Failed to fetch'); }, onView() {}, onLink: (l) => links.push(l) });
  const res = await party.join('Ana', null);
  assert.equal(res.error, 'offline');
  assert.equal(res.signin, undefined);
  assert.equal(links.some((l) => l.signin), false);
});

test('signin outranks every other link state and its words reload the page', () => {
  assert.equal(linkState(null, 0, true), 'signin');
  assert.equal(linkState(5, 10_000_000, true), 'signin');
  assert.equal(linkState(null, 0), 'ok');                   // the default is the old behavior
  const words = linkWords({ link: 'signin' });
  assert.equal(words.reload, true);
  assert.equal(words.retry, true);
  assert.match(words.title, /sign in/i);
  assert.doesNotMatch(words.text, /Wi-Fi/);
  assert.equal(linkWords({ link: 'lost' }).reload, undefined);  // the Pi's lost state never reloads
});
