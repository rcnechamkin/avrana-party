import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadCatalog, normalizeCatalog } from '../../web/party/lib/catalog-load.js';

const good = { games: [{ id: 'a' }], labels: {} };
const respond = (body, ok = true) => async () => ({ ok, json: async () => body });

test('a valid catalog loads as ok', async () => {
  const r = await loadCatalog(respond(good));
  assert.equal(r.ok, true);
  assert.deepEqual(r.catalog, good);
});
test('corrupt JSON gives an empty catalog and does not throw', async () => {
  const r = await loadCatalog(async () => ({ ok: true, json: async () => JSON.parse('{nope') }));
  assert.equal(r.ok, false);
  assert.deepEqual(r.catalog.games, []);
});
test('a missing file, a network failure and a wrong shape all degrade to empty', async () => {
  for (const f of [respond({}, false), async () => { throw new TypeError('offline'); }, respond({ games: 'x' }), respond(null)]) {
    const r = await loadCatalog(f);
    assert.equal(r.ok, false);
    assert.deepEqual(r.catalog.games, []);
  }
});
test('retry: the same loader succeeds once the file is back', async () => {
  let up = false;
  const f = async () => (up ? { ok: true, json: async () => good } : { ok: false });
  assert.equal((await loadCatalog(f)).ok, false);
  up = true;
  assert.equal((await loadCatalog(f)).ok, true);
});
test('normalizeCatalog returns a fresh empty catalog each time', () => {
  const a = normalizeCatalog(null).catalog, b = normalizeCatalog(null).catalog;
  a.games.push(1);
  assert.deepEqual(b.games, []);
});
