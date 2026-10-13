// Tier 1 (node --test): the going screen's watchdog (AVR-339) with a fake clock and a fake page.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createGoingWatchdog, WAIT_MS, RETRIES } from '../../web/party/lib/going-watchdog.js';
import { moveKey } from '../../web/party/lib/party-mode.js';

const TO = 'https://games.avrana.net/games/hello/';

// A clock that only moves when told to, a document that can be hidden, a window that can leave.
function rig(options = {}) {
  let now = 0, seq = 0;
  const timers = new Map();
  const handlers = { doc: {}, win: {} };
  const doc = { visibilityState: 'visible', addEventListener: (t, f) => { handlers.doc[t] = f; } };
  const win = { addEventListener: (t, f) => { handlers.win[t] = f; } };
  const log = { retries: [], giveUps: [] };
  const watch = createGoingWatchdog({
    retry: (to) => log.retries.push(to), giveUp: (to) => log.giveUps.push(to), doc, win,
    setTimer: (fn, ms) => { seq += 1; timers.set(seq, { fn, at: now + ms }); return seq; },
    clearTimer: (id) => { timers.delete(id); },
    ...options,
  });
  const advance = (ms) => {
    const end = now + ms;
    for (;;) {
      const due = [...timers.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]); now = due[1].at; due[1].fn();
    }
    now = end;
  };
  const hide = () => { doc.visibilityState = 'hidden'; handlers.doc.visibilitychange(); };
  const show = () => { doc.visibilityState = 'visible'; handlers.doc.visibilitychange(); };
  return { watch, log, advance, hide, show, timers, leave: () => handlers.win.pagehide() };
}

test('a navigation that never completes: one retry after the wait, then the way out, and nothing more', () => {
  const r = rig();
  assert.equal(RETRIES, 1);
  assert.equal(r.watch.arm(TO), true);                          // the caller navigates now
  r.advance(WAIT_MS - 1);
  assert.deepEqual(r.log, { retries: [], giveUps: [] });        // not nervous
  r.advance(1);
  assert.deepEqual(r.log, { retries: [TO], giveUps: [] });
  r.advance(WAIT_MS);
  assert.deepEqual(r.log, { retries: [TO], giveUps: [TO] });
  assert.equal(r.watch.gaveUp, true);
  r.advance(10 * WAIT_MS);                                      // it cannot loop
  assert.deepEqual(r.log, { retries: [TO], giveUps: [TO] });
  assert.equal(r.timers.size, 0);
});

test('a navigation that completes leaves nothing behind: the page is leaving, the timer is gone', () => {
  const r = rig();
  r.watch.arm(TO);
  r.advance(WAIT_MS / 2);
  r.leave();                                                    // pagehide: the phone has arrived
  r.advance(10 * WAIT_MS);
  assert.deepEqual(r.log, { retries: [], giveUps: [] });
  assert.equal(r.timers.size, 0);
  assert.equal(r.watch.target, null);
});

test('the route changes away: the timer is cancelled, and no way out is raised', () => {
  const r = rig();
  r.watch.arm(TO);
  r.advance(WAIT_MS + 1);                                       // one retry made
  r.watch.cancel();                                             // show() left the going screen
  r.advance(10 * WAIT_MS);
  assert.deepEqual(r.log, { retries: [TO], giveUps: [] });
  assert.equal(r.timers.size, 0);
  assert.equal(r.watch.arm(TO), true);                          // coming back later is a fresh start
});

test('a hidden or frozen page never looks like a hung navigation; the wait starts over when it shows', () => {
  const r = rig();
  r.watch.arm(TO);
  r.advance(WAIT_MS - 100);
  r.hide();                                                     // locked, another tab, or frozen in the back/forward cache
  assert.equal(r.timers.size, 0);
  r.advance(100 * WAIT_MS);
  assert.deepEqual(r.log, { retries: [], giveUps: [] });
  r.show();
  r.advance(WAIT_MS - 1);
  assert.deepEqual(r.log, { retries: [], giveUps: [] });        // a full wait, not the remainder
  r.advance(1);
  assert.deepEqual(r.log, { retries: [TO], giveUps: [] });
});

test('a timer that fires while the page is hidden (a throttled clock) does nothing', () => {
  const r = rig();
  r.watch.arm(TO);
  const [[, timer]] = [...r.timers.entries()];
  r.watch.arm(TO);                                              // same target: nothing restarts
  r.hide();
  timer.fn();                                                   // the browser ran it anyway
  assert.deepEqual(r.log, { retries: [], giveUps: [] });
});

test('the same target is armed once, so view updates do not navigate or restart the wait', () => {
  const r = rig();
  assert.equal(r.watch.arm(TO), true);
  r.advance(WAIT_MS / 2);
  assert.equal(r.watch.arm(TO), false);                         // a poll's new view while going
  r.advance(WAIT_MS / 2);
  assert.deepEqual(r.log.retries, [TO]);                        // the clock was not reset by it
  r.advance(WAIT_MS);
  assert.equal(r.watch.arm(TO), false);                         // given up: a poll does not navigate again either
  assert.deepEqual(r.log.retries, [TO]);
  assert.equal(r.watch.arm(TO + 'x'), true);                    // another target is another trip
});

test('Try again: a fresh round of waits and one navigation now; Back to Party cancels', () => {
  const r = rig();
  r.watch.arm(TO);
  r.advance(2 * WAIT_MS);
  assert.equal(r.watch.gaveUp, true);
  r.watch.again();
  assert.deepEqual(r.log.retries, [TO, TO]);                    // the retry, and the person's own
  assert.equal(r.watch.gaveUp, false);
  r.advance(WAIT_MS);
  assert.deepEqual(r.log.retries, [TO, TO, TO]);
  r.advance(WAIT_MS);
  assert.equal(r.log.giveUps.length, 2);                        // and the way out again, never a loop
  r.watch.again();
  r.watch.cancel();                                             // Back to Party
  r.advance(10 * WAIT_MS);
  assert.equal(r.log.giveUps.length, 2);
  r.watch.again();                                              // nothing to try again once cancelled
  assert.equal(r.log.retries.length, 4);
});

test('moveKey tells one move of the Party from the next', () => {
  const view = (seq, extra = {}) => ({ party: 'p1', nav: { seq }, location: { at: 'game', game: 'hello', session: 's1' }, ...extra });
  assert.equal(moveKey(view(3)), moveKey(view(3, { version: 9 })));   // a poll is not a move
  assert.notEqual(moveKey(view(3)), moveKey(view(4)));
  assert.notEqual(moveKey(view(3)), moveKey(view(3, { location: { at: 'game', game: 'hello', session: 's2' } })));
  assert.notEqual(moveKey(view(3)), moveKey(view(3, { party: 'p2' })));
  assert.equal(typeof moveKey(null), 'string');
});
