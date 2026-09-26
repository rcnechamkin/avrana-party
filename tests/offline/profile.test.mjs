import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createProfile, photoPath } from '../../web/party/lib/profile.js';

const lan = { id: 'lan-chess', legacySlug: 'chess' }, arcade = { id: 'arcade-gauntlet2' };
function fixture(values = {}) {
  const data = new Map(Object.entries(values));
  return { data, storage: { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, v) } };
}
test('existing donor identity and lists are reused, not copied into a parallel store', () => {
  const { data, storage } = fixture({ 'wc-token': 'existing-player-01', 'wc-name': 'Robin',
    'wc-avatar': '🐸', 'wc-pfp': '/avatars/0123456789abcdef0123.webp?v=12',
    'lg-favorites': '["chess","unknown-old-title"]', 'lg-recent': '["chess"]', 'lg-play-total': '7' });
  const p = createProfile(storage);
  assert.equal(p.identity().token, 'existing-player-01');
  assert.equal(p.snapshot().name, 'Robin');
  assert.ok(p.isFavorite(lan));
  p.save({ name: 'Robin Two', avatar: '🐙' });
  p.toggleFavorite(arcade);
  p.remember(arcade);
  assert.equal(data.get('wc-token'), 'existing-player-01');
  assert.equal(data.get('wc-name'), 'Robin Two'); // Legacy Hub.identity reads this exact key.
  assert.deepEqual(JSON.parse(data.get('lg-favorites')), ['avrana:lan-chess','unknown-old-title','avrana:arcade-gauntlet2']);
  assert.deepEqual(JSON.parse(data.get('lg-recent')), ['avrana:arcade-gauntlet2','avrana:lan-chess']);
  assert.equal(p.snapshot().playTotal, 8);
  assert.ok(!('token' in p.snapshot()));
  assert.ok([...data.keys()].every((key) => /^(wc-|lg-)/.test(key)));
});
test('new identity is persisted once, corrupt lists recover and recent history stays bounded', () => {
  const { data, storage } = fixture({ 'lg-favorites': '{broken', 'lg-recent': 'null' });
  const p = createProfile(storage);
  p.save({ name: ' New Guest ', avatar: '🦊' });
  assert.match(p.ensureToken(), /^[0-9a-f]{32}$/);
  assert.equal(p.ensureToken(), data.get('wc-token'));
  assert.equal(p.snapshot().name, 'New Guest');
  for (let i = 0; i < 10; i++) p.remember({ id: 'g' + i });
  p.remember({ id: 'g5' });
  assert.equal(p.snapshot().recent.length, 8);
  assert.equal(p.snapshot().recent[0], 'avrana:g5');
  assert.equal(p.snapshot().playTotal, 11);
});
test('storage failure cannot silently create a second ephemeral player identity', () => {
  const p = createProfile({ getItem() { throw new Error(); }, setItem() { throw new Error(); } });
  assert.equal(p.snapshot().name, '');
  assert.throws(() => p.identity(), /cannot save/);
  assert.throws(() => p.save({ name: 'Guest' }), /cannot save/);
  const corrupt = createProfile(fixture({ 'wc-token': 'bad!' }).storage);
  assert.throws(() => corrupt.identity(), /needs repair/);
});
test('photo compatibility uses the existing backend and same token only in headers', async () => {
  const { data, storage } = fixture({ 'wc-token': 'existing-player-01' });
  const p = createProfile(storage), calls = [];
  const request = async (path, init) => { calls.push([path, init]); return {
    ok: true, json: async () => ({ url: '/avatars/0123456789abcdef0123.webp?v=12' }) }; };
  await p.uploadPhoto(new Blob(['photo']), request);
  assert.equal(data.get('wc-pfp'), '/avatars/0123456789abcdef0123.webp?v=12');
  await p.removePhoto(request);
  assert.equal(data.get('wc-pfp'), '');
  assert.deepEqual(calls.map(([path, init]) => [path, init.method, init.headers['x-wc-token']]),
    [['/api/avatar', 'POST', 'existing-player-01'], ['/api/avatar', 'DELETE', 'existing-player-01']]);
  await assert.rejects(p.removePhoto(async () => ({ ok: false })), /Could not remove/);
});
test('photo URL validation rejects credentials, remote images and path tricks', () => {
  for (const path of ['https://other.test/photo.png','//other.test/avatars/a.webp','/avatars/../x',
    'data:image/png;base64,aaa','/avatars/0123456789abcdef0123.webp?token=bad']) assert.equal(photoPath(path), '');
});

test('legacy and canonical aliases collapse without losing unknown or cross-provider entries', () => {
  const { data, storage } = fixture({ 'lg-favorites': '["chess","lan-chess","avrana:lan-chess","unknown","avrana:ps1-worms"]',
    'lg-recent': '["chess","avrana:lan-chess","avrana:arcade-gauntlet2"]' });
  const p = createProfile(storage);
  assert.ok(p.isFavorite(lan));
  assert.deepEqual(p.snapshot().favorites, ['avrana:lan-chess','unknown','avrana:ps1-worms']);
  p.toggleFavorite(lan);
  assert.deepEqual(JSON.parse(data.get('lg-favorites')), ['unknown','avrana:ps1-worms']);
  p.remember(lan);
  assert.deepEqual(JSON.parse(data.get('lg-recent')), ['avrana:lan-chess','avrana:arcade-gauntlet2']);
});
