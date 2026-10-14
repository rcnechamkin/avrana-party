// The Node fixture game of AVR-68: a TEST FIXTURE, not an SDK and not a game anyone plays.
//
// It is the Hello Party reference game (Games repository) again, in one ES module, so that the
// existing proof driver can play it: seats from the launch roster, one secret word per seat, a
// shared greeting board, one hello per seat, a cooperative result. The Party session protocol
// (avrana.party-session/v0) and the result envelope (avrana.game-result/v1) are written out here
// with node:crypto, on purpose minimal: the shared JavaScript helper belongs to another lane, and
// the reference implementation is avrana/party/protocol.py. JSON.parse cannot refuse a duplicate
// key, which the Python kit does; a real game should.
//
// Routes under /games/<id>/, as avrana_gamekit serves them:
//   POST avrana/session/v0/launch | end  {"message"}   Party Core only (no proxy header at all)
//   GET  api/party                       {"partyOrigin"}
//   POST api/redeem {"ticket"}           -> {"ok","token","role","view"}
//   POST api/poll   {"token","since"}    -> {"ok","view"}   long poll
//   POST api/greet  {"token","text"}     -> {"ok","view"} | 409 {"error","message","view"}
//   GET  <the page>
import { createHash, createHmac, randomBytes, randomInt, timingSafeEqual } from 'node:crypto';

// A vendored dependency, resolved from the package's own node_modules (plain files, no install).
import { MAX_TEXT, WORDS } from 'avr-fixture-dep';

export const GAME = 'hellonode';
export const BUILD = 'hellonode-0.1.0';
export const BASE = `/games/${GAME}`;
export const ENDED_ROUTE = '/internal/party-session/v0/ended';

const VERSION = 'avrana.party-session/v0';
const RESULT_SCHEMA = 'avrana.game-result/v1';
const DATA_SCHEMA = 'hellonode.result/v1';
const PREFIX = 'aps0';
const MESSAGE_TTL = 30;
const CLOCK_SKEW = 5;
const MAX_TOKEN = 8192;
const MAX_BODY = 16384;
const MAX_PLAYERS = 6;
const POLL_MS = 25000;
const MAX_POLLERS = 32;
const SID = /^session-[0-9a-f]{32}$/;
const PID = /^participant-[0-9a-f]{32}$/;
const NONCE = /^[0-9a-f]{24}$/;
const ROLES = ['player', 'spectator'];
const PROXY_HEADERS = ['x-forwarded-for', 'x-real-ip', 'forwarded'];
const SECURITY = { 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer' };

export class Invalid extends Error {}

// ---- the envelope: aps0.<b64url(canonical JSON)>.<b64url(HMAC-SHA256(key, "aps0." + part 1))> ----
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

const mac = (key, signed) => createHmac('sha256', key).update(signed, 'ascii').digest();
const seconds = () => Math.floor(Date.now() / 1000);

export function seal(key, payload) {
  const head = `${PREFIX}.${Buffer.from(canonical(payload), 'utf8').toString('base64url')}`;
  return `${head}.${mac(key, head).toString('base64url')}`;
}

export function unseal(key, token, typ, aud) {
  if (typeof token !== 'string' || token.length > MAX_TOKEN) throw new Invalid('shape');
  const parts = token.split('.');
  if (parts.length !== 3 || parts[0] !== PREFIX) throw new Invalid('shape');
  if (!/^[A-Za-z0-9_-]*$/.test(parts[1]) || !/^[A-Za-z0-9_-]*$/.test(parts[2])) throw new Invalid('encoding');
  const want = mac(key, `${parts[0]}.${parts[1]}`);
  const got = Buffer.from(parts[2], 'base64url');
  if (got.length !== want.length || !timingSafeEqual(got, want)) throw new Invalid('signature');
  let p;
  try {
    p = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'));
  } catch {
    throw new Invalid('payload');
  }
  if (p === null || typeof p !== 'object' || Array.isArray(p) || p.v !== VERSION) throw new Invalid('version');
  if (p.typ !== typ) throw new Invalid('type');
  if (p.aud !== aud) throw new Invalid('audience');
  const now = Date.now() / 1000;
  if (!Number.isInteger(p.iat) || !Number.isInteger(p.exp)) throw new Invalid('expired');
  if (p.iat > now + CLOCK_SKEW) throw new Invalid('clock');
  if (p.exp <= now) throw new Invalid('expired');
  if (typeof p.sid !== 'string' || !SID.test(p.sid)) throw new Invalid('session');
  return p;
}

// One game's side of the protocol: the running session, the replay guard, the spent tickets.
class Side {
  constructor(key) {
    this.key = key;
    this.sid = null;
    this.seen = new Map(); // nonce -> exp
    this.spent = new Map(); // sha256(ticket) -> exp
  }

  guard(p) {
    const now = Date.now() / 1000;
    for (const [nonce, exp] of this.seen) if (exp <= now) this.seen.delete(nonce);
    if (typeof p.nonce !== 'string' || !NONCE.test(p.nonce)) throw new Invalid('nonce');
    if (this.seen.has(p.nonce)) throw new Invalid('replay');
    this.seen.set(p.nonce, p.exp);
  }

  open(message, typ) {
    const p = unseal(this.key, message, typ, GAME);
    if (p.iss !== 'party') throw new Invalid('issuer');
    if (typ === 'launch') {
      const ok = Array.isArray(p.roster) && p.roster.every((r) => r !== null && typeof r === 'object'
        && Object.keys(r).sort().join() === 'name,participant,role' && ROLES.includes(r.role)
        && typeof r.participant === 'string' && PID.test(r.participant) && typeof r.name === 'string');
      if (!ok) throw new Invalid('roster');
    }
    this.guard(p);
    return p;
  }

  launch(message) {
    const p = this.open(message, 'launch');
    this.sid = p.sid;
    this.spent.clear();
    return p.roster;
  }

  end(message) {
    const p = this.open(message, 'end');
    if (p.sid !== this.sid) throw new Invalid('session');
    this.sid = null;
  }

  acknowledgeEnd(message, sid) {
    if (sid === null || unseal(this.key, message, 'end', GAME).sid !== sid) throw new Invalid('session');
    this.open(message, 'end');
  }

  redeem(ticket) {
    if (typeof ticket !== 'string' || !/^[\x20-\x7e]*$/.test(ticket)) throw new Invalid('shape');
    const p = unseal(this.key, ticket, 'ticket', GAME);
    if (p.iss !== 'party') throw new Invalid('issuer');
    if (this.sid === null || p.sid !== this.sid) throw new Invalid('session');
    if (!ROLES.includes(p.role) || typeof p.pid !== 'string' || !PID.test(p.pid)) throw new Invalid('participant');
    const now = Date.now() / 1000;
    for (const [digest, exp] of this.spent) if (exp <= now) this.spent.delete(digest);
    const digest = createHash('sha256').update(ticket, 'ascii').digest('hex');
    if (this.spent.has(digest)) throw new Invalid('replay');
    this.spent.set(digest, p.exp);
    const token = `avr-${createHmac('sha256', this.key).update(`game-token|${p.sid}|${p.pid}`, 'ascii').digest('hex').slice(0, 40)}`;
    return { token, role: p.role, participant: p.pid };
  }

  ended(outcome, result) {
    if (this.sid === null) throw new Invalid('session');
    const iat = seconds();
    const payload = { v: VERSION, typ: 'ended', iss: GAME, aud: 'party', sid: this.sid, iat, exp: iat + MESSAGE_TTL,
      outcome, nonce: randomBytes(12).toString('hex') };
    if (result) payload.result = result;
    this.sid = null;
    return seal(this.key, payload);
  }
}

// ---- the rules: Hello Party's ----------------------------------------------------------------
class Declined extends Error {}
class Conflict extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

class Session {
  constructor(roster) {
    const players = roster.filter((r) => r.role === 'player');
    if (players.length < 1 || players.length > MAX_PLAYERS || new Set(players.map((r) => r.participant)).size !== players.length) {
      throw new Declined(`Hello Node takes one to ${MAX_PLAYERS} different players.`);
    }
    const words = [...WORDS];
    this.seats = players.map((r) => ({ participant: r.participant, name: r.name, secret: words.splice(randomInt(words.length), 1)[0] }));
    this.board = [];
    this.v = 1;
    this.over = false;
  }

  seatOf(participant) {
    const index = this.seats.findIndex((s) => s.participant === participant);
    return index < 0 ? null : index;
  }

  view(participant) {
    const seat = participant === null ? null : this.seatOf(participant);
    return {
      v: this.v,
      seat,
      names: this.seats.map((s) => s.name),
      you: seat === null ? null : { name: this.seats[seat].name, secret: this.seats[seat].secret },
      board: this.board.map((e) => ({ ...e })),
      greeted: this.seats.map((_, i) => this.board.some((e) => e.seat === i)),
      over: this.over,
      result: this.over ? { greetings: this.board.length } : null,
    };
  }

  greet(participant, raw) {
    const seat = this.seatOf(participant);
    if (seat === null) throw new Conflict('watching', 'You are watching this game.');
    if (this.over) throw new Conflict('over', 'The game is over.');
    const text = raw.trim().split(/\s+/).join(' ');
    if (!text || text.length > MAX_TEXT || /[\u0000-\u001f\u007f-\u009f]/.test(text)) {
      throw new Conflict('bad_text', `Say hello in 1 to ${MAX_TEXT} characters.`);
    }
    if (this.board.some((e) => e.seat === seat)) throw new Conflict('already', 'You have already said hello.');
    this.board.push({ seat, by: this.seats[seat].name, text });
    this.over = this.board.length === this.seats.length;
    this.v += 1;
  }

  result() {
    return { schema: RESULT_SCHEMA, game: { id: GAME, build: BUILD }, mode: 'cooperative',
      standings: this.seats.map((s) => ({ participant: s.participant, standing: 'won' })),
      data_schema: DATA_SCHEMA, data: { greetings: this.board.length } };
  }
}

// ---- the app: who may hold a token, the long poll, the signed end ------------------------------
const json = (status, body) => ({ status, type: 'application/json', body: Buffer.from(JSON.stringify(body)) });
const NOT_FOUND = () => json(404, { ok: false, error: 'not_found' });
const BAD_JSON = () => json(400, { ok: false, error: 'bad_json' });
const NO_SEAT = () => json(403, { ok: false, message: 'There is no game for this seat.' });
const isString = (v) => typeof v === 'string';

function strict(raw, fields) {
  let body;
  try {
    body = JSON.parse(raw.toString('utf8'));
  } catch {
    return null;
  }
  if (body === null || typeof body !== 'object' || Array.isArray(body)) return null;
  const names = Object.keys(fields);
  if (Object.keys(body).length !== names.length || !names.every((k) => Object.hasOwn(body, k) && fields[k](body[k]))) return null;
  return body;
}

/** `report(message) -> Promise<{status, verdict}>` sends one signed `ended`; `log(level, text)` never gets a secret. */
export function createApp({ key, report, origin, page, log, idleMs = 60000, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) }) {
  const side = new Side(key);
  let session = null;
  let players = new Set();
  const tokens = new Map(); // token -> participant
  let finishedSid = null;
  let waiters = new Set();
  let reporting = 0;
  let idleSince = Date.now();
  let stopping = false;

  function forget() {
    session = null;
    finishedSid = null;
    players = new Set();
    tokens.clear();
    idleSince = Date.now();
    wake();
  }

  function wake() {
    const current = waiters;
    waiters = new Set();
    for (const resume of current) resume();
  }

  function who(token) {
    if (typeof token !== 'string' || !tokens.has(token)) return null;
    const participant = tokens.get(token);
    return players.has(participant) ? participant : 'watcher';
  }

  const viewFor = (s, w) => s.view(w === 'watcher' ? null : w);

  function control(rest, raw) {
    const body = strict(raw, { message: isString });
    if (!body) return BAD_JSON();
    if (stopping) return json(503, { ok: false, message: 'The game is restarting. Try again.' });
    try {
      if (rest === '/avrana/session/v0/launch') {
        const roster = side.launch(body.message);
        forget();
        try {
          session = new Session(roster);
        } catch (e) {
          if (!(e instanceof Declined)) throw e;
          side.sid = null;
          return json(409, { ok: false, message: e.message });
        }
        players = new Set(roster.filter((r) => r.role === 'player').map((r) => r.participant));
        log('INFO', `launched (${roster.length} on the roster)`);
        return json(200, { ok: true });
      }
      if (side.sid === null && finishedSid !== null) {
        side.acknowledgeEnd(body.message, finishedSid);
        log('INFO', 'released by the party after the result was reported');
      } else {
        side.end(body.message);
        log('INFO', 'ended by the party');
      }
      forget();
      return json(200, { ok: true });
    } catch (e) {
      if (!(e instanceof Invalid)) throw e;
      log('WARNING', `control message refused (${e.message})`);
      return json(403, { ok: false, message: 'Refused.', reason: e.message });
    }
  }

  function redeem(raw) {
    const body = strict(raw, { ticket: isString });
    if (!body) return BAD_JSON();
    let got;
    try {
      got = side.redeem(body.ticket);
    } catch (e) {
      if (!(e instanceof Invalid)) throw e;
      log('WARNING', `ticket refused (${e.message})`);
      return json(403, { ok: false, message: 'Refused.' });
    }
    if (session === null) return json(409, { ok: false, message: 'There is no game.' });
    const seated = players.has(got.participant);
    if ((got.role === 'player') !== seated) {
      log('WARNING', 'ticket refused (role disagrees with the roster)');
      return json(403, { ok: false, message: 'Refused.' });
    }
    tokens.set(got.token, got.participant);
    const role = seated ? 'player' : 'spectator';
    log('INFO', `ticket redeemed (${role})`);
    return json(200, { ok: true, token: got.token, role, view: session.view(seated ? got.participant : null) });
  }

  async function poll(raw) {
    const body = strict(raw, { token: isString, since: Number.isSafeInteger });
    if (!body) return BAD_JSON();
    const w = who(body.token);
    const mine = session;
    if (w === null || mine === null) return NO_SEAT();
    if (mine.v <= body.since && !stopping) {
      if (waiters.size >= MAX_POLLERS) return json(503, { ok: false, error: 'busy', message: 'Try again in a moment.' });
      const deadline = Date.now() + POLL_MS;
      while (session === mine && !stopping && mine.v <= body.since && Date.now() < deadline) {
        await new Promise((resume) => {
          const timer = setTimeout(() => { waiters.delete(done); resume(); }, Math.max(0, deadline - Date.now()));
          const done = () => { clearTimeout(timer); resume(); };
          waiters.add(done);
        });
      }
    }
    if (session !== mine) return NO_SEAT();
    return json(200, { ok: true, view: viewFor(mine, w) });
  }

  function greet(raw) {
    const body = strict(raw, { token: isString, text: (v) => isString(v) && v.length <= 200 });
    if (!body) return BAD_JSON();
    const w = who(body.token);
    if (w === null || session === null) return NO_SEAT();
    if (w === 'watcher') return json(403, { ok: false, error: 'watching', message: 'You are watching this game.' });
    try {
      session.greet(w, body.text);
    } catch (e) {
      if (!(e instanceof Conflict)) throw e;
      return json(409, { ok: false, error: e.code, message: e.message, view: session.view(w) });
    }
    if (session.over && finishedSid === null && side.sid !== null) {
      const sid = side.sid;
      const message = side.ended('completed', session.result());
      finishedSid = sid;
      idleSince = Date.now();
      log('INFO', 'finished');
      deliver(message);
    }
    wake();
    return json(200, { ok: true, view: session.view(w) });
  }

  async function deliver(message) {
    reporting += 1;
    try {
      let answer = await report(message);
      for (const delay of [1000, 2000, 4000]) {
        if (answer.status !== null && answer.status < 500) break;
        await sleep(delay);
        answer = await report(message);
      }
      if (answer.status === 200 && answer.verdict === 'accepted') log('INFO', 'the party accepted the result');
      else log('WARNING', `the party did not accept the report (status ${answer.status}, result ${answer.verdict ?? 'unknown'})`);
    } finally {
      reporting -= 1;
    }
  }

  /** {status, type, body, headers?} for one request. `headers` has lower-case names (Node's). */
  async function handle(method, path, headers, raw) {
    if (!path.startsWith(`${BASE}/`)) return NOT_FOUND();
    const rest = path.slice(BASE.length);
    if (rest.startsWith('/avrana/')) {
      const fromParty = !PROXY_HEADERS.some((name) => name in headers);
      if (!fromParty || method !== 'POST' || !['/avrana/session/v0/launch', '/avrana/session/v0/end'].includes(rest)) return NOT_FOUND();
      return control(rest, raw);
    }
    if (rest === '/api/party' && method === 'GET') return json(200, { partyOrigin: origin });
    if (rest === '/api/redeem' && method === 'POST') return redeem(raw);
    if (rest === '/api/poll' && method === 'POST') return poll(raw);
    if (rest === '/api/greet' && method === 'POST') return greet(raw);
    if (rest === '/' && method === 'GET') {
      return { status: 200, type: 'text/html; charset=utf-8', body: page,
        headers: { 'Content-Security-Policy': `default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-src ${origin || "'none'"}; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` } };
    }
    return NOT_FOUND();
  }

  /** A node:http request listener: bounded JSON bodies only, the same refusals as the Python kit. */
  function listener(req, res) {
    const answer = (reply) => {
      res.writeHead(reply.status, { 'Content-Type': reply.type, 'Content-Length': reply.body.length, ...SECURITY, ...(reply.headers || {}) });
      res.end(reply.body);
    };
    const refuse = (status, error) => {
      res.shouldKeepAlive = false;
      answer(json(status, { ok: false, error }));
      req.resume();
    };
    const path = (req.url || '').split('?', 1)[0];
    if (req.method === 'GET') {
      handle('GET', path, req.headers, Buffer.alloc(0)).then(answer, () => refuse(500, 'internal'));
      return;
    }
    if (req.method !== 'POST') {
      refuse(405, 'method');
      return;
    }
    const length = Number(req.headers['content-length']);
    if (!/^[0-9]+$/.test(req.headers['content-length'] || '') || length > MAX_BODY) {
      refuse(413, 'body_size');
      return;
    }
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size <= MAX_BODY) chunks.push(chunk);
    });
    req.on('error', () => res.destroy());
    req.on('end', () => {
      if (size > MAX_BODY) return refuse(413, 'body_size');
      if (!(req.headers['content-type'] || '').startsWith('application/json')) return refuse(415, 'json_only');
      return handle('POST', path, req.headers, Buffer.concat(chunks)).then(answer, () => refuse(500, 'internal'));
    });
  }

  /** True once: nothing authoritative has run for `idleMs` and no report is pending. */
  function claimIdleStop() {
    if (side.sid !== null || reporting > 0 || Date.now() - idleSince < idleMs) return false;
    stopping = true;
    wake();
    return true;
  }

  function close() {
    stopping = true;
    wake();
  }

  return { handle, listener, claimIdleStop, close };
}
