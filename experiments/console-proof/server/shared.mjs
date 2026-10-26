// Shared by the fixture Party server and the fixture game server (AVR-762 experiment only).
// Two browser origins, one site, like production (party.avrana.net / games.avrana.net):
//   Party origin  http://party.cp.test:8370   holds the device cookie (HttpOnly, host-only)
//   Game origin   http://games.cp.test:8371   holds only a Party-issued, game-scoped seat ticket
// Browsers resolve *.cp.test to 127.0.0.1 (Chromium --host-resolver-rules; WebKit via proxy.mjs).
import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize, resolve, sep } from 'node:path';

export const PARTY_PORT = Number(process.env.CP_PARTY_PORT || 8370);
export const GAME_PORT = Number(process.env.CP_GAME_PORT || 8371);
export const PROXY_PORT = Number(process.env.CP_PROXY_PORT || 8372);
export const PARTY = `http://party.cp.test:${PARTY_PORT}`;
export const GAME = `http://games.cp.test:${GAME_PORT}`;
export const COOKIE = 'cp_device';

// The secret the Party signs seat tickets with and the game server verifies (ADR 0006 tickets).
const SECRET = process.env.CP_SECRET ? Buffer.from(process.env.CP_SECRET, 'hex') : randomBytes(32);
const b64 = (buf) => Buffer.from(buf).toString('base64url');

/** A ticket for one participant in one game: {pid, game, role, seat, exp}. */
export function signTicket(claims) {
  const body = b64(JSON.stringify({ ...claims, n: randomBytes(9).toString('base64url') }));
  return `${body}.${b64(createHmac('sha256', SECRET).update(body).digest())}`;
}

/** The claims, or {error: 'bad' | 'expired'}. */
export function verifyTicket(ticket, game, now = Date.now()) {
  if (typeof ticket !== 'string' || ticket.length > 1024) return { error: 'bad' };
  const [body, mac] = ticket.split('.');
  if (!body || !mac) return { error: 'bad' };
  const want = createHmac('sha256', SECRET).update(body).digest();
  const got = Buffer.from(mac, 'base64url');
  if (got.length !== want.length || !timingSafeEqual(got, want)) return { error: 'bad' };
  let claims;
  try { claims = JSON.parse(Buffer.from(body, 'base64url').toString()); } catch { return { error: 'bad' }; }
  if (claims.game !== game || typeof claims.n !== 'string') return { error: 'bad' };
  if (!(claims.exp > now)) return { error: 'expired' };
  return claims;
}

export const CATALOG = [
  { id: 'rt', name: 'Dot Rally', players: { min: 1, max: 8 }, screen: 'phone', blurb: 'Realtime fixture: canvas, rAF, 20 Hz WebSocket ticks.' },
  { id: 'turn', name: 'Duel', players: { min: 2, max: 2 }, screen: 'phone', blurb: 'Turn-based fixture: private hands, server turn timer.' },
  { id: 'checkers', name: 'Checkers', players: { min: 2, max: 2 }, screen: 'phone', blurb: 'Classic board game.' },
  { id: 'bestguess', name: 'Best Guess', players: { min: 3, max: 8 }, screen: 'tv_optional', blurb: 'Guess the number.' },
  { id: 'coup', name: 'Coup', players: { min: 2, max: 6 }, screen: 'phone', blurb: 'Bluff and deduce.' },
  { id: 'tanks', name: 'Tanks', players: { min: 2, max: 4 }, screen: 'tv_optional', blurb: 'Realtime arena.' },
  { id: 'bluff', name: 'BLUFF', players: { min: 2, max: 8 }, screen: 'phone', blurb: 'Party card game.' },
  { id: 'expo', name: 'EXPO', players: { min: 3, max: 10 }, screen: 'tv_required', blurb: 'Drawing game.' },
];

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.png': 'image/png', '.webp': 'image/webp' };

/** Serve a file from `root` for `rel` (no traversal), or return false. */
export async function serveStatic(res, root, rel, headers = {}) {
  const base = resolve(root);
  const path = normalize(join(base, decodeURIComponent(rel)));
  if (path !== base && !path.startsWith(base + sep)) return false;
  try {
    let p = path;
    if ((await stat(p)).isDirectory()) p = join(p, 'index.html');
    const body = await readFile(p);
    res.writeHead(200, { 'content-type': TYPES[extname(p)] || 'application/octet-stream', 'cache-control': 'no-cache', ...headers });
    res.end(body);
    return true;
  } catch { return false; }
}

export async function readJson(req, limit = 4096) {
  let size = 0; const chunks = [];
  for await (const c of req) { size += c.length; if (size > limit) throw new Error('too big'); chunks.push(c); }
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString());
}

export const json = (res, status, body, headers = {}) => {
  res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store', ...headers });
  res.end(JSON.stringify(body));
};
