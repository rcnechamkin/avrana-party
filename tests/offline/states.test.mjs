// Tier 1 (node --test): the states the shell says out loud (web/party/lib/states.js) and the part
// of the Party client that feeds them. This phone losing the Party box, the Host going away and
// hosting passing on, and trouble on the box that changes what can be played.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { LOST_AFTER_MS, awayHost, briefLine, fineLine, hostNote, hostPassed, linkState, linkWords, offLine, troubles } from '../../web/party/lib/states.js';
import { createPartyClient } from '../../web/party/lib/party-client.js';

const catalog = JSON.parse(readFileSync(new URL('../../web/party/catalog.json', import.meta.url)));
const source = readFileSync(new URL('../../web/party/lib/states.js', import.meta.url), 'utf8');

const member = (id, name, { host = false, presence = 'here' } = {}) => ({ id, name, presence, host });
function view({ members, me = 'b', party = 'party-1', state = 'lobby' }) {
  const mine = members.find((m) => m.id === me) || null;
  return { party, version: 1, state, members, games: ['bluff'], me: mine ? { id: mine.id, name: mine.name, host: mine.host } : null };
}

test('reconnecting is said at once and "lost" after about ten seconds; an answer ends both', () => {
  assert.equal(LOST_AFTER_MS, 10000);                    // the owner, 2026-10-06
  assert.equal(linkState(null, 5000), 'ok');
  assert.equal(linkState(undefined, 5000), 'ok');
  assert.equal(linkState(1000, 1000), 'reconnecting');
  assert.equal(linkState(1000, 1000 + LOST_AFTER_MS - 1), 'reconnecting');
  assert.equal(linkState(1000, 1000 + LOST_AFTER_MS), 'lost');
  assert.equal(linkState(0, LOST_AFTER_MS), 'lost');     // a start at time zero is still a start
});

test('the words for a phone that cannot reach Party Core', () => {
  assert.equal(linkWords({ link: 'ok' }), null);
  assert.equal(linkWords(), null);
  assert.deepEqual(linkWords({ link: 'reconnecting' }), { title: '', text: 'Reconnecting. What you see may be out of date.', retry: false });
  assert.equal(linkWords({ link: 'reconnecting', brief: true }).text, 'Reconnecting. Your answer stays as it is for now.');
  assert.deepEqual(linkWords({ link: 'lost' }),
    { title: 'This phone lost the Party box', text: 'Check it’s on the Avrana Party Wi-Fi.', retry: true });
  // the Host's own phone: the role passes on by Party Core's rule; no time is promised
  assert.equal(linkWords({ link: 'lost', host: true }).text, 'Check it’s on the Avrana Party Wi-Fi. Hosting passes on if it stays away.');
  // the box answers, only not the Party: the Wi-Fi is not blamed
  const restarting = linkWords({ link: 'lost', answered: true });
  assert.equal(restarting.title, 'The Party box isn’t answering');
  assert.doesNotMatch(restarting.text, /Wi-Fi/);
  assert.equal(restarting.retry, true);
});

test('the Host is away only when Party Core says so: never this phone, never a Host in the round', () => {
  const dana = (presence) => member('a', 'Dana', { host: true, presence });
  assert.equal(awayHost(view({ members: [dana('away'), member('b', 'Sam')] })).name, 'Dana');
  assert.equal(awayHost(view({ members: [dana('here'), member('b', 'Sam')] })), null);
  // a Host who holds a place in the round that is on is "playing": the role does not move
  assert.equal(awayHost(view({ members: [dana('playing'), member('b', 'Sam')], state: 'active' })), null);
  assert.equal(awayHost(view({ members: [dana('away'), member('b', 'Sam')], me: 'a' })), null);       // this phone is asking: it is here
  assert.equal(awayHost(view({ members: [member('a', 'Dana'), member('b', 'Sam')] })), null);         // nobody hosts
  assert.equal(awayHost(view({ members: [dana('away')], me: null })).name, 'Dana');                   // a phone with no name sees it too
  for (const odd of [null, undefined, {}, { members: 'x' }]) assert.equal(awayHost(odd), null);
});

test('hosting passed on: only between two views of one Party, and "away" only when it was said', () => {
  const before = view({ members: [member('a', 'Dana', { host: true, presence: 'away' }), member('b', 'Sam'), member('c', 'Priya')] });
  const after = view({ members: [member('a', 'Dana', { presence: 'away' }), member('b', 'Sam', { host: true }), member('c', 'Priya')] });
  assert.deepEqual(hostPassed(before, after), { to: 'Sam', from: 'Dana', mine: true, wasAway: true });
  assert.deepEqual(hostPassed(before, { ...after, me: { id: 'c', name: 'Priya', host: false } }), { to: 'Sam', from: 'Dana', mine: false, wasAway: true });
  // the old Host left, or handed it over: nobody "has been away"
  const here = view({ members: [member('a', 'Dana', { host: true }), member('b', 'Sam')] });
  const left = view({ members: [member('b', 'Sam', { host: true })] });
  assert.equal(hostPassed(here, left).wasAway, false);
  assert.equal(hostPassed(before, before), null);                         // nothing changed
  assert.equal(hostPassed(null, after), null);                            // a phone that was not watching is told nothing
  assert.equal(hostPassed(before, { ...after, party: 'party-2' }), null); // another Party is not a hand-over
  assert.equal(hostPassed(before, view({ members: [member('b', 'Sam')] })), null);          // vacant: said by its own line
  assert.equal(hostPassed(view({ members: [member('b', 'Sam')] }), after), null);
});

test('what Home and the Party page say about the Host', () => {
  assert.equal(hostNote(), null);
  assert.equal(hostNote({ away: null, passed: null }), null);
  const away = hostNote({ away: { name: 'Dana' } });
  assert.deepEqual([away.kind, away.icon, away.mine], ['away', 'moon-star', false]);
  assert.equal(away.text, 'Hosting passes to someone here if Dana isn’t back soon.');
  assert.doesNotMatch(away.text, /\d/);                                   // no countdown: the view carries none
  const mine = hostNote({ passed: { to: 'Sam', from: 'Dana', mine: true, wasAway: true } });
  assert.deepEqual([mine.kind, mine.mine, mine.title], ['passed', true, 'You’re hosting now']);
  assert.equal(mine.text, 'Dana has been away, so you pick what the Party plays.');
  assert.equal(hostNote({ passed: { to: 'Sam', from: 'Dana', mine: true, wasAway: false } }).text, 'You pick what the Party plays.');
  assert.equal(hostNote({ passed: { to: 'Sam', from: 'Dana', mine: false, wasAway: true } }).text, 'Sam is hosting now. Dana has been away.');
  assert.equal(hostNote({ passed: { to: 'Sam', from: 'Dana', mine: false, wasAway: false } }).text, 'Sam is hosting now.');
  // the new Host is away too: what happens next matters more than what happened
  assert.equal(hostNote({ away: { name: 'Sam' }, passed: { to: 'Sam', from: 'Dana', mine: false, wasAway: true } }).kind, 'away');
});

test('the briefing’s line: Party Core’s sentence for the Host, who everyone else waits for', () => {
  const panel = (over = {}) => ({ game: 'bluff', host: false, hostName: 'Dana', starting: false, blocker: null, ...over });
  assert.equal(briefLine(null), '');
  assert.equal(briefLine(panel({ starting: true, host: true, blocker: 'x' })), 'Starting…');
  assert.equal(briefLine(panel({ host: true, blocker: 'Waiting for Sam to choose.' })), 'Waiting for Sam to choose.');
  assert.equal(briefLine(panel({ host: true })), '');
  assert.equal(briefLine(panel()), 'Waiting for Dana to start');
  assert.equal(briefLine(panel({ hostName: null })), 'Nobody is hosting right now.');
  assert.equal(briefLine(panel(), { away: { name: 'Dana' } }),
    'Dana, the Host, is away, so the game can’t start yet. Hosting passes to someone here if Dana isn’t back soon.');
  const passed = { to: 'Sam', from: 'Dana', mine: false, wasAway: true };
  assert.equal(briefLine(panel({ hostName: 'Sam' }), { passed }), 'Sam is hosting now. Waiting for Sam to start');
  assert.equal(briefLine(panel({ host: true, hostName: 'Sam', blocker: 'Waiting for Dana to choose.' }), { passed: { ...passed, mine: true } }),
    'You’re hosting now. Waiting for Dana to choose.');
  assert.equal(briefLine(panel({ host: true, hostName: 'Sam' }), { passed: { ...passed, mine: true } }), 'You’re hosting now.');
  // the Host never reads that they themselves are away
  assert.equal(briefLine(panel({ host: true, blocker: 'B' }), { away: { name: 'Dana' } }), 'B');
});

test('trouble on the Party box, from the status document’s fields and the catalog’s titles', () => {
  const games = catalog.games;
  const ok = { arcade: { ok: true, emulator_running: true, error: null }, games_provider: { ok: true, compatible: true },
    summary: { state: 'degraded', reasons: ['arcade unreachable'] } };
  assert.deepEqual(troubles(ok, games), []);              // the operator's sentences are never read
  for (const odd of [null, undefined, 'x', {}]) assert.deepEqual(troubles(odd, games), []);
  const arcade = troubles({ ...ok, arcade: { ok: false } }, games);
  assert.equal(arcade.length, 1);
  assert.deepEqual([arcade[0].id, arcade[0].title, arcade[0].text], ['arcade', 'Arcade games are off right now', 'Card and party games play as usual.']);
  assert.equal(arcade[0].detail, 'The arcade part of the Party box isn’t answering. Gauntlet II can’t be played. Card and party games are not affected.');
  for (const a of [{ ok: true, emulator_running: false }, { ok: true, emulator_running: true, error: 'no core' }])
    assert.equal(troubles({ ...ok, arcade: a }, games)[0].id, 'arcade');
  const cards = troubles({ ...ok, games_provider: { ok: false } }, games);
  assert.deepEqual([cards[0].id, cards[0].title, cards[0].text], ['cards', 'Card and party games are off right now', 'Arcade games play as usual.']);
  assert.match(cards[0].detail, /BLUFF and EXPO can’t be played\. Arcade games are not affected\.$/);
  const both = troubles({ arcade: { ok: false }, games_provider: { ok: false } }, games);
  assert.deepEqual([both.length, both[0].id, both[0].title, both[0].text],
    [1, 'games', 'Some games are off right now', 'Other games play as usual.']);
  assert.match(both[0].detail, /BLUFF, EXPO and Gauntlet II can’t be played\.$/);
  // a part with nothing installed cannot be "off"; a title that is not installed is never named
  assert.deepEqual(troubles({ ...ok, arcade: { ok: false } }, games.filter((g) => g.legacySlug)), []);
  assert.equal(troubles({ ...ok, arcade: { ok: false } }, games.filter((g) => g.provider === 'arcade'))[0].text, '');
  // Native processes do not share either provider's failure; no title-specific exception.
  const independent = [{ id: 'new-native', name: 'New native', provider: 'native', installed: true, entry: '/games/new-native/' }];
  assert.deepEqual(troubles({ arcade: { ok: false }, games_provider: { ok: false } }, independent), []);
  assert.doesNotMatch(JSON.stringify([arcade, cards, both]), /Checkers/);
  const legacyOnly = troubles({ arcade: { ok: false }, games_provider: { ok: false } },
    games.filter((g) => g.provider === 'arcade' || g.provider === 'lan-games'));
  assert.equal(legacyOnly[0].title, 'Games are off right now');
  assert.equal(legacyOnly[0].text, 'No game can be started.');
  assert.doesNotMatch(JSON.stringify([arcade, cards, both]), /Worms|Bomberman/);
  // a compatible-but-older provider and a certificate are not this notice's business
  assert.deepEqual(troubles({ ...ok, games_provider: { ok: true, compatible: false }, certificate: { status: 'expired' } }, games), []);
});

test('System’s line for everyone else, and the one quiet line when all is well', () => {
  assert.equal(offLine([], 3), null);
  assert.deepEqual(offLine(['Gauntlet II'], 2), { title: 'Gauntlet II is off for now', text: 'Every other game plays as usual.' });
  assert.deepEqual(offLine(['Gauntlet II'], 1), { title: 'Gauntlet II is off for now', text: 'The other game plays as usual.' });
  assert.deepEqual(offLine(['BLUFF', 'EXPO'], 0), { title: 'BLUFF and EXPO are off for now', text: '' });
  assert.deepEqual(fineLine(true), { title: 'Everything’s working', text: 'The Party box and this phone are fine.' });
  assert.equal(fineLine(false).title, 'The Party box is working');
});

test('guest words only in everything this module says', () => {
  const said = source.split('\n').filter((line) => !/^\s*(\/\/|\/?\*)/.test(line)).join('\n');
  const strings = [...said.matchAll(/'([^'\n]*)'|`([^`]*)`/g)].map((m) => m[1] || m[2] || '').filter((s) => /[a-z] [a-z]/i.test(s));
  assert.ok(strings.length > 15);
  for (const s of strings) assert.doesNotMatch(s, /\b(seat|session|runtime|server|websocket|presence|manifest|launch(ing)?|backend|token|slot|provider|emulator|certificate)\b/i, s);
});

// ---- the client: every try that ends is heard, and a wait between tries can be cut short --------------

const good = { party: 'p', version: 1, members: [], games: [] };
function timers() {
  const due = [];
  return { due, schedule: (fn, ms) => { const t = { fn, ms }; due.push(t); return t; },
    cancel: (t) => { const i = due.indexOf(t); if (i >= 0) due.splice(i, 1); } };
}
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0)); };

test('the client reports each try: failed (offline, or answered with no view), then back', async () => {
  const answers = [() => { throw new TypeError('offline'); }, () => ({ ok: false, status: 502, json: async () => null }),
    () => ({ ok: true, status: 200, json: async () => ({ hello: 1 }) }), () => ({ ok: true, status: 200, json: async () => ({ ...good, version: 2 }) })];
  let n = 0;
  const hang = new Promise(() => {});
  const t = timers(), heard = [], asked = [];
  const client = createPartyClient({ fetch: async (url) => { asked.push(url); return n < answers.length ? answers[n++]() : hang; },
    onView() {}, onLink: (l) => heard.push(l), ...t });
  client.start(good);
  for (let i = 0; i < 3; i++) {
    await settle();
    const wait = t.due.find((d) => d.ms <= 5000);          // the pause after a failed try (the other timer is the poll's own limit)
    assert.ok(wait, `a pause after failure ${i + 1}`);
    t.cancel(wait); wait.fn();
  }
  await settle();
  assert.deepEqual(heard, [{ ok: false, answered: false }, { ok: false, answered: true }, { ok: false, answered: true }, { ok: true, answered: true }]);
  assert.equal(client.view().version, 2);
  // a try after a failed one asks for what is true now; only a healthy poll waits for a change
  assert.deepEqual(asked.map((url) => /wait=(\d+)/.exec(url)[1]), ['20', '0', '0', '0', '20']);
  client.stop();
});

test('poke ends the pause after a failed try, so "Try again" and a returning network ask at once', async () => {
  let n = 0;
  const hang = new Promise(() => {});
  const t = timers(), heard = [];
  const client = createPartyClient({ fetch: async () => { n++; if (n === 1) throw new TypeError('offline'); return n === 2 ? { ok: true, status: 200, json: async () => ({ ...good, version: 3 }) } : hang; },
    onView() {}, onLink: (l) => heard.push(l), ...t });
  client.start(good);
  await settle();
  assert.equal(n, 1);
  assert.equal(t.due.filter((d) => d.ms <= 5000).length, 1);          // waiting to try again
  client.poke();
  await settle();
  assert.equal(n >= 2, true);                                          // asked again without the wait running out
  assert.equal(t.due.filter((d) => d.ms <= 5000).length, 0);          // and the wait was put away, not left to fire later
  assert.deepEqual(heard.slice(0, 2), [{ ok: false, answered: false }, { ok: true, answered: true }]);
  client.stop();
});

test('a poll this page cut short itself is not a failure', async () => {
  const t = timers(), heard = [];
  const fetch = (url, init = {}) => new Promise((resolve, reject) => init.signal?.addEventListener('abort', () => reject(new Error('aborted'))));
  const client = createPartyClient({ fetch, onView() {}, onLink: (l) => heard.push(l), ...t });
  client.start(good);
  await settle();
  client.poke();                                                       // after an action, or on wake
  await settle();
  assert.deepEqual(heard, []);
  client.stop();
});
