// The controller shortcut into the Party drawer (AVR-581): pure rules, no DOM, so node tests them
// (tests/offline/controller-shortcut.test.mjs). layer-app.js reads the Gamepad API in the Party's own
// frame, so a game page can neither see nor fake what is pressed: it never posts input to the Party,
// and the shortcut only opens the drawer, where every action still asks for its own confirmation.
//
// Owner decisions (AVR-581): a connected controller never hides the floating button by itself;
// hiding is a manual device setting, offered only after a shortcut has worked once; a disconnect
// brings the button back at once. Nothing here claims full controller navigation of the drawer.

export const PREF_KEY = 'avrana-controller/v1';   // versioned, Party-origin, this device only
export const HOLD_MS = 800;                       // a held chord, not a tap: a game move is rarely this
export const IDLE_MS = 10 * 60_000;               // no input this long while hidden: the button comes back
export const SYSTEM = 16;                         // the standard mapping's centre (Home / Guide / PS) button
export const MAX_BUTTONS = 3;

// Names on the standard mapping (W3C Gamepad, Xbox-style words); anything else is "Button N".
const NAMES = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'View', 'Menu', 'Left stick', 'Right stick',
  'Up', 'Down', 'Left', 'Right', 'Home'];

const DEFAULT_PREF = Object.freeze({ v: 1, shortcut: null, verified: false, hide: false });

/** A kept preference, or the defaults: anything malformed is forgotten rather than half-trusted.
 * `hide` holds only with a verified shortcut, so the button cannot be hidden with no way back. */
export function parsePref(raw) {
  if (!raw || typeof raw !== 'object' || raw.v !== 1) return { ...DEFAULT_PREF };
  const shortcut = parseShortcut(raw.shortcut);
  const verified = Boolean(shortcut) && raw.verified === true;
  return { v: 1, shortcut, verified, hide: verified && raw.hide === true };
}

function parseShortcut(s) {
  if (!s || typeof s !== 'object' || !Array.isArray(s.buttons)) return null;
  const buttons = [...new Set(s.buttons)].sort((a, b) => a - b);
  if (!buttons.length || buttons.length > MAX_BUTTONS || !buttons.every((b) => Number.isInteger(b) && b >= 0 && b < 32)) return null;
  if (refusal(buttons)) return null;
  const mapping = s.mapping === 'standard' ? 'standard' : '';
  // Off the standard mapping, button numbers mean nothing on another controller: keep which one.
  const id = mapping ? '' : (typeof s.id === 'string' ? s.id.slice(0, 120) : '');
  return { buttons, mapping, id };
}

/** Why these buttons cannot be the shortcut, or null. One button alone is a game move waiting to
 * happen, unless it is the system button (which no game should be using, when a browser delivers it). */
export function refusal(buttons) {
  if (buttons.length === 1 && buttons[0] !== SYSTEM) return 'one_button';
  if (buttons.length > MAX_BUTTONS) return 'too_many';
  return null;
}

export function shortcutName(shortcut) {
  if (!shortcut) return '';
  return shortcut.buttons.map((b) => (shortcut.mapping === 'standard' && NAMES[b]) || `Button ${b}`).join(' + ');
}

/** The pads that are really there: getGamepads() keeps null holes and, on some browsers, ghosts. */
export function livePads(list) {
  return Array.from(list || []).filter((p) => p && p.connected !== false && p.buttons && typeof p.buttons.length === 'number');
}

export function pressed(pad) {
  const out = [];
  for (let i = 0; i < pad.buttons.length; i++) if (pad.buttons[i] && pad.buttons[i].pressed) out.push(i);
  return out;
}

function fits(shortcut, pad) {
  const mapping = pad.mapping === 'standard' ? 'standard' : '';
  if (mapping !== shortcut.mapping) return false;
  return mapping === 'standard' || (typeof pad.id === 'string' && pad.id.slice(0, 120) === shortcut.id);
}

/** Learning a shortcut: whatever one pad holds, unchanged, for HOLD_MS. step() answers
 * { buttons, mapping, id } once (then waits for every button to be let go), or { refused } for a hold
 * that cannot be a shortcut, or null. Pads are matched by what they are, not their index, which a
 * reconnect may change. */
export function createLearner({ holdMs = HOLD_MS } = {}) {
  let held = null, since = 0, spent = false;
  return {
    step(pads, now) {
      const busy = livePads(pads).map((pad) => ({ pad, buttons: pressed(pad) })).filter((x) => x.buttons.length);
      if (!busy.length) { held = null; spent = false; return null; }
      if (spent) return null;
      const { pad, buttons } = busy.reduce((a, b) => (b.buttons.length > a.buttons.length ? b : a));
      const key = `${pad.id}|${buttons.join(',')}`;
      if (!held || held !== key) { held = key; since = now; return null; }
      if (now - since < holdMs) return null;
      spent = true;
      const why = refusal(buttons);
      if (why) return { refused: why, buttons };
      const mapping = pad.mapping === 'standard' ? 'standard' : '';
      return { buttons, mapping, id: mapping ? '' : String(pad.id || '').slice(0, 120) };
    },
  };
}

/** Watching for the shortcut: true once when every one of its buttons is held on a fitting pad for
 * HOLD_MS, then not again until they are let go. A hold that started while the page was away
 * (stale polling, sleep) starts its clock when it is first seen, never earlier. */
export function createWatcher(shortcut, { holdMs = HOLD_MS } = {}) {
  let since = null, spent = false;
  return {
    step(pads, now) {
      const down = shortcut && livePads(pads).some((pad) => fits(shortcut, pad)
        && shortcut.buttons.every((b) => pad.buttons[b] && pad.buttons[b].pressed));
      if (!down) { since = null; spent = false; return false; }
      if (spent) return false;
      if (since === null) { since = now; return false; }
      if (now - since < holdMs) return false;
      spent = true;
      return true;
    },
    reset() { since = null; spent = false; },
  };
}

/** The newest input any live pad reports (Gamepad.timestamp), to tell a controller in use from one
 * left on the sofa. */
export function lastInput(pads) {
  return livePads(pads).reduce((t, p) => Math.max(t, Number(p.timestamp) || 0), 0);
}

/** Is the floating button hidden? Only by the person's own choice, with a shortcut that has worked,
 * while a controller that fits it is connected and has been used lately. Anything else, including a
 * disconnect, an unreadable Gamepad API or a page that has not polled yet, shows the button. */
export function fabHidden(pref, pads, { idleMs = 0, idleLimit = IDLE_MS } = {}) {
  if (!pref || !pref.hide || !pref.verified || !pref.shortcut) return false;
  if (!livePads(pads).some((pad) => fits(pref.shortcut, pad))) return false;
  return idleMs < idleLimit;
}

/** What the drawer's Controller line says. phase: 'idle' | 'learning' | 'verifying' | 'refused'. */
export function padLine({ pref, connected, phase, candidate }) {
  if (phase === 'learning') return 'Hold the controller’s Home button, or two buttons together, for a second.';
  if (phase === 'refused') return 'One button alone could be a game move. Hold two buttons together, ones the game doesn’t use together.';
  if (phase === 'verifying') return `Now hold ${shortcutName(candidate)} again to check it opens this menu.`;
  if (pref.verified) {
    return connected ? `Hold ${shortcutName(pref.shortcut)} to open this menu.`
      : `Shortcut: ${shortcutName(pref.shortcut)}. Connect the controller to use it.`;
  }
  return connected ? 'A controller is connected. The Party button stays on screen.' : '';
}
