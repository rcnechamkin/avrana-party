// The offline copy of the Party pages (service worker at /party/sw.js, scope /party/ only).
//
// No maintenance trap: sw.js is served no-cache and registered with updateViaCache 'none', so the
// browser rechecks it on every visit; version.json (network-first, so fresh whenever the Pi
// answers) can switch the offline copy off, which removes it here; the diagnostics page has a manual "Remove offline
// copy" button; and a self-destruct sw.js build (ENABLED = false) cleans up phones that never
// reload this page. The worker never touches the games hub, the arcade or anything outside /party/.

export const CACHE_PREFIX = 'avrana-party-shell-';
const SW_URL = new URL('../sw.js', import.meta.url);
const SCOPE = new URL('../', import.meta.url);
const VERSION_URL = new URL('../version.json', import.meta.url);

export async function readVersion(fetchImpl = globalThis.fetch) {
  try {
    const res = await fetchImpl(VERSION_URL, { cache: 'no-store' });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

/** Unregister every worker under /party/ and delete this shell's caches. */
export async function removeShell({ nav = globalThis.navigator, cachesImpl = globalThis.caches } = {}) {
  const removed = { registrations: 0, caches: 0 };
  if (nav && nav.serviceWorker && typeof nav.serviceWorker.getRegistrations === 'function') {
    for (const reg of await nav.serviceWorker.getRegistrations()) {
      if (new URL(reg.scope).pathname.startsWith(SCOPE.pathname) && await reg.unregister()) removed.registrations += 1;
    }
  }
  if (cachesImpl && typeof cachesImpl.keys === 'function') {
    for (const key of await cachesImpl.keys()) {
      if (key.startsWith(CACHE_PREFIX) && await cachesImpl.delete(key)) removed.caches += 1;
    }
  }
  return removed;
}

/**
 * Register the worker when this is a secure context and the appliance has not switched it off.
 * Returns { state: 'unsupported'|'disabled'|'registered'|'failed', version, error? }. Never throws.
 */
export async function registerShell({ nav = globalThis.navigator, secure = globalThis.isSecureContext,
  version } = {}) {
  const info = version === undefined ? await readVersion() : version;
  if (!secure || !nav || !nav.serviceWorker) return { state: 'unsupported', version: info };
  if (info && info.serviceWorker === false) {
    await removeShell({ nav }).catch(() => {});
    return { state: 'disabled', version: info };
  }
  try {
    const registration = await nav.serviceWorker.register(SW_URL, { scope: SCOPE.pathname, updateViaCache: 'none' });
    registration.update().catch(() => {});
    return { state: 'registered', version: info };
  } catch (err) {
    return { state: 'failed', version: info, error: (err && err.name) || 'error' };
  }
}

/** Describe the current worker and caches (diagnostics only). */
export async function describeShell({ nav = globalThis.navigator, cachesImpl = globalThis.caches } = {}) {
  const out = { controlled: false, scope: null, state: null, caches: [] };
  try {
    if (nav && nav.serviceWorker) {
      out.controlled = Boolean(nav.serviceWorker.controller);
      const reg = await nav.serviceWorker.getRegistration(SCOPE.pathname);
      if (reg) {
        out.scope = new URL(reg.scope).pathname;
        const worker = reg.active || reg.waiting || reg.installing;
        out.state = worker ? worker.state : null;
      }
    }
    if (cachesImpl) {
      for (const key of await cachesImpl.keys()) {
        if (!key.startsWith(CACHE_PREFIX)) continue;
        const cache = await cachesImpl.open(key);
        out.caches.push({ name: key, entries: (await cache.keys()).length });
      }
    }
  } catch (err) {
    out.error = (err && err.name) || 'error';
  }
  return out;
}
