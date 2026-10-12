import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadCatalog, loadCovers, normalizeCatalog, normalizeCovers } from '../../web/party/lib/catalog-load.js';

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

test('covers: only a cover\'s own path, named for its game, is taken from the index', () => {
  const covers = normalizeCovers({ schema: 'avrana.covers/v0', covers: {
    'ps1-worms': 'covers/ps1-worms.jpg', 'ps1-bomberman': 'covers/ps1-bomberman.webp', expo: 'covers/expo.avif', pong: 'covers/pong.png',
    bluff: 'covers/expo.jpg',                    // another game's file
    'arcade-gauntlet2': '../secrets.jpg',        // not in the covers folder
    remote: 'https://example.com/remote.jpg', page: 'covers/page.html', svg: 'covers/svg.svg', deep: 'covers/a/deep.jpg',
    Upper: 'covers/Upper.jpg', number: 7, nothing: null, constructor: 'covers/constructor.gif',
  } });
  assert.deepEqual([...covers], [['ps1-worms', 'covers/ps1-worms.jpg'], ['ps1-bomberman', 'covers/ps1-bomberman.webp'], ['expo', 'covers/expo.avif'], ['pong', 'covers/pong.png']]);
  assert.equal(covers.get('constructor'), undefined);      // a Map: no name is special
  for (const junk of [null, undefined, 3, 'x', [], {}, { covers: null }, { covers: 'all' }, { covers: [] }]) assert.equal(normalizeCovers(junk).size, 0);
});

test('covers: a missing, refused, corrupt or unreachable index is no covers, never an error', async () => {
  const good = { covers: { bluff: 'covers/bluff.png' } };
  assert.deepEqual([...await loadCovers(async (url) => { assert.equal(url, 'covers/index.json'); return { ok: true, json: async () => good }; })], [['bluff', 'covers/bluff.png']]);
  assert.equal((await loadCovers(async () => ({ ok: false, json: async () => good }))).size, 0);
  assert.equal((await loadCovers(async () => ({ ok: true, json: async () => JSON.parse('{nope') }))).size, 0);
  assert.equal((await loadCovers(async () => { throw new TypeError('offline'); })).size, 0);
});
