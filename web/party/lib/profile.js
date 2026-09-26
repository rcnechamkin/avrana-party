// Avrana owns this profile. These are the donor's existing backing keys, not a
// second identity store. Never expose the token in UI, URLs, diagnostics or caches.
export const AVATARS = ['🦊','🐸','🦖','🐙','🦉','🐯','🐼','🦄','👾','🤖','🐲','😈','🦈','🐝','🦩','🐢'];
const TOKEN = /^[A-Za-z0-9_-]{8,64}$/;
export const photoPath = (value) => typeof value === 'string'
  && /^\/avatars\/[a-f0-9]{20}\.webp(?:\?v=\d+)?$/.test(value) ? value : '';

export function createProfile(storage, random = globalThis.crypto) {
  const get = (key) => { try { return storage.getItem(key) || ''; } catch { return ''; } };
  const put = (key, value) => {
    try {
      storage.setItem(key, value);
      if (storage.getItem(key) !== value) throw new Error();
    } catch { throw new Error('This browser cannot save your profile. Allow local storage and try again.'); }
  };
  const list = (key) => {
    try {
      const value = JSON.parse(get(key) || '[]');
      return Array.isArray(value) ? [...new Set(value.filter((v) => typeof v === 'string'))] : [];
    } catch { return []; }
  };
  // Keep legacy slugs for LAN titles; namespace other games in the SAME backing lists.
  const keyFor = (game) => game.legacySlug || 'avrana:' + game.id;
  const snapshot = () => ({
    name: get('wc-name').slice(0, 24), avatar: get('wc-avatar').slice(0, 32) || AVATARS[0],
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
      put('wc-avatar', String(avatar || AVATARS[0]).slice(0, 32));
      return snapshot();
    },
    isFavorite(game) { return list('lg-favorites').includes(keyFor(game)); },
    toggleFavorite(game) {
      const values = new Set(list('lg-favorites')), key = keyFor(game);
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
