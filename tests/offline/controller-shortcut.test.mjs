// The controller shortcut's rules (AVR-581): web/party/lib/controller.js. Run with: node --test tests/offline/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { HOLD_MS, IDLE_MS, SYSTEM, createLearner, createWatcher, fabHidden, livePads, padLine, parsePref, refusal,
  shortcutName } from '../../web/party/lib/controller.js';

/** A fake Gamepad: `down` lists the pressed buttons. */
function pad(down = [], { id = 'Xbox Wireless Controller', mapping = 'standard', index = 0, timestamp = 1 } = {}) {
  return { id, mapping, index, connected: true, timestamp,
    buttons: Array.from({ length: 17 }, (_, i) => ({ pressed: down.includes(i), value: down.includes(i) ? 1 : 0 })) };
}
const VIEW_MENU = { buttons: [8, 9], mapping: 'standard', id: '' };
const VERIFIED = { v: 1, shortcut: VIEW_MENU, verified: true, hide: true };

test('a kept preference is versioned, and hiding needs a verified shortcut', () => {
  assert.deepEqual(parsePref(null), { v: 1, shortcut: null, verified: false, hide: false });
  assert.deepEqual(parsePref({ v: 2, shortcut: VIEW_MENU, verified: true, hide: true }).hide, false);   // another version: forgotten
  assert.equal(parsePref({ v: 1, shortcut: VIEW_MENU, verified: false, hide: true }).hide, false);
  assert.equal(parsePref({ v: 1, shortcut: null, verified: true, hide: true }).hide, false);
  assert.deepEqual(parsePref(VERIFIED), VERIFIED);
  assert.equal(parsePref({ v: 1, shortcut: { buttons: [0], mapping: 'standard' }, verified: true }).shortcut, null);   // one game button
  assert.equal(parsePref({ v: 1, shortcut: { buttons: [99, 1], mapping: 'standard' }, verified: true }).shortcut, null);
  // Off the standard mapping a shortcut belongs to the controller it was learned on.
  assert.equal(parsePref({ v: 1, shortcut: { buttons: [3, 4], mapping: '', id: 'Odd pad' } }).shortcut.id, 'Odd pad');
});

test('one button alone is refused unless it is the system button', () => {
  assert.equal(refusal([0]), 'one_button');
  assert.equal(refusal([SYSTEM]), null);
  assert.equal(refusal([8, 9]), null);
  assert.equal(shortcutName(VIEW_MENU), 'View + Menu');
  assert.equal(shortcutName({ buttons: [3, 4], mapping: '' }), 'Button 3 + Button 4');
});

test('learning takes a steady hold, once, and refuses a lone game button', () => {
  const l = createLearner();
  assert.equal(l.step([pad([8])], 0), null);
  assert.equal(l.step([pad([8, 9])], 100), null);              // the chord changed: its clock starts again
  assert.equal(l.step([pad([8, 9])], 100 + HOLD_MS - 1), null);
  assert.deepEqual(l.step([pad([8, 9])], 100 + HOLD_MS), { buttons: [8, 9], mapping: 'standard', id: '' });
  assert.equal(l.step([pad([8, 9])], 5000), null);             // still held: not again until let go
  l.step([pad()], 5100);
  l.step([pad([0])], 6000);
  assert.deepEqual(l.step([pad([0])], 6000 + HOLD_MS), { refused: 'one_button', buttons: [0] });
});

test('the watcher fires once per hold, on any fitting pad, wherever it is indexed', () => {
  const w = createWatcher(VIEW_MENU);
  assert.equal(w.step([null, pad([8, 9], { index: 1 })], 0), false);
  assert.equal(w.step([null, pad([8, 9], { index: 1 })], HOLD_MS), true);
  assert.equal(w.step([pad([8, 9], { index: 0 })], HOLD_MS + 500), false);   // reindexed, still the same hold
  w.step([pad()], 2000);
  w.step([pad([8, 9])], 3000);
  assert.equal(w.step([pad([8, 9])], 3000 + HOLD_MS), true);
});

test('normal play does not open the menu: a tap, half the chord, or a short press', () => {
  const w = createWatcher(VIEW_MENU);
  for (let t = 0; t < 5000; t += 50) assert.equal(w.step([pad(t % 200 ? [0, 8] : [9])], t), false);
  w.step([pad([8, 9])], 6000);
  assert.equal(w.step([pad([8, 9])], 6000 + HOLD_MS - 50), false);
  assert.equal(w.step([pad()], 6000 + HOLD_MS), false);
  assert.equal(w.step([pad([8, 9])], 9000), false);           // a fresh hold starts its clock when first seen
});

test('a non-standard shortcut fires only on the controller it was learned on', () => {
  const s = { buttons: [3, 4], mapping: '', id: 'Odd pad' };
  const w = createWatcher(s);
  w.step([pad([3, 4], { mapping: '', id: 'Other pad' })], 0);
  assert.equal(w.step([pad([3, 4], { mapping: '', id: 'Other pad' })], HOLD_MS), false);
  w.step([pad([3, 4], { mapping: '', id: 'Odd pad' })], 2000);
  assert.equal(w.step([pad([3, 4], { mapping: '', id: 'Odd pad' })], 2000 + HOLD_MS), true);
});

test('the button hides only by choice, with a connected fitting pad, and comes back on disconnect or idle', () => {
  assert.equal(fabHidden(parsePref({ v: 1 }), [pad()]), false);                 // bare connection keeps it
  assert.equal(fabHidden({ ...VERIFIED, hide: false }, [pad()]), false);
  assert.equal(fabHidden(VERIFIED, [pad()]), true);
  assert.equal(fabHidden(VERIFIED, []), false);                                 // disconnect
  assert.equal(fabHidden(VERIFIED, [null, { ...pad(), connected: false }]), false);
  assert.equal(fabHidden(VERIFIED, [pad([], { mapping: '', id: 'Odd pad' })]), false);
  assert.equal(fabHidden(VERIFIED, [pad()], { idleMs: IDLE_MS }), false);       // left on the sofa
  assert.equal(livePads(undefined).length, 0);
});

test('the drawer says only what is true', () => {
  const none = parsePref(null);
  assert.equal(padLine({ pref: none, connected: false, phase: 'idle' }), '');
  assert.match(padLine({ pref: none, connected: true, phase: 'idle' }), /stays on screen/);
  assert.match(padLine({ pref: none, connected: true, phase: 'learning' }), /Home button, or two buttons/);
  assert.match(padLine({ pref: none, connected: true, phase: 'verifying', candidate: VIEW_MENU }), /View \+ Menu again/);
  assert.match(padLine({ pref: VERIFIED, connected: false, phase: 'idle' }), /Connect the controller/);
});
