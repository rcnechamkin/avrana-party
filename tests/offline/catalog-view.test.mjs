import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { donorAvailability, visibleGames, filterGames, launchTarget } from '../../web/party/lib/catalog-view.js';
import { createProfile } from '../../web/party/lib/profile.js';
import { evaluateSeat } from '../../web/party/lib/evaluate.js';
const catalog = JSON.parse(readFileSync(new URL('../../web/party/catalog.json', import.meta.url)));
const map = new Map([['lg-favorites', '["chess","avrana:ps1-worms"]'], ['lg-recent', '["avrana:arcade-gauntlet2","chess"]']]);
const profile = createProfile({ getItem: (k) => map.get(k) ?? null, setItem: (k,v) => map.set(k,v) });

test('unified catalog includes individual browser titles, arcade and honest PS1 entries', () => {
  const games = visibleGames(catalog);
  assert.equal(games.length, 32); // 29 donor + arcade + 2 PS1; uninstalled BLUFF stays hidden.
  assert.equal(games.filter((g) => g.provider === 'lan-games').length, 29);
  const ps1 = games.filter((g) => g.provider === 'retroarch-ps1');
  assert.equal(ps1.length, 2);
  assert.ok(ps1.every((g) => !g.installed && !g.entry && g.hardwareValidationRequired));
});
test('favorites/history match donor slugs and cross-game IDs; filtering preserves order', () => {
  const games = visibleGames(catalog);
  assert.deepEqual(filterGames(games, { view: 'favorites' }, profile).map((g) => g.id), ['lan-chess','ps1-worms']);
  assert.deepEqual(filterGames(games, { view: 'recent' }, profile).map((g) => g.id), ['arcade-gauntlet2','lan-chess']);
  assert.deepEqual(filterGames(games, { query: 'chess', players: 2 }, profile).map((g) => g.id), ['lan-chess']);
  assert.equal(filterGames(games, { query: 'chess', players: 4 }, profile).length, 0);
});
test('donor API only confirms known visible slugs and never supplies launch authority', () => {
  assert.equal(donorAvailability({ games: [] }), null);
  const availability = donorAvailability({ games: [
    { slug: 'chess', live: { players: 1 }, entry: 'https://outside.test', requires: ['camera'] },
    { slug: 'template', hidden: true }, { title: 'Bad' }], external: [{ slug: 'wordclash' }] });
  assert.deepEqual(availability.get('chess'), { running: false, integration: false, players: 1, max: null });
  assert.ok(!availability.has('template'));
  assert.equal(catalog.games.find((g) => g.id === 'lan-chess').entry, '/games/chess/');
});
test('a weak phone cannot downgrade another phone or the provider catalog', () => {
  const game = catalog.games.find((g) => g.id === 'arcade-gauntlet2');
  const strong = { websocket: 'yes', webrtc: 'yes', 'video.h264': 'yes', wake_lock: 'yes', vibration: 'yes', web_audio: 'yes' };
  const before = evaluateSeat(game, strong);
  assert.equal(evaluateSeat(game, { ...strong, 'video.h264': 'no' }).outcome, 'unavailable');
  assert.deepEqual(evaluateSeat(game, strong), before);
  assert.equal(evaluateSeat(catalog.games.find((g) => g.id === 'lan-chess'), { websocket: 'yes', 'storage.local': 'yes' }).outcome, 'ready');
});

test('all granted browser titles launch directly with explicit context; invalid paths fail closed', () => {
  const games = catalog.games.filter((g) => g.provider === 'lan-games' && g.installed);
  assert.equal(games.length, 29);
  for (const game of games) {
    assert.equal(launchTarget(game), `/games/${game.legacySlug}/?avrana=1`);
    assert.equal(launchTarget({ ...game, entry: '/' }), null);
    assert.equal(launchTarget({ ...game, launchTarget: '//outside.test/' }), null);
  }
  assert.equal(launchTarget(catalog.games.find((g) => g.id === 'arcade-gauntlet2')), '/arcade/');
  const api = { games: [{ slug: 'chess' }], external: [], avranaIntegration: 'avrana.lan-launch/v1' };
  assert.equal(donorAvailability(api).get('chess').running, true);
  assert.equal(donorAvailability({ ...api, avranaIntegration: 'unknown' }).get('chess').running, false);
});
