// The HTTP doorway (ADR 0012, LIMITED-MODE §3.1): where every phone starts. A browser's
// certificate warning cannot be redirected, so a phone cannot be sent *out of* broken HTTPS; it
// has to start on plain HTTP and be sent *into* HTTPS only when HTTPS works.
//
// The test is one request to the Full Mode origin. It succeeds only when the name resolves to
// the box, the certificate is trusted and the phone's clock agrees. The answer is never read
// (`no-cors`, no credentials): reaching it is the whole test. Pure: fetch and timers are passed in.

export const PROBE_MS = 3500;

/** { full, limited } from the page's own attributes, or null when either is not what a doorway
 * may send a phone to: `full` an https URL (http only on a loopback development host), `limited`
 * a plain-http URL. The page never takes a destination from its address or its query. */
export function targets(dataset) {
  const parse = (value) => { try { return new URL(String(value)); } catch { return null; } };
  const full = parse(dataset && dataset.full), limited = parse(dataset && dataset.limited);
  if (!full || !limited) return null;
  const loopback = full.hostname === '127.0.0.1' || full.hostname === 'localhost';
  if (full.protocol !== 'https:' && !(full.protocol === 'http:' && loopback)) return null;
  if (limited.protocol !== 'http:') return null;
  return { full: full.href, limited: limited.href };
}

/** 'full' when the Full Mode origin answered in time, else 'limited'. Never throws. */
export async function chooseMode({ full, fetch = globalThis.fetch, timeoutMs = PROBE_MS,
  schedule = setTimeout, cancel = clearTimeout } = {}) {
  const ctl = typeof AbortController === 'function' ? new AbortController() : null;
  let timer = null;
  const timeout = new Promise((resolve) => {
    timer = schedule(() => { if (ctl) ctl.abort(); resolve(false); }, timeoutMs);
  });
  const probe = (async () => {
    try {
      await fetch(new URL('api/origin.json', full).href,
        { mode: 'no-cors', cache: 'no-store', credentials: 'omit', signal: ctl ? ctl.signal : undefined });
      return true;
    } catch {
      return false;
    }
  })();
  const ok = await Promise.race([probe, timeout]);
  cancel(timer);
  return ok ? 'full' : 'limited';
}
