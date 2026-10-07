/* Avrana Party Full Mode shell worker. Scope: /party/ (the path it is served from; nginx sends no
   Service-Worker-Allowed header, so it can never widen). Policy, most important first:

   - Only GET requests to this origin under /party/ are touched. The games hub (/), the arcade,
     PS1 streams, WebSockets and everything else go straight to the network.
   - /party/api/* and sw.js itself are never cached or answered from cache.
   - Pages and shell files are NETWORK-FIRST: the Pi is local and fast, so a phone on the Party
     Wi-Fi always runs the current build. The cache is only a fallback when the Pi cannot be
     reached (phone left the Wi-Fi, Pi restarting), so the page can say so instead of showing a
     browser error. No party state, identity or game data is ever cached.
   - BUILD is stamped at install (avrana.web.build); a new build replaces the old cache.
   - ENABLED = false turns this file into a self-destruct build: it deletes its caches,
     unregisters itself and reloads open pages. See docs/design/FULL-MODE.md. */
'use strict';

const BUILD = 'dev';
const ENABLED = true;
const CACHE_PREFIX = 'avrana-party-shell-';
const CACHE = CACHE_PREFIX + BUILD;
const SCOPE = new URL('./', self.location.href).pathname;
const NAV_TIMEOUT_MS = 4000;
// Everything the shell needs offline, relative to the scope. A test checks each file exists and
// that no other file under web/party/ is left out by accident.
const SHELL = [
  '', 'index.html', 'styles.css', 'app.js', 'manifest.json', 'icon.svg', 'catalog.json', 'version.json',
  'lib/capabilities.js', 'lib/evaluate.js', 'lib/keep-awake.js', 'lib/shell.js', 'lib/ui.js',
  'lib/profile.js', 'lib/profile-ui.js', 'lib/party-chat.js', 'lib/catalog-view.js', 'lib/catalog-load.js', 'lib/icons.js', 'lib/avatars.js',
  'lib/party-mode.js', 'lib/party-client.js', 'lib/party-follow.js', 'lib/limited.js', 'lib/game-origins.js',
  // The module of the frame, and the one bundled font with its licence (Geist, SIL OFL 1.1).
  'lib/frame.js', 'lib/library.js', 'lib/states.js', 'fonts/Geist-Variable.woff2', 'fonts/OFL.txt',
  // The bridge frame for game pages on another origin, and the reference shim (ADR 0013).
  'bridge.html', 'lib/bridge.js', 'lib/bridge-frame.js', 'bridge/shim.js',
  'diag/', 'diag/index.html', 'diag/diag.js',
  // Library artwork (tools/build-art.mjs from contracts/artwork.json).
  'art/kenney-exploding.svg', 'art/kenney-sword.svg', 'art/lan-bluff.svg',
  // Which games have a cover the owner supplied (AVR-306). The covers themselves are never here:
  // they are not part of a commit, and a phone without the box draws the art above instead.
  'covers/index.json',
  // Player avatars (tools/build-avatars.mjs): generated, committed, tiny.
  'avatars/gaze-01.svg', 'avatars/gaze-02.svg', 'avatars/gaze-03.svg', 'avatars/gaze-04.svg',
  'avatars/gaze-05.svg', 'avatars/gaze-06.svg', 'avatars/gaze-07.svg', 'avatars/gaze-08.svg',
  'avatars/gaze-09.svg', 'avatars/gaze-10.svg', 'avatars/gaze-11.svg', 'avatars/gaze-12.svg',
  'avatars/gaze-13.svg', 'avatars/gaze-14.svg', 'avatars/gaze-15.svg', 'avatars/gaze-16.svg',
  'avatars/gaze-17.svg', 'avatars/gaze-18.svg', 'avatars/gaze-19.svg', 'avatars/gaze-20.svg',
  'avatars/gaze-21.svg', 'avatars/gaze-22.svg', 'avatars/gaze-23.svg', 'avatars/gaze-24.svg',
  'avatars/gaze-25.svg', 'avatars/gaze-26.svg', 'avatars/gaze-27.svg', 'avatars/gaze-28.svg',
  'avatars/gaze-29.svg', 'avatars/gaze-30.svg', 'avatars/gaze-31.svg', 'avatars/gaze-32.svg',
];
const NEVER = [/^api\//, /^sw\.js$/];

function relative(url) {
  return url.pathname.startsWith(SCOPE) ? url.pathname.slice(SCOPE.length) : null;
}

/** 'bypass' | 'page' | 'shell' for a request (pure; exported for tests). */
function policy(request) {
  if (request.method !== 'GET') return 'bypass';
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return 'bypass';
  const rel = relative(url);
  if (rel === null || NEVER.some((re) => re.test(rel))) return 'bypass';
  if (request.headers && typeof request.headers.has === 'function' && request.headers.has('range')) return 'bypass';
  if (request.mode === 'navigate') return 'page';
  return SHELL.includes(rel) ? 'shell' : 'bypass';
}

function cacheKey(request) {
  const url = new URL(request.url);
  url.search = '';
  url.hash = '';
  return url.href;
}

async function fromCache(request) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(cacheKey(request));
  if (hit || request.mode !== 'navigate') return hit;
  // An unknown page under the scope falls back to the Party page itself.
  return cache.match(new URL(SCOPE, self.location.href).href);
}

async function networkFirst(event, kind) {
  const request = event.request;
  const network = fetch(request).then((response) => {
    if (response.ok && response.type === 'basic' && SHELL.includes(relative(new URL(request.url)))) {
      const copy = response.clone();
      const saved = caches.open(CACHE).then((cache) => cache.put(cacheKey(request), copy)).catch(() => {});
      try { event.waitUntil(saved); } catch { /* the event already settled; best effort */ }
    }
    return response;
  });
  network.catch(() => {}); // a late failure after the saved copy answered is not an error
  if (kind !== 'page') {
    return network.catch(async () => (await fromCache(request)) || Response.error());
  }
  // Pages: wait for the Pi a few seconds (a hung Wi-Fi join), then use the saved copy.
  let timer;
  const slow = new Promise((resolve) => { timer = setTimeout(() => resolve('slow'), NAV_TIMEOUT_MS); });
  try {
    const first = await Promise.race([network, slow]);
    if (first !== 'slow') return first;
    return (await fromCache(request)) || await network;
  } catch {
    return (await fromCache(request)) || Response.error();
  } finally {
    clearTimeout(timer);
  }
}

self.addEventListener('install', (event) => {
  if (!ENABLED) {
    event.waitUntil(self.skipWaiting());
    return;
  }
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(SHELL.map((rel) => new Request(new URL(rel, new URL(SCOPE, self.location.href)).href,
      { cache: 'reload' })));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith(CACHE_PREFIX) && (!ENABLED || key !== CACHE))
      .map((key) => caches.delete(key)));
    if (!ENABLED) {
      await self.registration.unregister();
      const pages = await self.clients.matchAll({ type: 'window' });
      await Promise.all(pages.map((page) => page.navigate(page.url).catch(() => {})));
      return;
    }
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  if (!ENABLED) return;
  const kind = policy(event.request);
  if (kind === 'bypass') return;
  event.respondWith(networkFirst(event, kind));
});

// Read-only hook for the unit tests (tests/offline/sw.test.mjs); nothing in a page uses it.
self.__avranaShell = Object.freeze({ BUILD, ENABLED, CACHE, SCOPE, SHELL, policy, cacheKey });
