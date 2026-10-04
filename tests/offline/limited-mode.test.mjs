// Limited Mode in the shell (ADR 0012, AVR-225): the banner's words, per-seat limits and the
// HTTP doorway's decision. Pure modules; the browser run is tests/offline/limited.spec.ts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { FULL, LIMITED, blockedGames, limitedNotice, modeOf, seatChoice, seatLimits } from '../../web/party/lib/limited.js';
import { PROBE_MS, chooseMode, targets } from '../../web/party/lib/doorway.js';

const read = (path) => readFileSync(new URL('../../' + path, import.meta.url), 'utf8');
const catalog = JSON.parse(read('web/party/catalog.json'));

// A game as the catalog states one, with the device capabilities each role needs.
const game = (player, spectator = [], fallback = 'spectate') => ({
  id: 'g', name: 'Test Game', installed: true, entry: '/games/g/', fallback,
  presentations: [
    { id: 'play', method: 'browser_native', available: true, roles: ['player'], requires: { device: player }, optional: { device: ['wake_lock'] } },
    { id: 'watch', method: 'browser_native', available: true, roles: ['spectator'], requires: { device: spectator }, optional: { device: [] } },
  ],
});
// A phone on plain HTTP: no secure context, so no wake lock and no service worker either.
const HTTP_PHONE = { secure_context: 'no', wake_lock: 'no', service_worker: 'no', websocket: 'yes' };
const HTTPS_PHONE = { secure_context: 'yes', wake_lock: 'yes', service_worker: 'yes', websocket: 'yes' };

test('the mode is whatever Party Core says, and only "limited" is Limited Mode', () => {
  assert.equal(modeOf({ mode: 'limited' }), LIMITED);
  for (const view of [null, undefined, {}, { mode: 'full' }, { mode: 'LIMITED' }, { mode: true }, { mode: 'secure' }]) {
    assert.equal(modeOf(view), FULL, JSON.stringify(view));
  }
});

test('the banner says the connection is not private, what is missing here, and how it comes back', () => {
  const notice = limitedNotice({ caps: HTTP_PHONE, blocked: ['Gauntlet II'] });
  assert.equal(notice.title, 'Limited Mode');
  assert.match(notice.intro, /not private/);
  assert.match(notice.intro, /still work/);
  assert.equal(notice.missing.length, 3);
  assert.match(notice.missing[0], /screen may dim/);
  assert.match(notice.missing[1], /not saved on this phone/);
  assert.match(notice.missing[2], /^Gauntlet II: not playable on this phone/);
  assert.match(notice.restore, /renews its certificate/);
  const all = JSON.stringify(notice);
  assert.doesNotMatch(all, /\b(secure|padlock|encrypted|safe|https?|cookie|token|session|server)\b/i);   // no false comfort, no machinery
});

test('the banner lists only what is really missing on this phone', () => {
  assert.deepEqual(limitedNotice({ caps: HTTPS_PHONE }).missing, []);
  assert.equal(limitedNotice({ caps: { wake_lock: { status: 'yes' }, service_worker: { status: 'no' } } }).missing.length, 1);
  assert.match(limitedNotice({ caps: HTTP_PHONE, blocked: ['A', 'B', 'C', 'D'] }).missing[2], /^A, B, C and others:/);
  assert.equal(limitedNotice().missing.length, 2);                 // nothing known: assume the conveniences are absent
});

test('one seat, one decision: a game that needs a secure connection is watched from a Limited phone', () => {
  const needs = game(['websocket', 'secure_context'], ['websocket']);
  const labels = { secure_context: { label: 'a secure connection', missing: 'This page isn’t open on the secure Party address.' } };
  const limited = seatLimits(needs, HTTP_PHONE, labels);
  assert.deepEqual({ play: limited.play, watch: limited.watch }, { play: false, watch: true });
  assert.match(limited.why, /You can watch this one\.$/);
  assert.deepEqual(seatLimits(needs, HTTPS_PHONE, labels), { play: true, watch: true, why: '' });
  // a game that needs nothing secure is fully playable in Limited Mode, wake lock or not
  assert.deepEqual(seatLimits(game(['websocket']), HTTP_PHONE), { play: true, watch: true, why: '' });
});

test('a game that needs a secure connection even to watch is refused for that seat, with the reason', () => {
  const strict = game(['secure_context'], ['secure_context'], 'none');
  const limits = seatLimits(strict, HTTP_PHONE, { secure_context: { missing: 'Needs the secure Party address.' } });
  assert.deepEqual(limits, { play: false, watch: false, why: 'Needs the secure Party address.' });
});

test('blocked games are the installed ones this phone cannot play, by name', () => {
  const games = [game(['secure_context']), { ...game(['websocket']), name: 'Open Game' },
    { ...game(['secure_context']), name: 'Not Installed', installed: false }];
  assert.deepEqual(blockedGames(games, HTTP_PHONE), ['Test Game']);
  assert.deepEqual(blockedGames(games, HTTPS_PHONE), []);
});

test('every installed catalog game gets a decision in Limited Mode, and BLUFF stays playable', () => {
  for (const g of catalog.games.filter((x) => x.installed && x.entry)) {
    const limits = seatLimits(g, HTTP_PHONE, catalog.labels);
    assert.equal(typeof limits.play, 'boolean', g.id);
    if (!limits.play) assert.ok(limits.why, `${g.id} must say why`);
  }
  const bluff = catalog.games.find((g) => g.id === 'bluff');
  assert.equal(seatLimits(bluff, HTTP_PHONE, catalog.labels).play, true);
});

// ---- the doorway ---------------------------------------------------------------------------------

const timers = () => {
  const pending = [];
  return { pending, schedule: (fn, ms) => { pending.push({ fn, ms }); return pending.length; }, cancel: () => {} };
};

test('the doorway opens Full Mode when the secure origin answers, without reading the answer', async () => {
  const calls = [];
  const t = timers();
  const mode = await chooseMode({ full: 'https://party.avrana.net/party/', ...t,
    fetch: async (url, init) => { calls.push([url, init]); return { type: 'opaque', ok: false, status: 0 }; } });
  assert.equal(mode, 'full');
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'https://party.avrana.net/party/api/origin.json');
  assert.deepEqual({ mode: calls[0][1].mode, cache: calls[0][1].cache, credentials: calls[0][1].credentials },
    { mode: 'no-cors', cache: 'no-store', credentials: 'omit' });
  assert.equal(t.pending[0].ms, PROBE_MS);
});

test('the doorway opens Limited Mode when the secure origin fails: bad certificate, no name, no route', async () => {
  for (const failure of [new TypeError('Failed to fetch'), new Error('net::ERR_CERT_DATE_INVALID'), 'x']) {
    const mode = await chooseMode({ full: 'https://party.avrana.net/party/', ...timers(),
      fetch: async () => { throw failure; } });
    assert.equal(mode, 'limited');
  }
});

test('the doorway does not wait for ever: a request that hangs is Limited Mode', async () => {
  const t = timers();
  let aborted = false;
  const choosing = chooseMode({ full: 'https://party.avrana.net/party/', ...t,
    fetch: (url, init) => new Promise((resolve, reject) => {
      init.signal.addEventListener('abort', () => { aborted = true; reject(new Error('aborted')); });
    }) });
  t.pending[0].fn();                                  // the timeout fires
  assert.equal(await choosing, 'limited');
  assert.equal(aborted, true);
});

test('the doorway only sends a phone where its own page says, and only to the right schemes', () => {
  assert.deepEqual(targets({ full: 'https://party.avrana.net/party/', limited: 'http://10.42.0.1/party/' }),
    { full: 'https://party.avrana.net/party/', limited: 'http://10.42.0.1/party/' });
  assert.ok(targets({ full: 'http://127.0.0.1:8182/party/', limited: 'http://limited.avrana.test:8182/party/' }));
  for (const bad of [null, {}, { full: 'https://party.avrana.net/party/' },
    { full: 'http://party.avrana.net/party/', limited: 'http://10.42.0.1/party/' },       // Full Mode is never plain HTTP
    { full: 'https://party.avrana.net/party/', limited: 'https://10.42.0.1/party/' },     // Limited Mode is never HTTPS
    { full: 'javascript:alert(1)', limited: 'http://10.42.0.1/party/' },
    { full: 'https://party.avrana.net/party/', limited: 'javascript:alert(1)' },
    { full: '/party/', limited: '/party/' }]) {
    assert.equal(targets(bad), null, JSON.stringify(bad));
  }
});

test('the doorway page names the canonical origins and takes nothing from its address', () => {
  const html = read('web/party/doorway/index.html');
  assert.match(html, /data-full="https:\/\/party\.avrana\.net\/party\/"/);
  assert.match(html, /data-limited="http:\/\/10\.42\.0\.1\/party\/"/);      // ADR 0012 D1
  assert.match(html, /<noscript>/);
  const js = read('web/party/doorway/doorway.js') + read('web/party/lib/doorway.js');
  assert.doesNotMatch(js, /location\.(search|hash|href)|URLSearchParams|document\.referrer/);
});

test('the shell shows the banner only from Party Core’s word and never claims a padlock', () => {
  const html = read('web/party/index.html');
  assert.match(html, /<section id="limited" class="avrana-limited" hidden/);
  assert.match(html, /href="doorway\/">Check for the full version/);
  const app = read('web/party/app.js');
  assert.match(app, /state\.mode = modeOf\(partyView\)/);
  assert.match(app, /\$\('secure'\)\.hidden = !\(kind === 'ok' && window\.isSecureContext\)/);
  // the offline copy lists the module the page imports, and never the doorway (HTTP only)
  const sw = read('web/party/sw.js');
  assert.match(sw, /'lib\/limited\.js'/);
  assert.doesNotMatch(sw, /doorway/);
});

test('seat gating asks the mode first: Full Mode is never gated, whatever the phone reports', () => {
  const needs = game(['secure_context']);
  const open = { play: true, watch: true, why: '' };
  // the same phone, the same game, the same missing capability: only the mode differs
  assert.equal(seatLimits(needs, HTTP_PHONE).play, false);
  assert.equal(seatChoice(LIMITED, needs, HTTP_PHONE).play, false);
  assert.deepEqual(seatChoice(LIMITED, needs, HTTP_PHONE), seatLimits(needs, HTTP_PHONE));
  assert.deepEqual(seatChoice(FULL, needs, HTTP_PHONE), open);
  // anything that is not Party Core saying "limited" is Full Mode
  for (const mode of [undefined, null, '', 'Limited', 'http', modeOf({}), modeOf({ mode: 'half' })]) {
    assert.deepEqual(seatChoice(mode, needs, HTTP_PHONE), open, String(mode));
  }
  assert.deepEqual(seatChoice(FULL, needs, {}), open);            // no capability report yet
  assert.deepEqual(seatChoice(modeOf({ mode: 'limited' }), needs, HTTP_PHONE), seatLimits(needs, HTTP_PHONE));
});
