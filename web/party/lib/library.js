// The Library: what is on the shelf, in what order, and the words that say why. Pure: no DOM, no
// network, no storage.
//
// Recommending is not filtering. The number of people here orders and groups the shelf; nothing is
// left out until a person sets a filter, searches, or opens Favorites or Recent. Everything here
// comes from the catalog and this phone's own report: no lengths, kinds or covers are invented.

export const VIEWS = ['large', 'medium', 'compact', 'list'];
export const VIEW_NAMES = { large: 'Large grid', medium: 'Medium grid', compact: 'Compact grid', list: 'List' };
/** The view a stored value names; anything else is the medium grid. */
export const viewOf = (value) => (VIEWS.includes(value) ? value : 'medium');

export const TABS = ['all', 'favorites', 'recent'];
/** Players filter choices: 0 is Any, 6 is "6 or more". */
export const PLAYER_CHOICES = [0, 1, 2, 3, 4, 5, 6];
export const SCREEN_CHOICES = ['any', 'phone', 'tv_optional', 'tv_required'];
/** The same words the tiles use for where a game is seen (lib/ui.js screenText). */
export const SCREEN_NAMES = { any: 'Any', phone: 'Phone only', tv_optional: 'TV optional', tv_required: 'Needs the TV' };

const COUNT = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'];
/** A small number as a word, inside a sentence: "four". */
export const countWord = (n) => COUNT[n - 1] || String(n);
const games = (n) => (n === 1 ? '1 game' : `${n} games`);

/** Can this many people all play it? */
export function fits(game, people) {
  return game.players.min <= people && people <= game.players.max;
}

/** The mark in a cover's corner: the player range, or why this many people do not fit. */
export function seatsMark(game, people = 0) {
  const { min, max } = game.players;
  if (people >= 2 && people > max) return { ok: false, text: `Max ${max}` };
  if (people >= 2 && people < min) return { ok: false, text: `Needs ${min}` };
  return { ok: true, text: min === max ? String(max) : `${min}–${max}` };
}

/** The same, as a phrase for the list: "2–6", or "Max 2, you’re 4". */
export function seatsPhrase(game, people = 0) {
  const mark = seatsMark(game, people);
  return mark.ok ? mark.text : `${mark.text}, you’re ${people}`;
}

function matchesPlayers(game, players) {
  if (!players) return true;
  return players >= 6 ? game.players.max >= 6 : fits(game, players);
}

function matchesScreen(game, screen) {
  if (!screen || screen === 'any') return true;
  const tv = game.screen === 'tv_required' || game.screen === 'tv_optional';
  return screen === 'phone' ? !tv : game.screen === screen;
}

/** The filters that are on, in words: ["4 players", "TV optional"]. */
export function filterWords({ players = 0, screen = 'any' } = {}) {
  const words = [];
  if (players) words.push(players >= 6 ? 'Room for 6 or more' : players === 1 ? '1 player' : `${players} players`);
  if (screen && screen !== 'any') words.push(SCREEN_NAMES[screen]);
  return words;
}

/** The filter button's name for a screen reader. */
export function filterLabel(filters) {
  const words = filterWords(filters);
  return words.length ? `Filters, ${words.length} on: ${words.join(', ')}` : 'Filters';
}

/** What a title means on this phone right now, when it is not simply playable. One line, the most
 * decisive first; the same words in every view.
 *   installed: the catalog says it is on this Party box
 *   outcome:   what this phone can do with it (ready, limited, watch, unavailable)
 *   live:      the title's live state ({ running, integration, unknown }), or null when it has none.
 *              `unknown` is a question that got no answer at all: that is this phone's connection,
 *              not the game, so it is never "off" */
export function consequence({ installed, outcome, live }) {
  if (!installed) return { kind: 'not_installed', icon: 'circle-slash', text: 'Not installed' };
  if (live && !live.unknown && (live.running === false || live.integration === false)) return { kind: 'off', icon: 'triangle-alert', text: 'Off for now' };
  if (outcome === 'watch') return { kind: 'watch', icon: 'eye', text: 'Watch only on this phone' };
  if (outcome !== 'ready' && outcome !== 'limited') return { kind: 'no', icon: 'triangle-alert', text: 'Not on this phone' };
  return null;
}

function headingFor(count, filters) {
  const { players = 0, screen = 'any' } = filters;
  let text = games(count);
  // "6+" is a title six or more can play; it does not promise room for seven
  if (players) text += players >= 6 ? ' with room for 6 or more' : players === 1 ? ' for 1 player' : ` for ${players} players`;
  if (screen !== 'any') text += `, ${SCREEN_NAMES[screen]}`;
  return text;
}

/** The shelf.
 *   all:      the titles the Library lists (catalog order)
 *   people:   how many are at the party (0 when there is none)
 *   tab:      all | favorites | recent
 *   query:    the search field
 *   filters:  { players, screen }
 *   keyOf:    a title's key in the favourites and recents lists
 *   favorites, recent: those lists (recent is newest first)
 * Returns { total, count, groups: [{ title, meta, reset, games }], flat, hidden, empty, filtersOn }
 * where empty is null or { kind, title, text, action } and hidden is how many the filters left out. */
export function arrange({ all, people = 0, tab = 'all', query = '', filters = {}, keyOf = (g) => g.id, favorites = [], recent = [] }) {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const words = filterWords(filters);
  const inTab = all.filter((g) => tab === 'favorites' ? favorites.includes(keyOf(g))
    : tab === 'recent' ? recent.includes(keyOf(g)) : true);
  if (tab === 'recent') inTab.sort((a, b) => recent.indexOf(keyOf(a)) - recent.indexOf(keyOf(b)));
  const found = inTab.filter((g) => {
    const text = [g.name, g.summary, g.category].filter(Boolean).join(' ').toLowerCase();
    return terms.every((term) => text.includes(term));
  });
  const shown = found.filter((g) => matchesPlayers(g, filters.players) && matchesScreen(g, filters.screen));
  const base = { total: all.length, count: shown.length, hidden: found.length - shown.length, filtersOn: words.length, groups: [], flat: shown, empty: null };

  if (!all.length) return base;                             // no list at all: the page says so itself
  if (!shown.length) {
    if (tab === 'favorites' && !inTab.length) base.empty = { kind: 'favorites', icon: 'heart', title: 'No favorites yet', text: 'Tap the heart on any game to keep it here.', action: 'See all games' };
    else if (tab === 'recent' && !inTab.length) base.empty = { kind: 'recent', icon: 'history', title: 'Nothing played yet', text: 'Games you play on this phone will appear here.', action: 'See all games' };
    else if (terms.length && !found.length) base.empty = { kind: 'search', icon: 'search-x', title: `Nothing matches “${query.trim()}”`, text: `The Library has ${games(all.length)}.`, action: 'Clear search' };
    else base.empty = { kind: 'filters', icon: 'filter-x', title: 'No games match these filters', text: words.join(', '), action: 'Reset filters' };
    return base;
  }
  if (words.length) {
    base.groups = [{ title: headingFor(shown.length, filters), meta: '', reset: true, games: shown }];
  } else if (terms.length) {
    base.groups = [{ title: 'Search results', meta: String(shown.length), games: shown }];
  } else if (tab === 'favorites') {
    base.groups = [{ title: 'Favorites', meta: String(shown.length), games: shown }];
  } else if (tab === 'recent') {
    base.groups = [{ title: 'Recently played', meta: String(shown.length), games: shown }];
  } else if (people >= 2) {
    const great = shown.filter((g) => fits(g, people)), rest = shown.filter((g) => !fits(g, people));
    base.flat = [...great, ...rest];                       // best fit first, nothing left out
    base.groups = [{ title: `Great for ${countWord(people)}`, meta: String(great.length), games: great },
      { title: `Not for ${countWord(people)}`, meta: String(rest.length), games: rest }].filter((g) => g.games.length);
  } else {
    base.groups = [{ title: 'All games', meta: String(shown.length), games: shown }];
  }
  return base;
}

/** Home's shelves, from the same titles: the lead (the last one played on this phone, else the
 * first that suits the party), the rest that suit it, and what was played before that. No title
 * is on Home twice with the lead; `great` may be empty, and then its heading is not shown. */
export function homeShelves({ all, people = 0, keyOf = (g) => g.id, recent = [] }) {
  const recents = recent.map((key) => all.find((g) => keyOf(g) === key)).filter(Boolean);
  const suits = (g) => people < 2 || fits(g, people);
  const lead = recents[0] || all.find((g) => g.installed && suits(g)) || all.find(suits) || all[0] || null;
  const great = all.filter((g) => g !== lead && suits(g));
  return {
    lead, leadPlayed: Boolean(lead && recents[0] === lead),
    title: people >= 2 ? `Great for ${countWord(people)}` : 'Games',
    great, played: recents.filter((g) => g !== lead),
  };
}

/** The line under Home's lead title. */
export function leadLine(game, { people = 0, played = false } = {}) {
  const parts = [];
  if (played) parts.push('You played this last.');
  if (people >= 2) {
    parts.push(fits(game, people) ? `Room for all ${countWord(people)} of you.`
      : people > game.players.max ? `Up to ${game.players.max} play; you’re ${people}.`
        : `Needs ${game.players.min} or more.`);
  }
  return parts.join(' ');
}
