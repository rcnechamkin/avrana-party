// The Party layer over a game (AVR-292; decisions in docs/design/proposals/2026-10-16-control-center.md):
// the pure rules behind the floating Party button and its drawer. No DOM, no network: geometry,
// the protocol between the layer frame and the page that mounts it, and what each role is offered.
//
// The layer is a Party-origin frame (layer.html) that a game page mounts with
// bridge/layer-mount.js. The frame draws everything; the page only places the frame where the
// frame asks, inside its own viewport. Protocol `avrana.party-layer/v1`:
//
//   frame -> page   ready                         the frame is listening
//                   place {mode, side, y}         mode: 'button' | 'tab' | 'open'; side: 'left' |
//                                                 'right'; y: the top, in CSS px of the page
//                   drag {x, y}                   during a drag: the button's top-left
//                   hide                          nothing to show (not a member): the page hides
//                                                 the frame until the next place
//   page -> frame   viewport {w, h, insets}       on load and on every resize; insets: the
//                                                 safe-area insets {top, right, bottom, left}
//
// Nothing else crosses: no view, no names, no message text. A game page learns only that the
// layer opened or closed (the document event 'avrana-party-layer', {open}).

import { locationOf } from './party-mode.js';

import { BUTTON, LAYER_PROTOCOL as PROTOCOL, MARGIN, layerBox } from '../bridge/layer-mount.js';

export { PROTOCOL, layerBox };
export const LONG_PRESS_MS = 400;
export const SLOP = 8;                     // px a finger may move and still be a tap
export const POSITION_KEY = 'avrana-layer-position';

const num = (v) => typeof v === 'number' && Number.isFinite(v);
const keysAre = (o, ...names) => Object.keys(o).sort().join(',') === names.sort().join(',');
const SIDES = ['left', 'right'];

/** A message from the page, checked (for the frame), or null. */
export function parseFromPage(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data) || data.avrana !== PROTOCOL) return null;
  if (data.type !== 'viewport' || !keysAre(data, 'avrana', 'type', 'w', 'h', 'insets')) return null;
  const i = data.insets;
  if (!num(data.w) || !num(data.h) || data.w <= 0 || data.h <= 0 || !i || typeof i !== 'object'
      || !keysAre(i, 'top', 'right', 'bottom', 'left') || ![i.top, i.right, i.bottom, i.left].every((n) => num(n) && n >= 0)) return null;
  return { type: 'viewport', w: data.w, h: data.h, insets: { top: i.top, right: i.right, bottom: i.bottom, left: i.left } };
}

// ---- where the button is (AVR-579) -----------------------------------------------------------------
// The button stays wherever the player lets go of it. Its place is kept per orientation as a
// fraction of the usable area (inside the safe areas), so it survives a rotation, a resize or a
// different phone. Parking on an edge is a deliberate act (the drawer, never a drag or a fling).
export const STEP = 48;                   // px the drawer's and the keys' nudge moves the button
export const DEFAULT_SPOT = { nx: 1, ny: 1 / 3, parked: null };
const orientationOf = (vp) => (vp.w > vp.h ? 'landscape' : 'portrait');
const fraction = (v) => num(v) && v >= 0 && v <= 1;

/** The room the button may sit in: its top-left, inside the safe areas, a margin from the edges. */
export function usable(vp) {
  const i = vp.insets;
  const x0 = i.left + MARGIN, y0 = i.top + MARGIN;
  return { x0, y0, x1: Math.max(x0, vp.w - i.right - MARGIN - BUTTON), y1: Math.max(y0, vp.h - i.bottom - MARGIN - BUTTON) };
}
const clamp01 = (v) => Math.min(1, Math.max(0, v));

/** The button's top-left -> its place as fractions of the usable area. */
export function toSpot({ x, y }, vp, parked = null) {
  const u = usable(vp);
  return { nx: u.x1 > u.x0 ? clamp01((x - u.x0) / (u.x1 - u.x0)) : 0, ny: u.y1 > u.y0 ? clamp01((y - u.y0) / (u.y1 - u.y0)) : 0, parked };
}

/** A place -> the button's top-left on this screen, always inside the usable area. */
export function spotAt(spot, vp) {
  const u = usable(vp);
  return { x: Math.round(u.x0 + clamp01(spot.nx) * (u.x1 - u.x0)), y: Math.round(u.y0 + clamp01(spot.ny) * (u.y1 - u.y0)) };
}

/** The kept places ({portrait, landscape}, each {nx, ny, parked}), checked; anything else is dropped. */
export function keptSpots(kept) {
  const out = {};
  for (const o of ['portrait', 'landscape']) {
    const s = kept && kept[o];
    if (s && fraction(s.nx) && fraction(s.ny) && (s.parked === null || SIDES.includes(s.parked))) out[o] = { nx: s.nx, ny: s.ny, parked: s.parked };
  }
  return out;
}

/** This screen's place: its orientation's own, else the other's carried over, else the first place
 * (the right edge a third of the way down). */
export function spotFor(spots, vp) {
  const o = orientationOf(vp);
  return (spots && (spots[o] || spots[o === 'portrait' ? 'landscape' : 'portrait'])) || DEFAULT_SPOT;
}
export { orientationOf };

/** The page's request for a place: a tab on a side when parked, else the button where it was left. */
export function requestFor(spot, vp) {
  const at = spotAt(spot, vp);
  if (spot.parked) return { type: 'place', mode: 'tab', side: spot.parked, y: at.y };
  return { type: 'drag', x: at.x, y: at.y };
}

/** One step of a non-drag move (the drawer's buttons, the arrow keys). A parked button comes back
 * at its edge first. */
export function nudge(spot, dir, vp, step = STEP) {
  const here = spot.parked ? { ...spot, nx: spot.parked === 'left' ? 0 : 1, parked: null } : spot;
  const at = spotAt(here, vp);
  const d = { up: [0, -step], down: [0, step], left: [-step, 0], right: [step, 0] }[dir];
  return toSpot({ x: at.x + d[0], y: at.y + d[1] }, vp);
}

/** Park on an edge on purpose: a tab at the height it was. */
export const park = (spot, side) => ({ nx: spot.nx, ny: spot.ny, parked: side });

/** The tab, tapped: the button comes back at the edge it was parked on. */
export const unpark = (spot) => ({ nx: spot.parked === 'left' ? 0 : 1, ny: spot.ny, parked: null });

/** Is a pointer gesture a tap (open), a drag (move), or nothing yet? */
export function gesture({ heldMs, moved }) {
  if (heldMs >= LONG_PRESS_MS) return 'drag';
  return moved > SLOP ? 'cancel' : 'tap';
}

/** What this phone is offered in the drawer, from its Party view (Party Core decides every one
 * of them again when it is used). Quit & Spectate is offered only where Party Core allows it:
 * at a round's setup or results (D5b decides the rest).
 * `crossOrigin`: the layer sits on a page of another origin, which owns the frame element and
 * could hide it under a lure (D3 accepted "coverable" for first-party games only). There the
 * layer offers only what bridge v1 already lets a game page do (End, Party Home); handing over
 * hosting and stopping hosting stay on the Party's own pages until the owner widens this. */
export function actions(view, { crossOrigin = false } = {}) {
  const me = view && view.me;
  if (!me) return [];
  const at = locationOf(view).at;
  const out = [];
  if (me.host) {
    if (at === 'game') out.push('end');
    if (at !== 'home') out.push('lobby');
    if (crossOrigin) return out;
    if ((view.members || []).some((m) => m.id !== me.id && (m.presence === 'here' || m.presence === 'playing'))) out.push('handover');
    if (at === 'setup' || at === 'results') out.push('spectate');
  }
  return out;
}

/** Whether the drawer offers a guest "Leave Party…" over a game page of another origin (AVR-580 guest
 * exit). It only asks Party Core; the confirmation is on Party Home, a top-level Party page the game
 * cannot cover, so a lure over this frame can cost a person a trip to Party Home and nothing more.
 * Never the Host's (their Leave names who hosts next, on Party Home), and only during a round or its
 * results; elsewhere the person is on Party Home already. */
export function exitOffered(view, { crossOrigin = false } = {}) {
  const me = view && view.me;
  if (!crossOrigin || !me || me.host) return false;
  return ['game', 'results'].includes(locationOf(view).at);
}

export const ACTION_WORDS = {
  end: { label: 'End the round for everyone', confirm: 'This ends the round for everyone. Everyone goes back to Party Home.', yes: 'End the round' },
  lobby: { label: 'Bring everyone back to Party Home', confirm: 'Everyone goes back to Party Home. A round that is on ends.', yes: 'Bring everyone back' },
  handover: { label: 'Hand over hosting', confirm: 'They will choose what the Party plays.', yes: 'Hand over' },
  spectate: { label: 'Stop hosting and watch', confirm: 'Hosting passes to the next person here. You watch the next round.', yes: 'Stop hosting' },
};

/** The button's name for a screen reader: what it is, and anything new. */
export function buttonLabel(unread = 0) {
  if (unread > 0) return `Your Party, ${unread === 1 ? '1 new message' : `${unread} new messages`}`;
  return 'Your Party';
}

/** One line on the connection, or '' when all is well. */
export function connectionLine({ party, chat }) {
  if (party === 'offline') return 'Not connected to the Party. Trying again…';
  if (chat === 'unavailable') return 'Chat is reconnecting…';
  return '';
}
