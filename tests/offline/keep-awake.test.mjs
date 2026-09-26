// Tier 1 (node --test): keep-awake (Screen Wake Lock) lifecycle with a fake browser.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createKeepAwake } from '../../web/party/lib/keep-awake.js';

function fakeBrowser({ refuse = false } = {}) {
  const listeners = new Map();
  const doc = {
    visibilityState: 'visible',
    addEventListener: (t, fn) => listeners.set(t, fn),
    removeEventListener: (t) => listeners.delete(t),
    fire(state) { this.visibilityState = state; listeners.get('visibilitychange')?.(); },
  };
  const calls = { requests: 0, releases: 0 };
  let active = null;
  const nav = {
    wakeLock: {
      async request(type) {
        assert.equal(type, 'screen');
        calls.requests += 1;
        if (refuse) throw Object.assign(new Error('no'), { name: 'NotAllowedError' });
        const handlers = [];
        active = {
          released: false,
          addEventListener: (t, fn) => handlers.push(fn),
          async release() { if (!this.released) { this.released = true; calls.releases += 1; handlers.forEach((f) => f()); } },
        };
        return active;
      },
    },
  };
  // The browser drops the lock when the page is hidden.
  const hide = async () => { doc.fire('hidden'); if (active) await active.release(); };
  return { nav, doc, calls, hide };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

test('unsupported browsers are a silent no-op', async () => {
  const awake = createKeepAwake({ navigator: {}, document: { visibilityState: 'visible' } });
  assert.equal(awake.state, 'unsupported');
  await awake.want();
  await awake.release();
  assert.equal(awake.state, 'unsupported');
});

test('want, re-acquire after the page comes back, release', async () => {
  const b = fakeBrowser();
  const states = [];
  const awake = createKeepAwake({ navigator: b.nav, document: b.doc, onChange: (s) => states.push(s) });
  assert.equal(awake.state, 'off');
  await awake.want();
  assert.equal(awake.state, 'on');
  assert.equal(b.calls.requests, 1);
  await awake.want();                      // idempotent while held
  assert.equal(b.calls.requests, 1);
  await b.hide();
  assert.equal(awake.state, 'off');
  b.doc.fire('visible');
  await tick(); await tick();
  assert.equal(b.calls.requests, 2);
  assert.equal(awake.state, 'on');
  await awake.release();
  assert.equal(awake.state, 'off');
  b.doc.fire('visible');
  await tick();
  assert.equal(b.calls.requests, 2);      // no longer wanted: never re-requested
  assert.deepEqual(states, ['on', 'off', 'on', 'off']);
});

test('no request while hidden; it waits for the page to be visible', async () => {
  const b = fakeBrowser();
  b.doc.visibilityState = 'hidden';
  const awake = createKeepAwake({ navigator: b.nav, document: b.doc });
  await awake.want();
  assert.equal(b.calls.requests, 0);
  b.doc.fire('visible');
  await tick(); await tick();
  assert.equal(b.calls.requests, 1);
});

test('a refused request is not fatal', async () => {
  const b = fakeBrowser({ refuse: true });
  const awake = createKeepAwake({ navigator: b.nav, document: b.doc, onChange: () => { throw new Error('bad UI'); } });
  await awake.want();
  assert.equal(awake.state, 'refused');
  await awake.dispose();
});
