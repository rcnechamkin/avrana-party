// The fixture game server on the GAME origin (AVR-762 experiment). Authoritative for both fixture
// games; knows players only by Party-issued tickets. It never sees the Party cookie: the browser
// does not send a party.cp.test cookie to games.cp.test, and `cookieLeaks` counts any that arrive.
//
//   rt    realtime: 20 Hz tick broadcast, per-player dot moved by input
//   turn  turn-based: two seats, a private hand each, a turn timer the server enforces
import http from 'node:http';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';
import { COOKIE, GAME, PARTY, json, serveStatic, verifyTicket } from './shared.mjs';

const WEB = fileURLToPath(new URL('../web/game/', import.meta.url));
const VENDOR = fileURLToPath(new URL('../../../web/party/bridge/', import.meta.url));   // Games vendors layer-mount.js
export const TICK_MS = 50;
export const TURN_MS = Number(process.env.CP_TURN_MS || 20_000);

export function createGameServer() {
  const stats = { cookieLeaks: 0, ticks: 0, hellos: 0, rejects: { bad: 0, expired: 0, replayed: 0 }, connections: 0 };
  const revoked = new Set();                 // `${pid}:${game}` seats the Party took away
  const sockets = new Set();
  const used = new Map();                    // ticket nonce -> expiry: a ticket opens one socket, once
  const rt = { tick: 0, dots: {} };
  const turn = { seats: [], hands: {}, turn: 0, turnNo: 1, deadline: 0, log: [] };

  const card = (seat) => `PRIVATE-${seat}-${randomBytes(3).toString('hex')}`;
  function resetTurn(seatPids) {
    turn.seats = seatPids.slice(0, 2);
    turn.hands = {};
    turn.seats.forEach((pid) => { turn.hands[pid] = [card(pid), card(pid), card(pid)]; });
    turn.turn = 0; turn.turnNo = 1; turn.deadline = Date.now() + TURN_MS; turn.log = [];
  }

  const roleOf = (claims) => (claims.role === 'player' && !revoked.has(`${claims.pid}:${claims.game}`) ? 'player' : 'spectator');
  const send = (ws, msg) => { if (ws.readyState === 1) ws.send(JSON.stringify(msg)); };
  const turnPublic = () => ({ type: 'state', turn: turn.seats[turn.turn] || null, turnNo: turn.turnNo, deadline: turn.deadline, now: Date.now(),
    counts: Object.fromEntries(turn.seats.map((p) => [p, (turn.hands[p] || []).length])), log: turn.log.slice(-5) });
  function sendTurn(ws) {
    send(ws, turnPublic());
    if (ws.role === 'player' && turn.hands[ws.pid]) send(ws, { type: 'hand', cards: turn.hands[ws.pid] });
  }
  const each = (game, fn) => { for (const ws of sockets) if (ws.game === game && ws.pid) fn(ws); };

  setInterval(() => {
    rt.tick += 1; stats.ticks = rt.tick;
    const msg = JSON.stringify({ type: 'tick', t: rt.tick, now: Date.now(), dots: rt.dots });
    each('rt', (ws) => { if (ws.readyState === 1) ws.send(msg); });
    if (turn.seats.length && Date.now() >= turn.deadline) {          // the server's timer, not a client's
      turn.log.push(`turn ${turn.turnNo} timed out`);
      turn.turn = (turn.turn + 1) % turn.seats.length; turn.turnNo += 1; turn.deadline = Date.now() + TURN_MS;
      each('turn', sendTurn);
    }
  }, TICK_MS);

  const server = http.createServer(async (req, res) => {
    if ((req.headers.cookie || '').includes(COOKIE + '=')) stats.cookieLeaks += 1;
    const url = new URL(req.url, GAME);
    const headers = {
      // The embedded variant (a Party page framing the game) is the only framer allowed.
      'content-security-policy': `default-src 'self'; connect-src 'self' ws://games.cp.test:${url.port || 8371}; frame-src ${PARTY}; img-src 'self' data:; frame-ancestors ${PARTY}`,
    };
    if (url.pathname.startsWith('/vendor/')) {
      if (await serveStatic(res, VENDOR, url.pathname.slice('/vendor/'.length), headers)) return;
    } else if (await serveStatic(res, WEB, url.pathname.slice(1) || 'index.html', headers)) return;
    json(res, 404, { error: 'not_found' });
  });

  const wss = new WebSocketServer({ server, maxPayload: 4096 });
  wss.on('connection', (ws, req) => {
    if ((req.headers.cookie || '').includes(COOKIE + '=')) stats.cookieLeaks += 1;
    const game = new URL(req.url, GAME).pathname === '/ws/turn' ? 'turn' : 'rt';
    if (req.headers.origin !== GAME && req.headers.origin !== PARTY) { ws.close(1008, 'origin'); return; }   // PARTY: Limited Mode, same origin
    ws.game = game; stats.connections += 1; sockets.add(ws);
    ws.on('close', () => sockets.delete(ws));
    ws.on('message', (raw) => {
      let msg; try { msg = JSON.parse(raw); } catch { return; }
      if (msg.type === 'hello') {
        stats.hellos += 1;
        const claims = verifyTicket(msg.ticket, game);
        if (!claims.error && used.has(claims.n)) claims.error = 'replayed';
        if (claims.error) { stats.rejects[claims.error] += 1; send(ws, { type: 'reject', reason: claims.error }); return; }
        used.set(claims.n, claims.exp);
        for (const [n, exp] of used) if (exp < Date.now()) used.delete(n);
        ws.pid = claims.pid; ws.role = roleOf(claims); ws.name = claims.name;
        send(ws, { type: 'welcome', role: ws.role, you: ws.pid, now: Date.now() });
        if (game === 'rt') {
          if (ws.role === 'player' && !rt.dots[ws.pid]) rt.dots[ws.pid] = { x: 100 + Object.keys(rt.dots).length * 40, y: 200, name: ws.name };
          send(ws, { type: 'tick', t: rt.tick, now: Date.now(), dots: rt.dots });
        } else sendTurn(ws);
        return;
      }
      if (!ws.pid || ws.role !== 'player') return;                  // spectators never act
      if (game === 'rt' && msg.type === 'input' && rt.dots[ws.pid]) {
        const d = rt.dots[ws.pid];
        d.x = Math.max(0, Math.min(390, d.x + Math.sign(msg.dx || 0) * 10));
        d.y = Math.max(0, Math.min(600, d.y + Math.sign(msg.dy || 0) * 10));
        d.seq = Number(msg.seq) || 0;
      }
      if (game === 'turn' && msg.type === 'play' && turn.seats[turn.turn] === ws.pid) {
        const hand = turn.hands[ws.pid]; const at = hand.indexOf(msg.card);
        if (at < 0) return;
        hand.splice(at, 1, card(ws.pid));
        turn.log.push(`${ws.name} played`);
        turn.turn = (turn.turn + 1) % turn.seats.length; turn.turnNo += 1; turn.deadline = Date.now() + TURN_MS;
        each('turn', sendTurn);
      }
    });
  });

  return {
    server, stats,
    /** The Party's server-to-server seam: seat the round, take a seat away, drop sockets. */
    seat(game, pids) { if (game === 'turn') resetTurn(pids); else rt.dots = {}; for (const p of pids) revoked.delete(`${p}:${game}`); },
    revoke(pid, game) {
      revoked.add(`${pid}:${game}`);
      if (game === 'rt') delete rt.dots[pid];
      each(game, (ws) => { if (ws.pid === pid) { ws.role = 'spectator'; send(ws, { type: 'role', role: 'spectator' }); if (game === 'turn') sendTurn(ws); } });
    },
    drop() { for (const ws of sockets) ws.terminate(); },
    turnInfo: () => ({ turn: turn.seats[turn.turn] || null, deadline: turn.deadline }),
    state: () => ({ tick: rt.tick, turn: turnPublic() }),
  };
}
