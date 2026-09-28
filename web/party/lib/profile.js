// Avrana owns this profile. These are the donor's existing backing keys, not a
// second identity store. Never expose the token in UI, URLs, diagnostics or caches.
import { AVATARS as GAZE } from './avatars.js';

/** Player avatars: stable ids ("gaze-17") of the bundled DiceBear Gaze set (lib/avatars.js). */
export const AVATARS = GAZE.map((a) => a.id);
export const avatarLabel = (id) => (GAZE.find((a) => a.id === id) || GAZE[0]).label;
// The donor's former emoji characters, in the donor's own order. A stored emoji is read as the
// Gaze avatar at the same position (never written back until the player saves); anything else
// unknown reads as the first avatar. The name and every other key are untouched.
export const LEGACY_AVATARS = ['🦊','🐸','🦖','🐙','🦉','🐯','🐼','🦄','👾','🤖','🐲','😈','🦈','🐝','🦩','🐢'];
export function resolveAvatar(value) {
  if (AVATARS.includes(value)) return value;
  const legacy = LEGACY_AVATARS.indexOf(value);
  return AVATARS[legacy >= 0 ? legacy : 0];
}
const TOKEN = /^[A-Za-z0-9_-]{8,64}$/;
export const photoPath = (value) => typeof value === 'string'
  && /^\/avatars\/[a-f0-9]{20}\.webp(?:\?v=\d+)?$/.test(value) ? value : '';
// The games' server sends a chosen Gaze avatar as this exact bundled picture path.
export const gazePicture = (value) => {
  const match = typeof value === 'string' && /^\/shared\/avatars\/(gaze-\d\d)\.svg$/.exec(value);
  return match && AVATARS.includes(match[1]) ? value : '';
};

export function createProfile(storage, random = globalThis.crypto) {
  const get = (key) => { try { return storage.getItem(key) || ''; } catch { return ''; } };
  const put = (key, value) => {
    try {
      storage.setItem(key, value);
      if (storage.getItem(key) !== value) throw new Error();
    } catch { throw new Error('This browser cannot save your profile. Allow local storage and try again.'); }
  };
  const aliases = new Map();
  const list = (key) => {
    try {
      const value = JSON.parse(get(key) || '[]');
      return Array.isArray(value) ? [...new Set(value.filter((v) => typeof v === 'string').map((v) => aliases.get(v) || v))] : [];
    } catch { return []; }
  };
  // Canonical IDs in the SAME lists; lazy, non-destructive compatibility reads.
  // Unknown old entries are preserved. Register known titles before reading lists.
  const keyFor = (game) => {
    const key = 'avrana:' + game.id;
    aliases.set(game.id, key); aliases.set(key, key);
    if (game.legacySlug) {
      aliases.set(game.legacySlug, key);
      aliases.set('avrana:lan-' + game.legacySlug, key);
    }
    return key;
  };
  const snapshot = () => ({
    name: get('wc-name').slice(0, 24), avatar: resolveAvatar(get('wc-avatar')),
    pfp: photoPath(get('wc-pfp')), favorites: list('lg-favorites'), recent: list('lg-recent'),
    playTotal: Math.max(0, Number(get('lg-play-total')) || 0),
  });
  const ensureToken = () => {
    const old = get('wc-token');
    if (old) {
      if (!TOKEN.test(old)) throw new Error('Your saved profile needs repair before joining chat.');
      return old; // Do not rotate an existing identity.
    }
    const token = [...random.getRandomValues(new Uint8Array(16))]
      .map((v) => v.toString(16).padStart(2, '0')).join('');
    put('wc-token', token); // Fail closed rather than create an unshared in-memory identity.
    return token;
  };
  return {
    snapshot, keyFor, ensureToken,
    identity() { return { token: ensureToken(), name: snapshot().name || 'PLAYER', avatar: snapshot().avatar }; },
    save({ name, avatar }) {
      const clean = String(name).trim().slice(0, 24);
      if (!clean) throw new Error('Choose a name first.');
      ensureToken();
      put('wc-name', clean);
      put('wc-avatar', resolveAvatar(avatar || snapshot().avatar));
      return snapshot();
    },
    isFavorite(game) { const key = keyFor(game); return list('lg-favorites').includes(key); },
    toggleFavorite(game) {
      const key = keyFor(game), values = new Set(list('lg-favorites'));
      if (values.has(key)) values.delete(key); else values.add(key);
      put('lg-favorites', JSON.stringify([...values]));
    },
    remember(game) {
      const key = keyFor(game);
      put('lg-recent', JSON.stringify([key, ...list('lg-recent').filter((v) => v !== key)].slice(0, 8)));
      put('lg-play-total', String(snapshot().playTotal + 1));
    },
    async uploadPhoto(blob, request = globalThis.fetch) {
      const res = await request('/api/avatar', {
        method: 'POST', headers: { 'x-wc-token': ensureToken() }, body: blob, cache: 'no-store',
      });
      if (!res.ok) throw new Error('Could not save your photo. Please try again.');
      const path = photoPath((await res.json()).url);
      if (!path) throw new Error('The photo could not be loaded.');
      put('wc-pfp', path);
      return path;
    },
    async removePhoto(request = globalThis.fetch) {
      const res = await request('/api/avatar', {
        method: 'DELETE', headers: { 'x-wc-token': ensureToken() }, cache: 'no-store',
      });
      if (!res.ok) throw new Error('Could not remove your photo. Please try again.');
      put('wc-pfp', '');
    },
  };
}
