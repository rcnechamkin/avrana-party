// Limited Mode (ADR 0012): the same party, reached over plain HTTP when trusted HTTPS is not
// available. Pure: no DOM, no network, no storage. The mode comes only from Party Core's view
// (`view.mode`, set by the listener the request arrived on), never from the address bar or the
// user agent; what is missing on this phone comes from the capability report.
import { evaluateSeat, explain } from './evaluate.js';

export const FULL = 'full';
export const LIMITED = 'limited';

/** How this phone reaches the party. Anything but Party Core saying "limited" is Full Mode. */
export function modeOf(view) {
  return view && view.mode === LIMITED ? LIMITED : FULL;
}

const status = (caps, name) => {
  const value = caps ? caps[name] : undefined;
  return value && typeof value === 'object' ? value.status : value;
};

/** The banner: what Limited Mode means on this phone, in plain words. It never imitates a
 * padlock and never hides a browser warning.
 *   caps:    { name: 'yes'|'no'|… } or the capability report's caps
 *   blocked: names of installed games this phone cannot play here (see seatLimits) */
export function limitedNotice({ caps = {}, blocked = [] } = {}) {
  const missing = [];
  if (status(caps, 'wake_lock') !== 'yes') missing.push('The screen may dim while you play. Keep it on yourself.');
  if (status(caps, 'service_worker') !== 'yes') missing.push('The Party page is not saved on this phone.');
  if (blocked.length) {
    const names = blocked.slice(0, 3).join(', ') + (blocked.length > 3 ? ' and others' : '');
    missing.push(`${names}: not playable on this phone until the full version is back.`);
  }
  return {
    title: 'Limited Mode',
    intro: 'This connection is not private. Other people on this Wi-Fi could see what this phone sends. The party, the host and the games still work.',
    missing,
    restore: 'The full version comes back when the Party box’s owner renews its certificate.',
  };
}

/** What this phone may choose for a round of `game`: { play, watch, why }. One seat, one
 * decision (ADR 0012 decision 3): a phone that cannot play a game here watches it or is told
 * why, and nobody else's choice changes. */
export function seatLimits(game, caps, labels = {}) {
  const result = evaluateSeat(game, caps, 'player');
  if (result.outcome === 'watch') return { play: false, watch: true, why: explain(result, labels) };
  if (result.outcome === 'unavailable') {
    const watch = evaluateSeat(game, caps, 'spectator').outcome !== 'unavailable';
    return { play: false, watch, why: explain(result, labels) };
  }
  return { play: true, watch: true, why: '' };
}

/** Names of the installed games this phone cannot play. */
export function blockedGames(games, caps) {
  return games.filter((g) => g.installed && g.entry && !seatLimits(g, caps).play).map((g) => g.name);
}
