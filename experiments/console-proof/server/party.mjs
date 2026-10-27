// The fixture Party server on the PARTY origin (AVR-762 experiment). Stands in for Party Core:
// device cookie identity, one Party, one location, seats, Party-issued game tickets, and a
// FIXTURE next-game suggestions list (nominate + named approvals). It is NOT a voting backend.
//
// Static:  /party/x/vanilla/*  the vanilla console     /party/x/svelte/*  the Svelte build
//          /party/x/shared/*   CSS both consoles share  /party/*           the real web/party (read-only)
//          /party/x/<fw>/layer is the console page served with the layer frame's frame-ancestors.
import http from 'node:http';
import net from 'node:net';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { CATALOG, COOKIE, GAME, GAME_PORT, PARTY, json, readJson, serveStatic, signTicket } from './shared.mjs';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const ROOTS = { vanilla: here('../web/party-x/vanilla/'), svelte: here('../svelte/dist/'), shared: here('../web/party-x/shared/') };
const REAL = here('../../../web/party/');
const CRLF = String.fromCharCode(13, 10);
const GAME_WEB = here('../web/game/'), VENDOR = here('../../../web/party/bridge/');

export function createPartyServer(game) {
  let state;
  function reset() {
    state = {
      members: new Map([['ana', { id: 'ana', name: 'Ana', avatar: 'gaze-03', host: true }], ['ben', { id: 'ben', name: 'Ben', avatar: 'gaze-07', host: false }]]),
      devices: new Map(),                       // cookie value -> member id
      seats: { rt: [], turn: [] },
      location: { at: 'game', game: 'rt' },
      expireNext: new Set(),
      suggestions: [
        { id: 's1', game: 'checkers', by: 'ana', at: 1, approvals: ['ana', 'ben'] },
        { id: 's2', game: 'bestguess', by: 'ben', at: 2, approvals: ['ben'] },
      ],
      version: 1,
    };
    game.seat('rt', []); game.seat('turn', []);
  }
  reset();

  const memberOf = (req) => {
    const m = /(?:^|;\s*)cp_device=([A-Za-z0-9_-]+)/.exec(req.headers.cookie || '');
    const id = m && state.devices.get(m[1]);
    return id ? state.members.get(id) : null;
  };
  const nameOf = (id) => (state.members.get(id) || { name: '?' }).name;
  const sortedSuggestions = () => state.suggestions.slice()
    .sort((a, b) => b.approvals.length - a.approvals.length || a.at - b.at)
    .map((s) => ({ id: s.id, game: s.game, by: nameOf(s.by), approvals: s.approvals.map(nameOf), count: s.approvals.length }));

  function view(me) {
    const loc = state.location;
    const role = state.seats[loc.game] && state.seats[loc.game].includes(me.id) ? 'player' : 'spectator';
    const attention = [];
    if (loc.game === 'turn' && role === 'player') {
      const t = game.turnInfo();
      if (t.turn === me.id) attention.push({ id: 'turn', kind: 'your_turn', game: 'turn', deadline: t.deadline });
    }
    // Typed notices only (kind + ids): the console words them; a game never supplies the text.
    const top = sortedSuggestions()[0];
    if (top) attention.push({ id: 'sugg-' + top.id, kind: 'top_suggestion', game: top.game, by: top.by });
    return {
      version: state.version, me: { ...me, me: true }, role, location: loc, attention, now: Date.now(),
      members: [...state.members.values()].map((m) => ({ ...m, me: m.id === me.id })),
    };
  }

  // A browser-marked cross-origin request never acts as the member (like Party Core's Sec-Fetch-Site refusal).
  const sameOrigin = (req) => {
    const site = req.headers['sec-fetch-site'];
    if (site && site !== 'same-origin' && site !== 'none') return false;
    return !req.headers.origin || req.headers.origin === PARTY;
  };

  const csp = (frameAncestors) => ({
    'content-security-policy': `default-src 'self'; img-src 'self' data:; connect-src 'self'; style-src 'self'; frame-src ${GAME}; form-action 'self'; frame-ancestors ${frameAncestors}`,
    'x-content-type-options': 'nosniff',
  });

  async function api(req, res, url) {
    const path = url.pathname;
    if (path.startsWith('/test/')) {
      if (req.headers['x-cp-test'] !== '1') return json(res, 403, { error: 'forbidden' });
      const body = req.method === 'POST' ? await readJson(req) : {};
      const byName = (n) => [...state.members.values()].find((m) => m.name === n);
      if (path === '/test/reset') { reset(); return json(res, 200, { ok: true }); }
      if (path === '/test/location') { state.location = { at: 'game', game: body.game }; state.version += 1; return json(res, 200, { ok: true }); }
      if (path === '/test/seat-remove') {
        const m = byName(body.name); if (!m) return json(res, 404, {});
        state.seats[body.game] = state.seats[body.game].filter((p) => p !== m.id); state.version += 1;
        game.revoke(m.id, body.game); return json(res, 200, { ok: true });
      }
      if (path === '/test/expire-next') { const m = byName(body.name); if (m) state.expireNext.add(m.id); return json(res, 200, { ok: Boolean(m) }); }
      if (path === '/test/drop') { game.drop(); return json(res, 200, { ok: true }); }
      if (path === '/test/stats' || path === '/test/stats/') return json(res, 200, { game: game.stats, state: game.state(), seats: state.seats, version: state.version, location: state.location });
      if (path === '/test/ticket-for') {   // a ticket for another member, for the "never another's seat" test
        const m = byName(body.name); return json(res, 200, { ticket: signTicket({ pid: m.id, name: m.name, game: body.game, role: 'player', exp: Date.now() + 60_000 }) });
      }
      return json(res, 404, {});
    }
    if (path === '/api/dev-join' && req.method === 'GET') {        // a phone joins (the fixture's stand-in for Party Home's join)
      const name = String(url.searchParams.get('name') || '').slice(0, 20) || 'Guest';
      const seat = url.searchParams.get('seat');
      const id = 'p-' + randomBytes(4).toString('hex'), dev = randomBytes(18).toString('base64url');
      state.members.set(id, { id, name, avatar: 'gaze-1' + (state.members.size % 9), host: false });
      state.devices.set(dev, id);
      if (seat === 'rt' || seat === 'turn') { state.seats[seat].push(id); game.seat(seat, state.seats[seat]); }
      state.version += 1;
      return json(res, 200, { ok: true, id }, { 'set-cookie': `${COOKIE}=${dev}; HttpOnly; SameSite=Lax; Path=/` });
    }
    const me = memberOf(req);
    if (!me) return json(res, 401, { error: 'not_member' });
    if (req.method === 'POST' && !sameOrigin(req)) return json(res, 403, { error: 'cross_origin' });
    if (path === '/api/view') return json(res, 200, view(me));
    if (path === '/api/catalog') return json(res, 200, { games: CATALOG });
    if (path === '/api/ticket' && req.method === 'POST') {
      const body = await readJson(req);
      if (!['rt', 'turn'].includes(body.game)) return json(res, 400, { error: 'bad_game' });
      const role = state.seats[body.game].includes(me.id) ? 'player' : 'spectator';
      const expired = state.expireNext.delete(me.id);
      return json(res, 200, { ticket: signTicket({ pid: me.id, name: me.name, game: body.game, role, exp: Date.now() + (expired ? -1000 : 60_000) }), role });
    }
    if (path === '/api/suggestions' && req.method === 'GET') return json(res, 200, { fixture: true, suggestions: sortedSuggestions() });
    if (path === '/api/suggestions/nominate' && req.method === 'POST') {
      const body = await readJson(req);
      if (!CATALOG.some((g) => g.id === body.game)) return json(res, 400, { error: 'bad_game' });
      if (!state.suggestions.some((s) => s.game === body.game)) {
        state.suggestions.push({ id: 's' + (state.suggestions.length + 1), game: body.game, by: me.id, at: Date.now(), approvals: [me.id] });
      }
      return json(res, 200, { fixture: true, suggestions: sortedSuggestions() });
    }
    if (path === '/api/suggestions/approve' && req.method === 'POST') {
      const body = await readJson(req);
      const s = state.suggestions.find((x) => x.id === body.id);
      if (!s) return json(res, 404, { error: 'gone' });
      s.approvals = s.approvals.includes(me.id) ? s.approvals.filter((p) => p !== me.id) : [...s.approvals, me.id];
      return json(res, 200, { fixture: true, suggestions: sortedSuggestions() });
    }
    return json(res, 404, { error: 'not_found' });
  }

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, PARTY);
    try {
      if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/test/')) return await api(req, res, url);
      if (url.pathname.startsWith('/g/')) {         // Limited Mode stand-in: the game's files on the Party origin
        const rest = url.pathname.slice(3), limitedCsp = { ...csp("'none'"), 'content-security-policy': csp("'none'")['content-security-policy'].replace(`frame-src ${GAME}`, "frame-src 'self'") };
        if (rest.startsWith('vendor/') ? await serveStatic(res, VENDOR, rest.slice(7), limitedCsp) : await serveStatic(res, GAME_WEB, rest, limitedCsp)) return;
      }
      const m = /^\/party\/x\/(vanilla|svelte|shared)\/(.*)$/.exec(url.pathname);
      if (m) {
        const [, which, rest] = m;
        if (rest === 'layer') { if (await serveStatic(res, ROOTS[which], 'index.html', csp(`${PARTY} ${GAME}`))) return; }
        else if (await serveStatic(res, ROOTS[which], rest || 'index.html', csp("'none'"))) return;
      } else if (url.pathname.startsWith('/party/') && await serveStatic(res, REAL, url.pathname.slice('/party/'.length), csp("'none'"))) return;
      json(res, 404, { error: 'not_found' });
    } catch (err) { json(res, 500, { error: String(err && err.message) }); }
  });
  // Limited Mode: /g/ws/* goes to the game server with the Cookie header removed (nginx does the same, AVR-314).
  server.on('upgrade', (req, sock, head) => {
    if (!req.url.startsWith('/g/ws/')) { sock.destroy(); return; }
    const up = net.connect(GAME_PORT, '127.0.0.1', () => {
      const lines = [`GET ${req.url.slice(2)} HTTP/1.1`];
      for (let i = 0; i < req.rawHeaders.length; i += 2) if (req.rawHeaders[i].toLowerCase() !== 'cookie') lines.push(`${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}`);
      up.write(lines.join(CRLF) + CRLF + CRLF); up.write(head); up.pipe(sock); sock.pipe(up);
    });
    up.on('error', () => sock.destroy()); sock.on('error', () => up.destroy());
  });
  return { server, reset };
}
