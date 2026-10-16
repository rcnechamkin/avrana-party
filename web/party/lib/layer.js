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

import { BUTTON, LAYER_PROTOCOL as PROTOCOL, layerBox } from '../bridge/layer-mount.js';

export { PROTOCOL, layerBox };
export const LONG_PRESS_MS = 400;
export const SLOP = 8;                     // px a finger may move and still be a tap
export const FLING = 1.0;                  // px/ms toward an edge that throws the button into it
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

/** Where the button settles when a drag ends: the nearer side, or tucked into it.
 * x, y: the button's top-left at release; vx: horizontal speed in px/ms (+ is rightward). */
export function settle({ x, y, vx = 0 }, vp) {
  const center = x + BUTTON / 2;
  const side = center < vp.w / 2 ? 'left' : 'right';
  const toward = side === 'left' ? -vx : vx;
  const past = side === 'left' ? x < 0 - BUTTON / 4 : x + BUTTON > vp.w + BUTTON / 4;
  const flung = toward >= FLING;
  return { mode: past || flung ? 'tab' : 'button', side, y };
}

/** The first place: kept from last time on this phone, else the right edge a third of the way down. */
export function initialPlace(kept, vp) {
  if (kept && SIDES.includes(kept.side) && num(kept.y) && (kept.mode === 'button' || kept.mode === 'tab')) {
    return { mode: kept.mode, side: kept.side, y: kept.y };
  }
  return { mode: 'button', side: 'right', y: Math.round(vp.h / 3) };
}

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
