import { test } from 'node:test';
import assert from 'node:assert/strict';
import { coverRungs, packageImage, pickCover } from '../../web/party/lib/cover-art.js';

const URL1 = '/party/pkgart/demo/0123456789abcdef.webp';
const URL2 = '/party/pkgart/demo/fedcba9876543210.png';
const game = { id: 'demo', images: { cover: { url: URL1, w: 512, h: 512 }, icon: { url: URL2, w: 64, h: 64 } } };

test('the ladder: owner cover, package cover, package icon, first-party art, kind icon', () => {
  const kinds = (g, o) => coverRungs(g, o).map((r) => r.kind);
  assert.deepEqual(kinds(game, { own: 'covers/demo.png', art: 'art/lan-bluff.svg' }), ['own', 'package-cover', 'package-icon', 'art', 'icon']);
  assert.deepEqual(kinds(game, {}), ['package-cover', 'package-icon', 'icon']);
  assert.deepEqual(kinds({ id: 'demo' }, { art: 'art/lan-bluff.svg' }), ['art', 'icon']);
  assert.deepEqual(kinds({ id: 'demo' }, {}), ['icon']);
  assert.deepEqual(kinds({ ...game, images: { icon: game.images.icon } }, {}), ['package-icon', 'icon']);
});

test('a list row prefers the icon, else the cover; the owner cover still comes first', () => {
  assert.deepEqual(coverRungs(game, { small: true }).map((r) => r.kind), ['package-icon', 'package-cover', 'icon']);
  assert.deepEqual(coverRungs({ ...game, images: { cover: game.images.cover } }, { small: true }).map((r) => r.kind), ['package-cover', 'icon']);
  assert.equal(coverRungs(game, { small: true, own: 'covers/demo.png' })[0].kind, 'own');
});

test('pickCover skips a rung whose picture failed and always ends on the kind icon', () => {
  const opts = { own: 'covers/demo.png', art: 'art/lan-bluff.svg' };
  const failed = new Set();
  assert.equal(pickCover(game, opts, failed).src, 'covers/demo.png');
  failed.add('covers/demo.png');
  assert.equal(pickCover(game, opts, failed).src, URL1);
  failed.add(URL1);
  assert.equal(pickCover(game, opts, failed).src, URL2);
  failed.add(URL2);
  assert.equal(pickCover(game, opts, failed).src, 'art/lan-bluff.svg');
  failed.add('art/lan-bluff.svg');
  const last = pickCover(game, opts, failed);
  assert.equal(last.kind, 'icon');
  assert.equal(last.src, null);
});

test('width and height come with the picture', () => {
  assert.deepEqual(packageImage(game, 'cover'), { src: URL1, w: 512, h: 512 });
  assert.deepEqual(pickCover(game, {}, new Set()), { kind: 'package-cover', src: URL1, w: 512, h: 512 });
});

test('only the appliance shape is believed: another origin, another game, a path trick, a bad size', () => {
  const bad = (url, extra = {}) => packageImage({ id: 'demo', images: { cover: { url, w: 1, h: 1, ...extra } } }, 'cover');
  assert.equal(bad('https://evil.example/party/pkgart/demo/0123456789abcdef.webp'), null);
  assert.equal(bad('//evil.example/party/pkgart/demo/0123456789abcdef.webp'), null);
  assert.equal(bad('/party/pkgart/other/0123456789abcdef.webp'), null);              // listed under another game's id
  assert.equal(bad('/party/pkgart/demo/../x/0123456789abcdef.webp'), null);
  assert.equal(bad('/party/pkgart/demo/0123456789abcdef.svg'), null);
  assert.equal(bad('/party/pkgart/demo/0123456789ABCDEF.webp'), null);
  assert.equal(bad('/party/pkgart/demo/0123456789abcdef.webp?x=1'), null);
  assert.equal(bad('/party/art/demo/0123456789abcdef.webp'), null);
  assert.deepEqual(bad('/party/pkgart/demo/0123456789abcdef.jpg', { w: 0, h: 'x' }), { src: '/party/pkgart/demo/0123456789abcdef.jpg', w: null, h: null });
  for (const images of [null, 'x', [], { cover: null }, { cover: 'x' }, { cover: { url: 5 } }]) assert.equal(packageImage({ id: 'demo', images }, 'cover'), null);
  assert.equal(packageImage(null, 'cover'), null);
  assert.equal(packageImage({ id: 'demo' }, 'icon'), null);
});
