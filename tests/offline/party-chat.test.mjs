import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPartyChat, normalizeMessage } from '../../web/party/lib/party-chat.js';

const message = (id, text = 'hello') => ({ id, by: 'hashed-uid', name: 'Robin',
  avatar: '🐸', pfp: null, text, ts: 1234, img: null });
function fixture() {
  const sockets = [], changes = [], pending = new Map();
  let number = 0, me = { token: 'existing-player-01', name: 'Robin', avatar: '🐸' };
  class Socket {
    constructor(url) { this.url = url; this.sent = []; sockets.push(this); }
    send(text) { this.sent.push(JSON.parse(text)); }
    close() { this.onclose?.(); }
    receive(data) { this.onmessage({ data: JSON.stringify(data) }); }
  }
  const chat = createPartyChat({ identity: () => me, origin: 'https://party.avrana.net',
    Socket, onChange: (s) => changes.push(s),
    schedule: (fn, ms) => { const id = ++number; pending.set(id, { fn: () => { pending.delete(id); fn(); }, ms }); return id; },
    cancel: (id) => pending.delete(id) });
  return { chat, sockets, changes, pending, setName: (name) => { me = { ...me, name }; } };
}
test('Party Chat reuses donor hello, integer IDs, history, message echo and presence count', () => {
  const f = fixture(); f.chat.open(); f.chat.open();
  assert.equal(f.sockets.length, 1);
  const s = f.sockets[0];
  assert.equal(s.url, 'wss://party.avrana.net/chat/ws');
  s.onopen();
  assert.deepEqual(s.sent[0], { t: 'hello', token: 'existing-player-01', name: 'Robin', avatar: '🐸' });
  assert.equal(f.chat.send('too early'), false);
  s.receive({ type: 'welcome', you: 'hashed-uid' });
  s.receive({ type: 'history', messages: [message(1)] });
  s.receive({ type: 'presence', online: 3 });
  assert.equal(f.changes.at(-1).online, 3);
  assert.equal(f.chat.send('  Hey party  '), true);
  assert.deepEqual(s.sent.at(-1), { t: 'msg', text: 'Hey party' });
  assert.equal(f.changes.at(-1).messages.length, 1); // No optimistic second store.
  s.receive({ type: 'msg', ...message(2, 'Hey party') });
  s.receive({ type: 'msg', ...message(2, 'duplicate') });
  assert.equal(f.changes.at(-1).messages.length, 2);
  s.receive({ type: 'history', messages: Array.from({length: 65}, (_, i) => message(i + 1)) });
  assert.equal(f.changes.at(-1).messages.length, 60);
  s.receive({ type: 'cleared' });
  assert.equal(f.changes.at(-1).messages.length, 0);
  f.chat.close();
  assert.equal(f.pending.size, 0);
});
test('profile edits reconnect the same channel; stale sockets cannot mutate the current view', () => {
  const f = fixture(); f.chat.open(); const old = f.sockets[0]; old.onopen();
  old.receive({ type: 'welcome', you: 'hashed-uid' });
  f.setName('New Name'); f.chat.reconnect();
  const fresh = f.sockets[1]; fresh.onopen();
  assert.equal(fresh.sent[0].token, old.sent[0].token);
  assert.equal(fresh.sent[0].name, 'New Name');
  old.receive({ type: 'msg', ...message(1, 'stale') });
  assert.equal(f.changes.at(-1).messages.length, 0);
  fresh.receive({ type: 'welcome', you: 'hashed-uid' });
  fresh.close();
  assert.equal(f.changes.at(-1).status, 'unavailable');
  const retry = [...f.pending.values()].find((t) => t.ms === 600);
  assert.ok(retry); retry.fn();
  assert.equal(f.sockets.length, 3);
  f.chat.close();
});
test('malformed payloads and untrusted image URLs are not rendered as links', () => {
  assert.equal(normalizeMessage({ ...message(1), id: 'string-id' }), null);
  assert.equal(normalizeMessage({ ...message(1), text: {} }), null);
  assert.equal(normalizeMessage({ ...message(1), pfp: 'https://outside.test/x' }).pfp, '');
  const f = fixture(); f.chat.open(); const s = f.sockets[0];
  s.onmessage({ data: 'not json' }); s.receive({ type: 'history', messages: {} });
  s.receive({ type: 'presence', online: -1 });
  assert.equal(f.changes.at(-1).online, 0);
  f.chat.close();
});
test('no welcome times out; heartbeat uses donor ping; closed chat stops retries', () => {
  const f = fixture(); f.chat.open(); let s = f.sockets[0];
  [...f.pending.values()].find((t) => t.ms === 12000).fn();
  assert.equal(f.changes.at(-1).status, 'unavailable');
  [...f.pending.values()].find((t) => t.ms === 600).fn();
  s = f.sockets[1]; s.onopen(); s.receive({ type: 'welcome', you: 'me' });
  [...f.pending.values()].find((t) => t.ms === 25000).fn();
  assert.deepEqual(s.sent.at(-1), { t: 'ping' });
  f.chat.close(); assert.equal(f.pending.size, 0);
  assert.equal(f.chat.send('closed'), false);
});
