// What the two join-card QR codes carry (AVR-76). Pure functions; no I/O.
//
// QR 1 is the standard Wi-Fi credential string that iPhone Camera and Android read natively.
// QR 2 is the Party link. It names only the Party origin: never a game origin (ADR 0013), never a
// query or fragment, so no token, device id or name can ride along (ONBOARDING "Must NOT").

export const FULL_MODE_URL = 'https://party.avrana.net/party/';
// The port-80 page at the IP literal: it resolves under every DNS condition and today links to
// Full Mode (avrana-party.nginx, `location = /`). LIMITED-MODE 3.1 makes it the doorway later.
export const HTTP_DOORWAY_URL = 'http://10.42.0.1/';
export const PARTY_URLS = Object.freeze([FULL_MODE_URL, HTTP_DOORWAY_URL]);

/** An error whose message is safe to print: it never contains the Wi-Fi password. */
export class JoinCardError extends Error {}

const CONTROL = /[\u0000-\u001f\u007f]/;
const escapeWifi = (s) => s.replace(/[\\;,:"]/g, (c) => `\\${c}`);

export function checkSsid(ssid) {
  if (typeof ssid !== 'string' || ssid.length === 0) throw new JoinCardError('Wi-Fi network name is missing');
  if (CONTROL.test(ssid)) throw new JoinCardError('Wi-Fi network name contains a control character');
  if (new TextEncoder().encode(ssid).length > 32) throw new JoinCardError('Wi-Fi network name is longer than 32 bytes');
  return ssid;
}

export function checkPassword(password) {
  if (typeof password !== 'string' || password.length === 0) throw new JoinCardError('Wi-Fi password is missing');
  if (/^[0-9a-fA-F]{64}$/.test(password)) return password;
  if (!/^[\x20-\x7e]{8,63}$/.test(password)) {
    throw new JoinCardError('Wi-Fi password must be 8 to 63 printable ASCII characters (WPA2-Personal)');
  }
  return password;
}

/** The Wi-Fi QR payload: `WIFI:T:WPA;S:<ssid>;P:<password>;;` with `\ ; , : "` escaped. */
export function wifiPayload({ ssid, password, hidden = false }) {
  checkSsid(ssid);
  checkPassword(password);
  return `WIFI:T:WPA;S:${escapeWifi(ssid)};P:${escapeWifi(password)};${hidden ? 'H:true;' : ''};`;
}

/**
 * Normalize a Party link and accept it only if it is one of PARTY_URLS.
 * Case of scheme and host, and a missing trailing slash on /party, are forgiven; anything else
 * (another host or port, a game origin, plain HTTP to the Full Mode name, credentials, a query or
 * a fragment) is refused.
 */
export function partyUrl(input = FULL_MODE_URL) {
  let url;
  try { url = new URL(String(input)); } catch { throw new JoinCardError(`not a URL: ${input}`); }
  if (url.username || url.password) throw new JoinCardError('the Party link must not carry credentials');
  if (url.search || url.hash || /[?#]/.test(String(input))) throw new JoinCardError('the Party link must not carry a query or fragment (no tokens in QR codes)');
  if (url.pathname === '/party') url.pathname = '/party/';
  const out = url.href;
  if (!PARTY_URLS.includes(out)) {
    throw new JoinCardError(`the Party link must be one of ${PARTY_URLS.join(' or ')}; got ${out}`);
  }
  return out;
}
