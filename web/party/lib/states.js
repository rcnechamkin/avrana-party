// The states the shell says out loud: this phone losing the Party box, the Host going away and
// hosting passing on, and trouble on the box that changes what can be played. Pure: no DOM, no
// network, no storage. Every sentence here is made from what Party Core, the status document or
// the catalog already say; nothing is counted down and nobody is named as next (the view carries
// neither: docs/design/ux-redesign/BACKEND-GAPS.md D9).

/** How long "Reconnecting" is said before the phone says it lost the Party box (the owner,
 * 2026-10-06: about ten seconds). The phone keeps trying either way. */
export const LOST_AFTER_MS = 10000;

/** How this phone reaches Party Core: 'ok', 'reconnecting' (it stopped answering a moment ago)
 * or 'lost' (it has not answered for LOST_AFTER_MS). `failingSince`: when the first try in a row
 * failed (ms), or null while it answers. */
export function linkState(failingSince, now) {
  if (failingSince === null || failingSince === undefined) return 'ok';
  return now - failingSince >= LOST_AFTER_MS ? 'lost' : 'reconnecting';
}

/** The words for a link that is not 'ok'.
 *   answered: something on the box answered, only not the Party (it is restarting);
 *   host:     this phone was the Host when it last heard (its role passes on by Party Core's rule);
 *   brief:    said on a briefing, where a person has an answer in.
 * Returns { title, text, retry } or null. `title` is only for the lost state. */
export function linkWords({ link, answered = false, host = false, brief = false } = {}) {
  if (link === 'reconnecting') {
    return { title: '', text: brief ? 'Reconnecting. Your answer stays as it is for now.' : 'Reconnecting. What you see may be out of date.', retry: false };
  }
  if (link !== 'lost') return null;
  const passes = host ? ' Hosting passes on if it stays away.' : '';
  return answered
    ? { title: 'The Party box isn’t answering', text: 'It may be restarting.' + passes, retry: true }
    : { title: 'This phone lost the Party box', text: 'Check it’s on the Avrana Party Wi-Fi.' + passes, retry: true };
}

const hostOf = (view) => (view && Array.isArray(view.members) ? view.members.find((m) => m.host) || null : null);

/** The Host, when Party Core says they are away: the member, or null. Never this phone (a phone
 * that is asking is here), and never a Host who holds a place in the round that is on: Party
 * Core reports that Host as playing, and the role does not move (core.py, the in-round
 * exception). */
export function awayHost(view) {
  const host = hostOf(view);
  if (!host || host.presence !== 'away') return null;
  if (view.me && view.me.id === host.id) return null;
  return host;
}

/** Hosting changed hands between two views of the same Party: { to, from, mine, wasAway }, or
 * null. `wasAway` is true only when the earlier view said the old Host was away, so "has been
 * away" is never said of a Host who left or handed the role over. A phone that slept through it
 * compares with the last view it had, and is told when it wakes; a phone that has just arrived
 * has no earlier view and is told nothing: there is nothing to tell from. */
export function hostPassed(previous, view) {
  if (!previous || !view || previous.party !== view.party) return null;
  const was = hostOf(previous), now = hostOf(view);
  if (!was || !now || was.id === now.id) return null;
  return { to: now.name, from: was.name, mine: Boolean(view.me && view.me.id === now.id), wasAway: was.presence === 'away' };
}

/** What to say about the Host where the rule applies (Home, the Party page):
 *   { kind: 'away' | 'passed', icon, title, text, mine } or null.
 * A hand-over that reached this phone is a notice it may dismiss (`mine`). */
export function hostNote({ away = null, passed = null } = {}) {
  if (away) return { kind: 'away', icon: 'moon-star', title: '', text: `Hosting passes to someone here if ${away.name} isn’t back soon.`, mine: false };
  if (!passed) return null;
  if (passed.mine) {
    return { kind: 'passed', icon: 'arrow-up-down', title: 'You’re hosting now', mine: true,
      text: passed.wasAway ? `${passed.from} has been away, so you pick what the Party plays.` : 'You pick what the Party plays.' };
  }
  return { kind: 'passed', icon: 'arrow-up-down', title: '', mine: false,
    text: `${passed.to} is hosting now.` + (passed.wasAway ? ` ${passed.from} has been away.` : '') };
}

/** The briefing's one line under the choices. Party Core's own blocker sentence is the Host's;
 * everyone else reads who they are waiting for.
 *   panel: lib/party-mode.js setupPanel; away, passed: as above. */
export function briefLine(panel, { away = null, passed = null } = {}) {
  if (!panel) return '';
  if (panel.starting) return 'Starting…';
  const lead = !passed ? '' : passed.mine ? 'You’re hosting now. ' : `${passed.to} is hosting now. `;
  if (panel.host) return (lead + (panel.blocker || '')).trim();
  if (away) return `${away.name}, the Host, is away, so the game can’t start yet. Hosting passes to someone here if ${away.name} isn’t back soon.`;
  return lead + (panel.hostName ? `Waiting for ${panel.hostName} to start` : 'Nobody is hosting right now.');
}

const listed = (names) => (names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`);

/** Trouble on the Party box that changes what can be played, for the Host: from the status
 * document's structured fields (avrana.status/v0: `arcade`, `games_provider`), never from its
 * operator sentences, and the catalog's own titles. Only a part that has installed titles can be
 * "off". Returns [{ id, title, text, detail }]: `text` for the notice on Home, `detail` for System.
 * A certificate that has run out is not here: every phone it touches is in Limited Mode and is
 * told so by that notice. */
export function troubles(status, games = []) {
  if (!status || typeof status !== 'object') return [];
  const installed = games.filter((g) => g.installed && g.entry);
  const arcade = installed.filter((g) => !g.legacySlug), cards = installed.filter((g) => g.legacySlug);
  const a = status.arcade, p = status.games_provider;
  const arcadeOff = arcade.length > 0 && Boolean(a) && (a.ok === false || a.emulator_running === false || Boolean(a.error));
  const cardsOff = cards.length > 0 && Boolean(p) && p.ok === false;
  const cannot = (list) => `${listed(list.map((g) => g.name))} can’t be played.`;
  if (arcadeOff && cardsOff) {
    return [{ id: 'games', title: 'Games are off right now', text: 'No game can be started.',
      detail: `The parts of the Party box that run the games aren’t answering. ${cannot(installed)}` }];
  }
  if (arcadeOff) {
    return [{ id: 'arcade', title: 'Arcade games are off right now', text: cards.length ? 'Card and party games play as usual.' : '',
      detail: `The arcade part of the Party box isn’t answering. ${cannot(arcade)}` + (cards.length ? ' Card and party games are not affected.' : '') }];
  }
  if (cardsOff) {
    return [{ id: 'cards', title: 'Card and party games are off right now', text: arcade.length ? 'Arcade games play as usual.' : '',
      detail: `The part of the Party box that runs them isn’t answering. ${cannot(cards)}` + (arcade.length ? ' Arcade games are not affected.' : '') }];
  }
  return [];
}

/** System's health line for a phone that is not the Host, from what its own shelf already shows
 * (the titles marked "Off for now"). `off`: their names; `others`: how many other installed
 * titles there are. Returns { title, text } or null. */
export function offLine(off = [], others = 0) {
  if (!off.length) return null;
  return { title: `${listed(off)} ${off.length === 1 ? 'is' : 'are'} off for now`, text: others > 0 ? (others === 1 ? 'The other game plays as usual.' : 'Every other game plays as usual.') : '' };
}

/** System's one quiet line when nothing is wrong. `phone`: this phone has everything it needs. */
export function fineLine(phone) {
  return phone ? { title: 'Everything’s working', text: 'The Party box and this phone are fine.' }
    : { title: 'The Party box is working', text: 'Some things are limited on this phone.' };
}
