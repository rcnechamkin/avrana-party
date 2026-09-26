// Keep the screen on during active play (Screen Wake Lock, secure contexts only).
//
// Rules (docs/design/FULL-MODE.md): request only inside a tap that starts play; the browser drops
// the lock whenever the page is hidden, so re-request when it becomes visible again while play is
// still wanted; release on leave. Every failure is silent: an unsupported browser or a refused
// request only means the screen may dim.
//
//   const awake = createKeepAwake({ onChange: (state) => ... });
//   button.onclick = () => { awake.want(); ... };   // inside the user's tap
//   leave.onclick  = () => awake.release();
//
// state: 'unsupported' | 'off' | 'on' | 'refused'

export function createKeepAwake({ navigator: nav = globalThis.navigator, document: doc = globalThis.document,
  onChange = () => {} } = {}) {
  const supported = Boolean(nav && nav.wakeLock && typeof nav.wakeLock.request === 'function');
  let wanted = false;
  let sentinel = null;
  let pending = null;
  let state = supported ? 'off' : 'unsupported';

  const set = (next) => {
    if (next !== state) {
      state = next;
      try { onChange(state); } catch { /* a UI callback must not break the lock */ }
    }
  };

  async function acquire() {
    if (!supported || !wanted || sentinel || pending) return;
    if (doc && doc.visibilityState && doc.visibilityState !== 'visible') return;
    pending = (async () => {
      try {
        const lock = await nav.wakeLock.request('screen');
        if (!wanted) {
          await lock.release().catch(() => {});
          return;
        }
        sentinel = lock;
        lock.addEventListener('release', () => {
          if (sentinel === lock) sentinel = null;
          set('off');
        });
        set('on');
      } catch {
        set('refused');
      } finally {
        pending = null;
      }
    })();
    await pending;
  }

  function onVisibility() {
    if (doc.visibilityState === 'visible' && wanted) acquire();
  }
  if (supported && doc && typeof doc.addEventListener === 'function') {
    doc.addEventListener('visibilitychange', onVisibility);
  }

  return {
    get state() { return state; },
    get supported() { return supported; },
    /** Call from the tap that starts play (user activation helps some browsers). */
    want() {
      wanted = true;
      return acquire();
    },
    /** Stop wanting the lock (leave, game over, disconnect). */
    async release() {
      wanted = false;
      const lock = sentinel;
      sentinel = null;
      if (lock) {
        try { await lock.release(); } catch { /* already released */ }
      }
      if (supported) set('off');
    },
    dispose() {
      if (supported && doc && typeof doc.removeEventListener === 'function') {
        doc.removeEventListener('visibilitychange', onVisibility);
      }
      return this.release();
    },
  };
}
