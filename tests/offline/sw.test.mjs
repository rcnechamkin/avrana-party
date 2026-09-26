// Tier 1 (node --test): the Full Mode service worker's policy and handlers, run in a VM with a
// fake worker global (no browser). Browser behaviour is covered by tests/offline/party.spec.ts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const SOURCE = readFileSync(new URL('../../web/party/sw.js', import.meta.url), 'utf8');
const ORIGIN = 'https://party.avrana.net';

// Stores bodies, so every match returns a fresh Response (as Cache Storage does).
class FakeCache {
  constructor() { this.map = new Map(); }
  async match(key) {
    const body = this.map.get(typeof key === 'string' ? key : key.url);
    return body === undefined ? undefined : new Response(body);
  }
  async put(key, res) { this.map.set(typeof key === 'string' ? key : key.url, await res.text()); }
  async addAll(requests) { for (const r of requests) this.map.set(r.url, `cached ${r.url}`); }
  async keys() { return [...this.map.keys()]; }
}

// A same-origin network response, as a browser reports it.
const basic = (body) => Object.defineProperty(new Response(body), 'type', { value: 'basic' });

function load({ source = SOURCE, network = async () => basic('fresh') } = {}) {
  const listeners = {};
  const stores = new Map();
  const caches = {
    async open(name) { if (!stores.has(name)) stores.set(name, new FakeCache()); return stores.get(name); },
    async keys() { return [...stores.keys()]; },
    async delete(name) { return stores.delete(name); },
  };
  const calls = { unregister: 0, claim: 0, skipWaiting: 0, navigated: [] };
  const self = {
    location: new URL(`${ORIGIN}/party/sw.js`),
    addEventListener: (type, fn) => { listeners[type] = fn; },
    skipWaiting: async () => { calls.skipWaiting += 1; },
    registration: { unregister: async () => { calls.unregister += 1; return true; } },
    clients: {
      claim: async () => { calls.claim += 1; },
      matchAll: async () => [{ url: `${ORIGIN}/party/`, navigate: async (u) => calls.navigated.push(u) }],
    },
  };
  const context = vm.createContext({
    self, caches, fetch: (req) => network(req), Request, Response, URL, Promise, setTimeout, clearTimeout,
  });
  vm.runInContext(source, context);
  return { shell: self.__avranaShell, listeners, stores, calls, caches };
}

function req(path, { method = 'GET', mode = 'no-cors', headers = {} } = {}) {
  const url = path.startsWith('http') ? path : `${ORIGIN}${path}`;
  return { url, method, mode, headers: new Headers(headers) };
}

async function dispatch(listeners, type, extra) {
  const pending = [];
  let response;
  const event = { ...extra, waitUntil: (p) => pending.push(p), respondWith: (p) => { response = p; } };
  listeners[type](event);
  await Promise.all(pending);
  return response === undefined ? undefined : await response;
}

test('policy: only same-origin GETs under /party/, never api/ or sw.js', () => {
  const { shell } = load();
  assert.equal(shell.SCOPE, '/party/');
  assert.equal(shell.policy(req('/party/', { mode: 'navigate' })), 'page');
  assert.equal(shell.policy(req('/party/diag/', { mode: 'navigate' })), 'page');
  assert.equal(shell.policy(req('/party/app.js')), 'shell');
  assert.equal(shell.policy(req('/party/catalog.json?x=1')), 'shell');
  for (const [r, why] of [
    [req('/'), 'the games hub'], [req('/arcade/'), 'the arcade'], [req('/arcade/stats'), 'arcade stats'],
    [req('/party/api/origin.json'), 'live checks'], [req('/party/sw.js'), 'the worker itself'],
    [req('/party/app.js', { method: 'POST' }), 'non-GET'], [req('https://example.com/party/app.js'), 'other origin'],
    [req('/party/unknown.js'), 'not a shell file'], [req('/party/app.js', { headers: { range: 'bytes=0-1' } }), 'range'],
    [req('/partyish/', { mode: 'navigate' }), 'outside the scope'],
  ]) assert.equal(shell.policy(r), 'bypass', why);
});

test('install precaches the shell under a build-named cache', async () => {
  const { listeners, stores, calls, shell } = load();
  await dispatch(listeners, 'install');
  assert.deepEqual([...stores.keys()], ['avrana-party-shell-dev']);
  const cached = await stores.get(shell.CACHE).keys();
  assert.ok(cached.includes(`${ORIGIN}/party/`));
  assert.ok(cached.includes(`${ORIGIN}/party/lib/capabilities.js`));
  assert.equal(cached.length, shell.SHELL.length);
  assert.equal(calls.skipWaiting, 1);
});

test('activate deletes only older shell caches', async () => {
  const { listeners, stores, caches, calls } = load();
  await caches.open('avrana-party-shell-old');
  await caches.open('someone-elses-cache');
  await dispatch(listeners, 'install');
  await dispatch(listeners, 'activate');
  assert.deepEqual([...stores.keys()].sort(), ['avrana-party-shell-dev', 'someone-elses-cache']);
  assert.equal(calls.claim, 1);
});

test('network first: fresh responses win and refresh the cache', async () => {
  const { listeners, stores, shell } = load({ network: async () => basic('fresh page') });
  await dispatch(listeners, 'install');
  const res = await dispatch(listeners, 'fetch', { request: req('/party/', { mode: 'navigate' }) });
  assert.equal(await res.text(), 'fresh page');
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(await (await stores.get(shell.CACHE).match(`${ORIGIN}/party/`)).text(), 'fresh page');
});

test('the Pi is unreachable: pages and shell files come from the saved copy', async () => {
  const { listeners } = load({ network: async () => { throw new TypeError('Failed to fetch'); } });
  await dispatch(listeners, 'install');
  const page = await dispatch(listeners, 'fetch', { request: req('/party/?x', { mode: 'navigate' }) });
  assert.equal(await page.text(), `cached ${ORIGIN}/party/`);
  const unknownPage = await dispatch(listeners, 'fetch', { request: req('/party/nothing-here/', { mode: 'navigate' }) });
  assert.equal(await unknownPage.text(), `cached ${ORIGIN}/party/`);
  const js = await dispatch(listeners, 'fetch', { request: req('/party/app.js') });
  assert.equal(await js.text(), `cached ${ORIGIN}/party/app.js`);
});

test('a hung network falls back to the saved page after the timeout', { timeout: 10000 }, async () => {
  const { listeners } = load({ network: () => new Promise(() => {}) });
  await dispatch(listeners, 'install');
  const started = Date.now();
  const page = await dispatch(listeners, 'fetch', { request: req('/party/', { mode: 'navigate' }) });
  assert.equal(await page.text(), `cached ${ORIGIN}/party/`);
  assert.ok(Date.now() - started >= 3900);
});

test('bypassed requests are left to the browser', async () => {
  const { listeners } = load();
  assert.equal(await dispatch(listeners, 'fetch', { request: req('/party/api/origin.json') }), undefined);
  assert.equal(await dispatch(listeners, 'fetch', { request: req('/', { mode: 'navigate' }) }), undefined);
});

test('kill switch: the self-destruct build cleans up and reloads pages', async () => {
  const killed = SOURCE.replace('const ENABLED = true;', 'const ENABLED = false;');
  const { listeners, stores, caches, calls } = load({ source: killed });
  await caches.open('avrana-party-shell-dev');
  await caches.open('avrana-party-shell-older');
  await dispatch(listeners, 'install');
  assert.equal(stores.size, 2);  // nothing new precached
  await dispatch(listeners, 'activate');
  assert.equal(stores.size, 0);
  assert.equal(calls.unregister, 1);
  assert.deepEqual(calls.navigated, [`${ORIGIN}/party/`]);
  assert.equal(await dispatch(listeners, 'fetch', { request: req('/party/', { mode: 'navigate' }) }), undefined);
});
