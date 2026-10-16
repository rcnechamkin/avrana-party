// The Party room's client (web/party/lib/party-chat.js, AVR-54): merge by seq, unread, reconnect
// catch-up, the gap, a new Party, membership loss, sends and their retry. Pure: a fake fetch.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPartyChat, length, merge, readLine, systemText, unread } from '../../web/party/lib/party-chat.js';

const line = (seq, from = 'member-b', text = `m${seq}`, extra = {}) =>
  ({ seq, kind: 'member', scope: 'party', from, name: from === 'member-a' ? 'Ana' : 'Ben', avatar: null, text, age_ms: 0, ...extra });
const sys = (seq, event, extra = {}) =>
  ({ seq, kind: 'system', scope: 'party', from: 'member-b', name: 'Ben', avatar: null, event, age_ms: 0, ...extra });

/** A fake Party Core: answers queued for GET /messages, a handler for POST. */
function fixture({ storage = null } = {}) {
  const gets = [], posts = [], answers = [], timers = new Map(), changes = [];
  let n = 0, onPost = () => ({ status: 200, body: {} });
  const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
  const fetch = async (url, init = {}) => {
    if (init.method === 'POST') {
      const body = JSON.parse(init.body);
      posts.push(body);
      const r = onPost(body);
      if (r === 'offline') throw new TypeError('offline');
      return json(r.status, r.body);
    }
    gets.push(url);
    const next = answers.shift();
    if (!next) return new Promise((_, reject) => {      // held: nothing new, until aborted
      if (init.signal) init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    });
    if (next === 'offline') throw new TypeError('offline');
    return json(next.status || 200, next.body);
  };
  const chat = createPartyChat({ fetch, base: '/party/api/', storage, onChange: (s) => changes.push(s),
    schedule: (fn, ms) => { const id = ++n; timers.set(id, { fn: () => { timers.delete(id); fn(); }, ms }); return id; },
    cancel: (id) => timers.delete(id), newId: () => `id${posts.length + 1}` });
  const settle = () => new Promise((r) => setTimeout(r, 0));
  const fire = (ms) => { for (const t of [...timers.values()]) if (t.ms === ms) t.fn(); };
  return { chat, gets, posts, answers, changes, settle, fire, setPost: (f) => { onPost = f; },
    room: (party, lines, first, last, retry = 0) => ({ body: { party, first: first ?? (lines[0]?.seq || 0), last: last ?? (lines.at(-1)?.seq || 0), messages: lines, retry_ms: retry } }) };
}

test('reads the named Party from 0, then long-polls from the cursor', async () => {
  const f = fixture();
  f.answers.push(f.room('party-1', [line(1), sys(2, 'joined')]));
  f.chat.open('party-1', 'member-a');
  await f.settle(); await f.settle();
  assert.match(f.gets[0], /messages\?party=party-1&after=0&wait=0$/);
  assert.match(f.gets[1], /after=2&wait=20$/);
  const s = f.chat.state();
  assert.equal(s.status, 'connected');
  assert.deepEqual(s.messages.map((m) => m.seq), [1, 2]);
  f.chat.close();
});

test('a line is never doubled: a repeated answer, the own echo and a reconnect merge by seq', async () => {
  const f = fixture();
  f.answers.push(f.room('party-1', [line(1)]));
  f.chat.open('party-1', 'member-a');
  await f.settle(); await f.settle();
  f.setPost((b) => ({ status: 200, body: { party: 'party-1', message: line(2, 'member-a', b.text) } }));
  assert.deepEqual(await f.chat.send('  hello  '), { ok: true });
  assert.deepEqual(f.posts[0], { party: 'party-1', text: 'hello', client_id: 'id1' });
  // the poke ends the held poll; the next answer carries the same line again
  f.answers.push(f.room('party-1', [line(2, 'member-a', 'hello')]), f.room('party-1', [line(1), line(2, 'member-a', 'hello')], 1, 2));
  await f.settle(); await f.settle(); await f.settle();
  assert.deepEqual(f.chat.state().messages.map((m) => m.seq), [1, 2]);
  f.chat.close();
});

test('unread counts other people only, and only above what an open drawer has shown', async () => {
  const f = fixture();
  f.answers.push(f.room('party-1', [line(1), line(2, 'member-a'), sys(3, 'joined'), line(4)]));
  f.chat.open('party-1', 'member-a');
  await f.settle(); await f.settle();
  assert.equal(f.chat.state().unread, 2);
  f.chat.markSeen();
  assert.equal(f.chat.state().unread, 0);
  f.chat.close();
});

test('what was shown is kept for the tab, per Party: a reload does not bring old lines back as new', async () => {
  const kept = new Map();
  const storage = { getItem: (k) => kept.get(k) ?? null, setItem: (k, v) => kept.set(k, v) };
  let f = fixture({ storage });
  f.answers.push(f.room('party-1', [line(1), line(2)]));
  f.chat.open('party-1', 'member-a'); await f.settle(); await f.settle();
  f.chat.markSeen(); f.chat.close();
  f = fixture({ storage });
  f.answers.push(f.room('party-1', [line(1), line(2), line(3)]));
  f.chat.open('party-1', 'member-a'); await f.settle(); await f.settle();
  assert.equal(f.chat.state().unread, 1);
  f.chat.close();
  f = fixture({ storage });
  f.answers.push(f.room('party-2', [line(1)]));
  f.chat.open('party-2', 'member-a'); await f.settle(); await f.settle();
  assert.equal(f.chat.state().unread, 1, 'another Party starts its own count');
  f.chat.close();
});

test('away longer than the room holds: the gap is said, not hidden', async () => {
  const f = fixture();
  f.answers.push(f.room('party-1', [line(5)]), 'offline');
  f.chat.open('party-1', 'member-a'); await f.settle(); await f.settle(); await f.settle();
  assert.equal(f.chat.state().status, 'unavailable');
  f.answers.push(f.room('party-1', [line(90), line(91)], 90, 91));
  f.fire(1000); await f.settle(); await f.settle();
  const s = f.chat.state();
  assert.equal(s.status, 'connected');
  assert.equal(s.gap, true);
  assert.deepEqual(s.messages.map((m) => m.seq), [5, 90, 91]);
  f.chat.close();
});

test('a new Party (it ended, Core restarted) empties the list before anything of it is shown', async () => {
  const f = fixture();
  f.answers.push(f.room('party-1', [line(1), line(2)]));
  f.chat.open('party-1', 'member-a'); await f.settle(); await f.settle();
  f.chat.poke();
  f.answers.push(f.room('party-2', [line(1, 'member-b', 'new party')]));
  await f.settle(); await f.settle(); await f.settle();
  const s = f.chat.state();
  assert.equal(s.party, 'party-2');
  assert.deepEqual(s.messages.map((m) => m.text), ['new party']);
  assert.equal(s.gap, false);
  f.chat.close();
});

test('not a member: the list is emptied and nothing is retried until the page opens it again', async () => {
  const f = fixture();
  f.answers.push({ status: 403, body: { error: 'not_member' } });
  f.chat.open('party-1', 'member-a'); await f.settle(); await f.settle();
  assert.equal(f.chat.state().status, 'not_member');
  const asked = f.gets.length;
  await f.settle(); await f.settle();
  assert.equal(f.gets.length, asked);
  f.answers.push(f.room('party-1', []));
  assert.equal(f.chat.open('party-1', 'member-a'), true);
  await f.settle(); await f.settle();
  assert.equal(f.chat.state().status, 'connected');
  f.chat.close();
});

test('retry_ms is honoured: an answer at the cap does not make the phone ask again at once', async () => {
  const f = fixture();
  f.answers.push(f.room('party-1', [], 0, 0, 3000));
  f.chat.open('party-1', 'member-a'); await f.settle(); await f.settle();
  assert.equal(f.gets.length, 1);
  f.fire(3000); await f.settle();
  assert.equal(f.gets.length, 2);
  f.chat.close();
});

test('a send whose answer was lost is retried once with the same client_id', async () => {
  const f = fixture();
  f.answers.push(f.room('party-1', []));
  f.chat.open('party-1', 'member-a'); await f.settle(); await f.settle();
  let first = true;
  f.setPost((b) => { if (first) { first = false; return 'offline'; } return { status: 200, body: { party: 'party-1', message: line(1, 'member-a', b.text) } }; });
  assert.equal((await f.chat.send('hi')).ok, true);
  assert.equal(f.posts.length, 2);
  assert.equal(f.posts[0].client_id, f.posts[1].client_id);
  f.chat.close();
});

test('refusals come back with words to show; nothing is drawn for them', async () => {
  const f = fixture();
  f.answers.push(f.room('party-1', []));
  f.chat.open('party-1', 'member-a'); await f.settle(); await f.settle();
  f.setPost(() => ({ status: 429, body: { error: 'too_fast', retry_ms: 1500 } }));
  const r = await f.chat.send('again');
  assert.deepEqual([r.ok, r.error, r.retry_ms], [false, 'too_fast', 1500]);
  assert.ok(r.message);
  assert.equal(f.chat.state().messages.length, 0);
  assert.equal((await f.chat.send('   ')).error, 'empty');
  assert.equal((await f.chat.send('x'.repeat(401))).error, 'too_long');
  assert.equal((await f.chat.send('😀'.repeat(400))).error, 'too_fast', 'an emoji counts once: it reached Party Core');
  f.chat.close();
  assert.equal((await f.chat.send('closed')).error, 'not_connected');
});

test('only lines Party Core built are drawn; markup stays text', () => {
  assert.equal(readLine({ ...line(1), seq: '1' }), null);
  assert.equal(readLine({ ...line(1), kind: 'admin' }), null);
  assert.equal(readLine({ ...sys(1, 'joined'), event: 'free text' }), null);
  assert.equal(readLine({ ...line(1), text: { html: '<b>' } }), null);
  assert.equal(readLine({ ...line(1), avatar: 'https://x.test/a.png' }).avatar, null);
  assert.equal(readLine(line(1, 'member-b', '<img onerror=x>')).text, '<img onerror=x>');
  assert.equal(length('😀😀'), 2);
});

test('system lines are the Party\'s words, from a closed list', () => {
  const name = (id) => ({ bluff: 'BLUFF' }[id] || id);
  assert.equal(systemText(readLine(sys(1, 'joined')), name), 'Ben joined the Party');
  assert.equal(systemText(readLine(sys(1, 'renamed', { was: 'Benny' })), name), 'Benny is now Ben');
  assert.equal(systemText(readLine(sys(1, 'round_started', { game: 'bluff' })), name), 'BLUFF started');
  assert.equal(systemText(readLine(sys(1, 'round_ended', { game: 'bluff', outcome: 'abandoned' })), name), 'BLUFF stopped');
  assert.equal(systemText(readLine(sys(1, 'host', { more: 3 })), name), 'Ben is hosting now, and 3 more changes');
});

test('merge keeps seq order and the last 80', () => {
  const held = Array.from({ length: 79 }, (_, i) => readLine(line(i + 1)));
  const out = merge(held, [readLine(line(81)), readLine(line(80)), readLine(line(3))]);
  assert.equal(out.length, 80);
  assert.deepEqual(out.slice(-2).map((l) => l.seq), [80, 81]);
  assert.equal(unread(out, 79, 'member-a'), 2);
});
