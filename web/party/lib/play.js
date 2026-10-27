// PROPOSAL play_shell (AVR-766; draft ADR 0018 revision 3, D5): the round runs inside a Party page.
//
// An installed Party app (manifest scope /party/) leaves its scope when the phone navigates to a
// game on another origin, and iOS then draws its own browser bar over the game. With the proposal
// on, Party Home sends the phone to play.html instead, which stays inside /party/ and frames the
// game on its own origin. This file holds the rules both pages share; no DOM, no state.

export const PROPOSAL = 'play_shell';
export const PLAY_PAGE = 'play.html';
// The game keeps its own origin (its scripts, its socket, its storage) and its forms; it may not
// navigate the Party, open windows or reach anything outside its frame.
export const FRAME_SANDBOX = 'allow-scripts allow-same-origin allow-forms allow-pointer-lock';
export const FRAME_ALLOW = 'autoplay; fullscreen; screen-wake-lock; gamepad';

/** The proposal is switched on in this appliance's party-core.json. */
export function playShellOn(view) {
  return Boolean(view && Array.isArray(view.proposals) && view.proposals.includes(PROPOSAL));
}

/** The address the shell frames for a round target, or null: an absolute http(s) URL on another
 * origin. A same-origin game (BLUFF and EXPO today, Limited Mode) keeps today's top-level page. */
export function frameTarget(to, partyOrigin) {
  if (typeof to !== 'string' || !to) return null;
  let url;
  try { url = new URL(to, partyOrigin); } catch { return null; }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  if (url.origin === partyOrigin || url.username || url.password) return null;
  return url.href;
}

/** Where Party Home sends this phone for a round target: the shell when the proposal is on and
 * the target is framed, otherwise the target itself. */
export function roundAddress(view, to, partyOrigin) {
  return playShellOn(view) && frameTarget(to, partyOrigin) ? PLAY_PAGE : to;
}
