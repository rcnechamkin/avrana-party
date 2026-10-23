import { test } from 'node:test';
import assert from 'node:assert/strict';
import { NARROW_AT, WIDE_AT, artRungs, contextOf, coverRungs, heroIsWide, packageImage, pickArt, pickCover } from '../../web/party/lib/cover-art.js';

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

// ---- the banner (AVR-466): which picture a place draws -------------------------------------------------------------

const BANNER = '/party/pkgart/demo/aaaaaaaaaaaaaaaa.webp';
const full = { id: 'demo', images: { ...game.images, banner: { url: BANNER, w: 1920, h: 1080 } } };
const kinds = (g, context, o = {}) => artRungs(g, context, o).map((r) => r.kind);

test('a wide hero draws the banner first, a narrow one the cover; a tile and a rail never draw the banner', () => {
  assert.deepEqual(kinds(full, 'hero', { wide: true }), ['package-banner', 'package-cover', 'package-icon', 'icon']);
  assert.deepEqual(kinds(full, 'hero', { wide: false }), ['package-cover', 'package-banner', 'package-icon', 'icon']);
  assert.deepEqual(kinds(full, 'tile'), ['package-cover', 'package-icon', 'icon']);
  assert.deepEqual(kinds(full, 'rail'), ['package-cover', 'package-icon', 'icon']);
  assert.deepEqual(kinds(full, 'row'), ['package-icon', 'package-cover', 'icon']);
  assert.deepEqual(kinds(full, 'nonsense'), ['package-cover', 'package-icon', 'icon']);     // an unknown place is a tile
});

test('the banner says how it is drawn: it fills a wide box and shows whole in a narrow one', () => {
  assert.equal(artRungs(full, 'hero', { wide: true })[0].fit, 'bleed');
  assert.equal(artRungs(full, 'hero', { wide: false })[1].fit, 'whole');
  assert.deepEqual(artRungs(full, 'hero', { wide: true })[0], { kind: 'package-banner', src: BANNER, w: 1920, h: 1080, fit: 'bleed' });
  assert.equal('fit' in artRungs(full, 'hero', { wide: true })[1], false);
});

test('every artwork combination has a deterministic ladder in every place', () => {
  const only = (...roles) => ({ id: 'demo', images: Object.fromEntries(roles.map((r) => [r, r === 'banner' ? full.images.banner : game.images[r]])) });
  const table = [
    // [roles, hero wide, hero narrow, tile, row]
    [['cover', 'icon', 'banner'], 'banner', 'cover', 'cover', 'icon'],
    [['cover', 'icon'], 'cover', 'cover', 'cover', 'icon'],
    [['cover'], 'cover', 'cover', 'cover', 'cover'],
    [['banner'], 'banner', 'banner', 'icon', 'icon'],      // banner only: a tile and a row fall to the kind icon, never a cropped banner
    [[], 'icon', 'icon', 'icon', 'icon'],
  ];
  for (const [roles, wide, narrow, tile, rowKind] of table) {
    const g = only(...roles);
    const first = (context, o) => artRungs(g, context, o)[0].kind.replace('package-', '');
    assert.equal(first('hero', { wide: true }), wide, roles.join());
    assert.equal(first('hero', { wide: false }), narrow, roles.join());
    assert.equal(first('tile'), tile, roles.join());
    assert.equal(first('row'), rowKind, roles.join());
  }
});

test('the owner’s cover leads in every place, a banner or not; with none, the package banner is not shadowed', () => {
  for (const context of ['hero', 'tile', 'rail', 'row']) {
    assert.equal(artRungs(full, context, { own: 'covers/demo.png', wide: true })[0].kind, 'own', context);
  }
  assert.equal(artRungs(full, 'hero', { wide: true })[0].kind, 'package-banner');                // no owner cover: the banner leads
  assert.deepEqual(kinds(full, 'hero', { own: 'covers/demo.png', wide: true }).slice(0, 3), ['own', 'package-banner', 'package-cover']);
});

test('a banner that fails to load falls to the cover, then the icon, then the title’s own art, then the kind icon', () => {
  const failed = new Set();
  const opts = { own: null, art: 'art/lan-bluff.svg', wide: true };
  assert.equal(pickArt(full, 'hero', opts, failed).src, BANNER);
  failed.add(BANNER);
  assert.equal(pickArt(full, 'hero', opts, failed).src, URL1);
  failed.add(URL1);
  assert.equal(pickArt(full, 'hero', opts, failed).src, URL2);
  failed.add(URL2);
  assert.equal(pickArt(full, 'hero', opts, failed).src, 'art/lan-bluff.svg');
  failed.add('art/lan-bluff.svg');
  assert.equal(pickArt(full, 'hero', opts, failed).kind, 'icon');
  // a failed banner changes nothing for a tile, which never asked for it
  assert.equal(pickArt(full, 'tile', {}, new Set([BANNER])).src, URL1);
});

test('only the appliance shape is believed for a banner too: its game, its place, its shape', () => {
  const bad = (url) => packageImage({ id: 'demo', images: { banner: { url, w: 1920, h: 1080 } } }, 'banner');
  assert.equal(bad('https://evil.example/party/pkgart/demo/0123456789abcdef.webp'), null);
  assert.equal(bad('/party/pkgart/other/0123456789abcdef.webp'), null);
  assert.equal(bad('/party/pkgart/demo/0123456789abcdef.svg'), null);
  assert.equal(bad('/party/pkgart/demo/0123456789abcdef.webp?x=1'), null);
  assert.equal(bad('/party/pkgart/demo/../x/0123456789abcdef.webp'), null);
  assert.deepEqual(packageImage(full, 'banner'), { src: BANNER, w: 1920, h: 1080 });
  assert.equal(packageImage(full, 'screenshots'), null);                    // no other role is a picture address
  assert.equal(packageImage(full, '__proto__'), null);
  assert.deepEqual(kinds({ id: 'demo', images: { banner: { url: 'https://evil.example/x.png', w: 1, h: 1 } } }, 'hero', { wide: true }), ['icon']);
});

test('a box is wide from 1.3 and narrow again only under 1.2, so a stage that gains a line does not flip', () => {
  assert.equal(heroIsWide(WIDE_AT), true);
  assert.equal(heroIsWide(WIDE_AT - 0.01), false);
  assert.equal(heroIsWide(0.84), false);                    // a phone held upright (375 x 447)
  assert.equal(heroIsWide(1.4), true);                      // the briefing's compact stage on that phone
  assert.equal(heroIsWide(2.43), true);                     // a phone on its side
  assert.equal(heroIsWide(1.25, true), true);               // inside the band, it keeps what it was
  assert.equal(heroIsWide(1.25, false), false);
  assert.equal(heroIsWide(NARROW_AT - 0.01, true), false);
  for (const bad of [0, -1, NaN, Infinity, undefined, null, '1.5']) assert.equal(heroIsWide(bad, true), true, String(bad)), assert.equal(heroIsWide(bad, false), false, String(bad));
});

test('a cover’s shape says its place', () => {
  assert.equal(contextOf('stage'), 'hero');
  assert.equal(contextOf('wide'), 'hero');
  assert.equal(contextOf('tall'), 'rail');
  assert.equal(contextOf('', true), 'row');
  assert.equal(contextOf(''), 'tile');
  assert.equal(contextOf(), 'tile');
});
