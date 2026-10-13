// The way to a game, watched (AVR-339). Party Home takes a phone to a game's own origin with one
// top-level navigation (ADR 0013). A page cannot see that navigation hang, only that it is still
// alive and looking at the going screen after a while. A hung navigation was seen once in about 13
// WebKit runs in CI (no response for ~22 s, then a browser error); this makes sure nobody is
// stranded: one more try, then a plain way out.
//
//   const watch = createGoingWatchdog({ retry: (to) => location.replace(to), giveUp: (to) => ... });
//   if (watch.arm(to)) location.replace(to);   // true: this target is new, go now
//   watch.again();                             // "Try again": a fresh round of waits
//   watch.cancel();                            // the phone is no longer on the going screen
//
// The wait only counts while the page is visible, so a locked phone, another tab or a page frozen
// in the back/forward cache never looks like a hung navigation; a page that is leaving (pagehide)
// is disarmed, because then the navigation has arrived.
export const WAIT_MS = 8000;   // twice the shell's own 4 s asks; a LAN page loads in about one; under the ~22 s a hung one took to die
export const RETRIES = 1;      // one more navigation, then the way out: 2 x 8 s = 16 s, before the browser gives up by itself

export function createGoingWatchdog({ retry, giveUp, doc = globalThis.document, win = globalThis.window,
  setTimer = globalThis.setTimeout.bind(globalThis), clearTimer = globalThis.clearTimeout.bind(globalThis),
  waitMs = WAIT_MS, retries = RETRIES }) {
  let target = null, tries = 0, timer = null, gaveUp = false;

  const visible = () => !doc || doc.visibilityState === undefined || doc.visibilityState === 'visible';
  const stop = () => { if (timer !== null) { clearTimer(timer); timer = null; } };

  function start() {
    stop();
    if (target === null || gaveUp || !visible()) return;        // hidden: the wait starts over when it shows
    timer = setTimer(fire, waitMs);
  }

  function fire() {
    timer = null;
    if (target === null || gaveUp || !visible()) return;
    if (tries < retries) {
      tries += 1;
      start();
      retry(target);
    } else {
      gaveUp = true;
      giveUp(target);
    }
  }

  if (doc && doc.addEventListener) doc.addEventListener('visibilitychange', start);
  if (win && win.addEventListener) win.addEventListener('pagehide', () => cancel());

  function cancel() { stop(); target = null; tries = 0; gaveUp = false; }

  return {
    /** Watch the navigation to `to`. True when the caller should navigate now; false when this very
     * target is already on its way, or was given up on (nothing navigates a phone twice by itself). */
    arm(to) {
      if (target === to) return false;
      cancel();
      target = to;
      start();
      return true;
    },
    /** A person asked again: a fresh round of waits, and one navigation now. */
    again() {
      if (target === null) return;
      stop(); tries = 0; gaveUp = false;
      start();
      retry(target);
    },
    cancel,
    get target() { return target; },
    get gaveUp() { return gaveUp; },
  };
}
