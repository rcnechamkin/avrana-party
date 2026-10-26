// Tier 1 (node --test): the handheld input probe (AVR-330) against synthetic browsers and controllers.
// These are SIMULATED observations. They prove the probe's logic, never what a real handheld does.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { INPUT_SCHEMA, classify, createInputProbe, describePad, inputSupport, keyName, measureViewport }
  from '../../web/party/lib/input-probe.js';

function browser(over = {}) {
  const nav = { getGamepads: () => [null, null, null, null], maxTouchPoints: 5, ...(over.navigator || {}) };
  return {
    isSecureContext: true,
    innerWidth: 360, innerHeight: 360, devicePixelRatio: 2,
    screen: { orientation: { type: 'landscape-primary' } },
    matchMedia: (q) => ({ matches: q.includes('coarse') }),
    ...over,
    navigator: nav,
  };
}

function pad(index, { mapping = 'standard', buttons = 17, axes = 4, pressed = [], moved = {} } = {}) {
  return {
    index, mapping, id: 'Vendor Pad (Vendor: 2dc8 Product: 6006) serial 0042', connected: true,
    buttons: Array.from({ length: buttons }, (_, i) => ({ pressed: pressed.includes(i), value: pressed.includes(i) ? 1 : 0 })),
    axes: Array.from({ length: axes }, (_, i) => moved[i] ?? 0),
  };
}

function clock() {
  let t = 1000;
  const now = () => t;
  now.advance = (ms) => { t += ms; };
  return now;
}

test('Gamepad API unavailable: the report says so and the path stays nothing-yet', () => {
  const env = browser({ navigator: { getGamepads: undefined, maxTouchPoints: 0 } });
  const r = createInputProbe({ env, now: clock() }).report();
  assert.equal(r.schema, INPUT_SCHEMA);
  assert.equal(r.support.gamepadApi, 'no');
  assert.equal(r.path, 'nothing-yet');
  assert.ok(r.notes.some((n) => n.includes('no Gamepad API')));
});

test('a permissions policy that throws reads as blocked, not as no', () => {
  const env = browser({ navigator: { getGamepads: () => { throw new Error('SecurityError'); } } });
  assert.equal(inputSupport(env).gamepadApi, 'blocked');
});

test('empty until the first physical press, then the pad appears with what was pressed', () => {
  const env = browser();
  const probe = createInputProbe({ env, now: clock() });
  probe.sample(env.navigator.getGamepads());
  let r = probe.report();
  assert.equal(r.pads.length, 0);
  assert.ok(r.notes.some((n) => n.includes('after its first button press')));
  probe.gamepadConnected(pad(0));
  probe.sample([pad(0, { pressed: [0] }), null]);
  probe.sample([pad(0, { pressed: [0, 12] }), null]);
  r = probe.report();
  assert.equal(r.path, 'gamepad-standard');
  assert.deepEqual(r.pads[0].pressed, [0, 12]);
  assert.equal(r.pads[0].connects, 1);
});

test('nonstandard mapping is reported as such, with the device\'s own numbering noted', () => {
  const probe = createInputProbe({ env: browser(), now: clock() });
  probe.sample([pad(0, { mapping: '', buttons: 11, axes: 8, pressed: [3], moved: { 6: -1 } })]);
  const r = probe.report();
  assert.equal(r.path, 'gamepad-nonstandard');
  assert.deepEqual(r.pads[0], { slot: 0, mapping: 'nonstandard', buttons: 11, axes: 8, pressed: [3], moved: [6],
    connects: 0, disconnects: 0 });
  assert.ok(r.notes.some((n) => n.includes('nonstandard mapping')));
});

test('keyboard-emulation mode: arrow and Enter keys with no controller press', () => {
  const probe = createInputProbe({ env: browser(), now: clock() });
  for (const key of ['ArrowDown', 'ArrowDown', 'Enter']) probe.key({ key, code: key === 'Enter' ? 'Enter' : 'ArrowDown' });
  const r = probe.report();
  assert.equal(r.path, 'keyboard-emulation');
  assert.deepEqual(r.keys, [{ key: 'ArrowDown', code: 'ArrowDown', count: 2 }, { key: 'Enter', code: 'Enter', count: 1 }]);
});

test('a controller press outranks navigation keys that arrive with it', () => {
  const probe = createInputProbe({ env: browser(), now: clock() });
  probe.sample([pad(0, { pressed: [13] })]);
  probe.key({ key: 'ArrowDown', code: 'ArrowDown' });
  assert.equal(probe.report().path, 'gamepad-standard');
});

test('connect and disconnect are counted and timed on the monotonic clock', () => {
  const now = clock();
  const probe = createInputProbe({ env: browser(), now });
  probe.gamepadConnected(pad(1));
  now.advance(2500);
  probe.gamepadDisconnected(pad(1));
  now.advance(500);
  probe.gamepadConnected(pad(1));
  const r = probe.report();
  assert.equal(r.pads[0].connects, 2);
  assert.equal(r.pads[0].disconnects, 1);
  assert.deepEqual(r.events.map((e) => [e.at, e.kind]),
    [[0, 'gamepad-connected'], [2500, 'gamepad-disconnected'], [3000, 'gamepad-connected']]);
  assert.equal(r.elapsedMs, 3000);
  assert.ok(r.notes.some((n) => n.includes('disconnected')));
});

test('touch fallback: touches with no controller give touch-only and a hint to press a button', () => {
  const probe = createInputProbe({ env: browser(), now: clock() });
  probe.touch();
  probe.touch();
  probe.pointer('touch');
  const r = probe.report();
  assert.equal(r.path, 'touch-only');
  assert.equal(r.touches, 2);
  assert.equal(r.pointers.touch, 1);
  assert.equal(r.events.filter((e) => e.kind === 'touch').length, 1);
});

test('privacy: no controller id and no typed character ever reaches the report', () => {
  const probe = createInputProbe({ env: browser(), now: clock() });
  const p = pad(0, { pressed: [0] });
  probe.gamepadConnected(p);
  probe.sample([p]);
  for (const ch of 'hunter2!') probe.key({ key: ch, code: `Key${ch.toUpperCase()}` });
  const text = JSON.stringify(probe.report());
  for (const leak of ['Vendor', '2dc8', '6006', 'serial', '0042', 'hunter', 'KeyH']) {
    assert.ok(!text.includes(leak), `report leaks ${leak}`);
  }
  assert.deepEqual(probe.report().keys, [{ key: 'character', code: 'character', count: 8 }]);
  assert.deepEqual(Object.keys(describePad(p)).sort(), ['axes', 'buttons', 'mapping', 'slot']);
});

test('key names: printable keys collapse, named keys stay, Space is named', () => {
  assert.equal(keyName('a'), 'character');
  assert.equal(keyName('é'), 'character');
  assert.equal(keyName(' '), 'Space');
  assert.equal(keyName('ArrowLeft'), 'ArrowLeft');
  assert.equal(keyName('F1'), 'F1');
  for (const typed of ['é', '\u{1F44D}\u{1F3FD}', '\u{1F1EB}\u{1F1F7}', 'ab', 'A', 'hunter2']) {
    assert.equal(keyName(typed), 'character', JSON.stringify(typed));
  }
  assert.equal(keyName(''), 'Unidentified');
  assert.equal(keyName(undefined), 'Unidentified');
});

test('viewport: a 720×720 panel at DPR 2 reads as 360×360 CSS pixels, square, with measured insets', () => {
  const env = browser({ screen: {} });
  const v = measureViewport(env, { top: 0, right: 0, bottom: 0, left: 0 });
  assert.deepEqual(v.css, { w: 360, h: 360 });
  assert.deepEqual(v.device, { w: 720, h: 720 });
  assert.equal(v.orientation, 'square');
  assert.deepEqual(v.safeArea, { top: 0, right: 0, bottom: 0, left: 0 });
});

test('plain http is called out, because some browsers hide gamepads outside a secure context', () => {
  const { notes } = classify({ gamepadApi: 'yes', secureContext: false }, [], 0, 0);
  assert.ok(notes.some((n) => n.includes('Not a secure context')));
});

test('the timeline is bounded', () => {
  const probe = createInputProbe({ env: browser(), now: clock() });
  for (let i = 0; i < 200; i += 1) probe.visibility(i % 2 ? 'visible' : 'hidden');
  assert.equal(probe.report().events.length, 60);
});

test('a throwing browser API never breaks the probe', () => {
  const env = browser({ matchMedia: () => { throw new Error('x'); } });
  Object.defineProperty(env, 'innerWidth', { get() { throw new Error('x'); } });
  const r = createInputProbe({ env, now: clock() }).report();
  assert.equal(r.viewport.css.w, 0);
  assert.equal(r.support.pointer, 'none');
});
