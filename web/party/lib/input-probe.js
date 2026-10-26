// Input probe for handhelds and phones (AVR-330), used only by the diagnostics page and only after a tap.
//
// Report schema 'avrana.input-probe/v0':
//   { schema, startedAt, elapsedMs,
//     viewport: { css: {w, h}, dpr, device: {w, h}, orientation, safeArea: {top, right, bottom, left} | null },
//     support: { secureContext, gamepadApi, touchPoints, pointer, hover },
//     pads: [ { slot, mapping, buttons, axes, pressed: [indexes], moved: [indexes], connects, disconnects } ],
//     keys: [ { key, code, count } ], touches, pointers: { touch, pen, mouse },
//     events: [ { at, kind, detail } ], path, notes: [string] }
//
// Privacy: a controller's id string (vendor, product, sometimes a serial) is never read into the report;
// slots are the browser's own indexes. A printable key is recorded as 'character', never the character
// itself, so typing a Wi-Fi password while the probe runs records nothing a person typed. Nothing is
// stored or sent: the report exists until the page closes, and a person decides whether to copy it.
// 'path' is what the probe has OBSERVED so far, never a claim that a device is supported.

export const INPUT_SCHEMA = 'avrana.input-probe/v0';

export const AXIS_THRESHOLD = 0.5;           // an axis counts as moved past this (sticks rest near 0)
const MAX_EVENTS = 60;                       // the timeline is bounded; the oldest entries drop
const MAX_KEYS = 40;

/** Keys a handheld in keyboard-emulation mode typically sends for its d-pad and face buttons. */
export const NAV_KEYS = Object.freeze(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Enter', 'Escape',
  'Backspace', 'Tab', ' ', 'GoBack', 'BrowserBack', 'MediaPlayPause', 'Unidentified']);

const isFn = (v) => typeof v === 'function';

function safe(fn, fallback) {
  try {
    const v = fn();
    return v === undefined ? fallback : v;
  } catch {
    return fallback;
  }
}

/** What the viewport is, in CSS pixels and in device pixels. `insets` is the measured safe area, or null. */
export function measureViewport(env, insets = null) {
  const w = safe(() => env.innerWidth, 0);
  const h = safe(() => env.innerHeight, 0);
  const dpr = safe(() => env.devicePixelRatio, 1) || 1;
  const type = safe(() => env.screen.orientation.type, null);
  return {
    css: { w, h },
    dpr,
    device: { w: Math.round(w * dpr), h: Math.round(h * dpr) },
    orientation: type || (w > h ? 'landscape' : w < h ? 'portrait' : 'square'),
    safeArea: insets,
  };
}

/** Which input paths this browser exposes before anything is pressed. */
export function inputSupport(env) {
  const nav = env.navigator || {};
  const mm = (q) => safe(() => env.matchMedia(q).matches, null);
  let gamepadApi = 'no';
  if (isFn(nav.getGamepads)) {
    gamepadApi = safe(() => { nav.getGamepads(); return 'yes'; }, 'blocked');   // a policy may throw
  }
  return {
    secureContext: Boolean(env.isSecureContext),
    gamepadApi,
    touchPoints: Number(nav.maxTouchPoints) || 0,
    pointer: mm('(pointer: coarse)') ? 'coarse' : mm('(pointer: fine)') ? 'fine' : 'none',
    hover: mm('(hover: hover)'),
  };
}

/** A pad as the report holds it: shape only, never its id. */
export function describePad(pad) {
  return {
    slot: pad.index,
    mapping: pad.mapping === 'standard' ? 'standard' : 'nonstandard',
    buttons: safe(() => pad.buttons.length, 0),
    axes: safe(() => pad.axes.length, 0),
  };
}

/** The key as the report holds it: navigation and function keys by name, anything printable as 'character'. */
export function keyName(key) {
  if (typeof key !== 'string' || key === '') return 'Unidentified';
  if (key === ' ') return 'Space';
  // Named keys are ASCII words ('ArrowUp', 'F1', 'MediaPlayPause'). Anything else is something typed, even
  // when it is several code points: 'e' plus a combining accent, an emoji with a skin tone, a flag.
  if (/^[A-Z][A-Za-z0-9]{1,31}$/.test(key)) return key;
  return 'character';
}

/**
 * The probe. Feed it browser events (or synthetic ones in tests) and read `report()`.
 * `now()` is a monotonic millisecond clock.
 */
export function createInputProbe({ env = globalThis, now = () => env.performance.now(), insets = null } = {}) {
  const start = now();
  const startedAt = safe(() => new Date().toISOString(), null);
  const pads = new Map();
  const keys = new Map();
  const events = [];
  const pointers = { touch: 0, pen: 0, mouse: 0 };
  let touches = 0;
  let padPressSeen = false;
  let navKeyWithoutPad = 0;
  let viewportInsets = insets;

  const log = (kind, detail) => {
    events.push(detail === undefined ? { at: Math.round(now() - start), kind }
      : { at: Math.round(now() - start), kind, detail });
    if (events.length > MAX_EVENTS) events.shift();
  };

  const entry = (pad) => {
    let e = pads.get(pad.index);
    if (!e) {
      e = { ...describePad(pad), pressed: new Set(), moved: new Set(), connects: 0, disconnects: 0 };
      pads.set(pad.index, e);
    } else {
      Object.assign(e, describePad(pad));
    }
    return e;
  };

  return {
    gamepadConnected(pad) {
      entry(pad).connects += 1;
      log('gamepad-connected', `slot ${pad.index}, ${describePad(pad).mapping}`);
    },
    gamepadDisconnected(pad) {
      entry(pad).disconnects += 1;
      log('gamepad-disconnected', `slot ${pad.index}`);
    },
    /** One poll of navigator.getGamepads(). Browsers report nothing until the first physical press. */
    sample(list) {
      for (const pad of Array.from(list || [])) {
        if (!pad) continue;
        const e = entry(pad);
        safe(() => pad.buttons.forEach((b, i) => {
          if ((b && (b.pressed || b.value > AXIS_THRESHOLD)) && !e.pressed.has(i)) {
            e.pressed.add(i);
            padPressSeen = true;
            log('button', `slot ${pad.index} #${i}`);
          }
        }));
        safe(() => pad.axes.forEach((v, i) => {
          if (Math.abs(v) > AXIS_THRESHOLD && !e.moved.has(i)) {
            e.moved.add(i);
            log('axis', `slot ${pad.index} #${i}`);
          }
        }));
      }
    },
    key(event) {
      const name = keyName(event.key);
      const code = name === 'character' ? 'character' : (event.code || '');
      const id = `${name}|${code}`;
      const k = keys.get(id);
      if (k) k.count += 1;
      else if (keys.size < MAX_KEYS) {
        keys.set(id, { key: name, code, count: 1 });
        log('key', name === 'character' ? 'character' : `${name}${code ? ` (${code})` : ''}`);
      }
      if (NAV_KEYS.includes(event.key) && !padPressSeen) navKeyWithoutPad += 1;
    },
    touch() {
      touches += 1;
      if (touches === 1) log('touch');
    },
    pointer(type) {
      if (type in pointers) {
        if (pointers[type] === 0) log('pointer', type);
        pointers[type] += 1;
      }
    },
    visibility(state) { log('visibility', state); },
    focus(hasFocus) { log(hasFocus ? 'focus' : 'blur'); },
    resize() { log('resize', (({ css }) => `${css.w}×${css.h}`)(measureViewport(env, viewportInsets))); },
    setInsets(value) { viewportInsets = value; },

    report() {
      const support = inputSupport(env);
      const padList = [...pads.values()].map((e) => ({
        slot: e.slot, mapping: e.mapping, buttons: e.buttons, axes: e.axes,
        pressed: [...e.pressed].sort((a, b) => a - b), moved: [...e.moved].sort((a, b) => a - b),
        connects: e.connects, disconnects: e.disconnects,
      }));
      return {
        schema: INPUT_SCHEMA,
        startedAt,
        elapsedMs: Math.round(now() - start),
        viewport: measureViewport(env, viewportInsets),
        support,
        pads: padList,
        keys: [...keys.values()],
        touches,
        pointers: { ...pointers },
        events: events.slice(),
        ...classify(support, padList, navKeyWithoutPad, touches, pointers),
      };
    },
  };
}

/** What has been observed, as one path and plain notes. Never a support claim. */
export function classify(support, pads, navKeyWithoutPad, touches, pointers = {}) {
  const notes = [];
  const pressedPads = pads.filter((p) => p.pressed.length || p.moved.length);
  let path = 'nothing-yet';
  if (pressedPads.some((p) => p.mapping === 'standard')) path = 'gamepad-standard';
  else if (pressedPads.length) path = 'gamepad-nonstandard';
  else if (navKeyWithoutPad > 0) path = 'keyboard-emulation';
  else if (touches > 0 || pointers.touch > 0) path = 'touch-only';

  if (support.gamepadApi === 'no') notes.push('This browser has no Gamepad API here (navigator.getGamepads is missing).');
  if (support.gamepadApi === 'blocked') notes.push('The Gamepad API is present but blocked (a permissions policy threw).');
  if (support.gamepadApi === 'yes' && !support.secureContext) {
    notes.push('Not a secure context: some browsers hide gamepads on plain http. Repeat on https://party.avrana.net.');
  }
  if (support.gamepadApi === 'yes' && pads.length === 0) {
    notes.push('No controller reported yet. Browsers list a controller only after its first button press.');
  }
  if (pressedPads.some((p) => p.mapping === 'nonstandard')) {
    notes.push('A nonstandard mapping: button and axis numbers are the device\'s own, not the W3C standard layout.');
  }
  if (path === 'keyboard-emulation') {
    notes.push('Navigation keys arrived with no controller button: the device is probably in keyboard (or d-pad) mode.');
  }
  if (path === 'touch-only' && support.gamepadApi === 'yes') {
    notes.push('Touch works. Press a controller button to test the controller.');
  }
  if (pads.some((p) => p.disconnects > 0)) notes.push('A controller disconnected during the probe; see the timeline.');
  return { path, notes };
}
