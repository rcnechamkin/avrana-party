// Tier 1 (node --test): the Library's shelf (web/party/lib/library.js). What is listed, in what
// order, under which heading, and the words that say why. The rule under test: the size of the
// party orders the shelf and never empties it; only a filter, a search or a tab leaves a title out.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PLAYER_CHOICES, SCREEN_CHOICES, SCREEN_NAMES, TABS, VIEWS, VIEW_NAMES, arrange, consequence, countWord, filterLabel,
  filterWords, fits, homeShelves, leadLine, seatsMark, seatsPhrase, viewOf } from '../../web/party/lib/library.js';
import { screenText } from '../../web/party/lib/ui.js';
import { visibleGames } from '../../web/party/lib/catalog-view.js';

const catalog = JSON.parse(readFileSync(new URL('../../web/party/catalog.json', import.meta.url), 'utf8'));
const html = readFileSync(new URL('../../web/party/index.html', import.meta.url), 'utf8');
const all = visibleGames(catalog);                     // the five real titles; nothing here is invented
const game = (id) => all.find((g) => g.id === id);
const ids = (games) => games.map((g) => g.id);
const shelf = (opts = {}) => arrange({ all, ...opts });

test('the shelf is the real catalog: five titles, two of them not installed', () => {
  assert.deepEqual(ids(all), ['bluff', 'expo', 'arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms']);
  assert.deepEqual(ids(all.filter((g) => !g.installed)), ['ps1-bomberman', 'ps1-worms']);
});

test('a stored view is one of four, and anything else is the medium grid', () => {
  assert.deepEqual(VIEWS, ['large', 'medium', 'compact', 'list']);
  for (const view of VIEWS) { assert.equal(viewOf(view), view); assert.ok(VIEW_NAMES[view]); }
  for (const odd of [null, undefined, '', 'huge', 'List', 7, '__proto__']) assert.equal(viewOf(odd), 'medium', String(odd));
});

test('the page offers exactly the choices the shelf understands', () => {
  for (const view of VIEWS) assert.match(html, new RegExp(`data-v="${view}"`));
  for (const tab of TABS) assert.match(html, new RegExp(`data-view="${tab}"`));
  for (const n of PLAYER_CHOICES) assert.match(html, new RegExp(`data-players="${n}"`));
  for (const screen of SCREEN_CHOICES) assert.match(html, new RegExp(`data-screen="${screen}"[^>]*>\\s*${SCREEN_NAMES[screen]}\\s*<`));
  assert.equal((html.match(/data-players="/g) || []).length, PLAYER_CHOICES.length);
  assert.equal((html.match(/data-screen="/g) || []).length, SCREEN_CHOICES.length);
});

test('the screen filter uses the words the titles themselves use', () => {
  assert.equal(SCREEN_NAMES.phone, screenText({ screen: 'no_tv_needed' }).text);
  assert.equal(SCREEN_NAMES.tv_optional, screenText({ screen: 'tv_optional' }).text);
  assert.equal(SCREEN_NAMES.tv_required, screenText({ screen: 'tv_required' }).text);
});

test('the corner mark is the player range, or why this many people do not fit', () => {
  assert.equal(countWord(4), 'four');
  assert.equal(countWord(13), '13');
  assert.equal(fits(game('bluff'), 4), true);
  assert.equal(fits(game('arcade-gauntlet2'), 4), false);
  assert.deepEqual(seatsMark(game('bluff'), 4), { ok: true, text: '2–6' });
  assert.deepEqual(seatsMark(game('arcade-gauntlet2'), 4), { ok: false, text: 'Max 2' });
  assert.deepEqual(seatsMark({ players: { min: 3, max: 8 } }, 2), { ok: false, text: 'Needs 3' });
  assert.deepEqual(seatsMark({ players: { min: 2, max: 2 } }, 2), { ok: true, text: '2' });
  // one phone, or no party at all, is told nothing is wrong: there is nobody to leave out yet
  for (const people of [0, 1]) assert.equal(seatsMark(game('bluff'), people).ok, true, String(people));
  assert.equal(seatsPhrase(game('bluff'), 4), '2–6');
  assert.equal(seatsPhrase(game('arcade-gauntlet2'), 4), 'Max 2, you’re 4');
});

test('filters in words, and the filter button says how many are on', () => {
  assert.deepEqual(filterWords(), []);
  assert.deepEqual(filterWords({ players: 1 }), ['1 player']);
  assert.deepEqual(filterWords({ players: 4, screen: 'tv_optional' }), ['4 players', 'TV optional']);
  assert.deepEqual(filterWords({ players: 6, screen: 'any' }), ['6 or more players']);
  assert.equal(filterLabel({ players: 0, screen: 'any' }), 'Filters');
  assert.equal(filterLabel({ players: 4, screen: 'any' }), 'Filters, 1 on: 4 players');
  assert.equal(filterLabel({ players: 2, screen: 'phone' }), 'Filters, 2 on: 2 players, Phone only');
});

test('one consequence line per title, the most decisive first', () => {
  const up = { running: true }, down = { running: false };
  assert.equal(consequence({ installed: true, outcome: 'ready', live: up }), null);
  assert.equal(consequence({ installed: true, outcome: 'limited', live: null }), null);       // unknown is not "off"
  assert.equal(consequence({ installed: true, outcome: 'ready', live: undefined }), null);
  assert.deepEqual(consequence({ installed: true, outcome: 'watch', live: up }), { kind: 'watch', icon: 'eye', text: 'Watch only on this phone' });
  assert.equal(consequence({ installed: true, outcome: 'unavailable', live: up }).text, 'Not on this phone');
  assert.equal(consequence({ installed: true, outcome: 'ready', live: down }).text, 'Off for now');
  assert.equal(consequence({ installed: true, outcome: 'ready', live: { running: true, integration: false } }).text, 'Off for now');
  // off beats what this phone could do; not installed beats everything
  assert.equal(consequence({ installed: true, outcome: 'unavailable', live: down }).kind, 'off');
  assert.equal(consequence({ installed: false, outcome: 'unavailable', live: down }).text, 'Not installed');
  for (const c of [{ installed: false }, { installed: true, live: down }, { installed: true, outcome: 'watch' }, { installed: true, outcome: 'unavailable' }])
    assert.match(consequence(c).icon, /^[a-z-]+$/);                                         // never colour alone
});

test('the size of the party orders and groups the shelf; it never leaves a title out', () => {
  for (const people of [0, 1]) {
    const one = shelf({ people });
    assert.deepEqual(one.groups.map((g) => [g.title, g.meta]), [['All games', '5']]);
    assert.deepEqual(ids(one.flat), ids(all));
  }
  for (let people = 2; people <= 12; people++) {
    const s = shelf({ people });
    assert.equal(s.count, 5, `${people} people`);
    assert.equal(s.hidden, 0);
    assert.equal(s.empty, null);
    assert.equal(s.flat.length, 5);
    assert.equal(s.groups.reduce((n, g) => n + g.games.length, 0), 5);
  }
  const four = shelf({ people: 4 });
  assert.deepEqual(four.groups.map((g) => [g.title, g.meta, ids(g.games)]), [
    ['Great for four', '4', ['bluff', 'expo', 'ps1-bomberman', 'ps1-worms']],
    ['Not for four', '1', ['arcade-gauntlet2']]]);
  assert.deepEqual(ids(four.flat), ['bluff', 'expo', 'ps1-bomberman', 'ps1-worms', 'arcade-gauntlet2']);   // best fit first
  const two = shelf({ people: 2 });
  assert.deepEqual(two.groups.map((g) => g.title), ['Great for two']);                    // no empty second shelf
  const nine = shelf({ people: 9 });
  assert.deepEqual(nine.groups.map((g) => [g.title, g.meta]), [['Not for nine', '5']]);   // still all five
});

test('a filter leaves titles out, says so, and its count, heading and hidden number agree', () => {
  const four = shelf({ people: 4, filters: { players: 4, screen: 'any' } });
  assert.equal(four.total, 5);
  assert.equal(four.count, 4);
  assert.equal(four.hidden, 1);
  assert.equal(four.filtersOn, 1);
  assert.deepEqual(four.groups.map((g) => [g.title, g.reset, g.games.length]), [['4 games for 4 players', true, 4]]);
  assert.equal(four.count + four.hidden, four.total);
  const both = shelf({ filters: { players: 2, screen: 'phone' } });
  assert.deepEqual(ids(both.flat), ['bluff', 'expo']);
  assert.equal(both.groups[0].title, '2 games for 2 players, Phone only');
  assert.equal(both.hidden, 3);
  assert.equal(both.filtersOn, 2);
  assert.deepEqual(ids(shelf({ filters: { players: 6 } }).flat), ['bluff']);              // "6 or more" is a title that seats six
  assert.equal(shelf({ filters: { players: 6 } }).groups[0].title, '1 game for 6 or more players');
  assert.deepEqual(ids(shelf({ filters: { players: 1 } }).flat), ['arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms']);
  assert.deepEqual(ids(shelf({ filters: { screen: 'tv_optional' } }).flat), ['arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms']);
  // a title that is off or not installed is still listed: only an explicit filter leaves one out
  assert.ok(ids(shelf({ filters: { players: 4 } }).flat).includes('ps1-worms'));
});

test('nothing to show always says why, and offers the way back', () => {
  const none = shelf({ filters: { players: 6, screen: 'tv_required' } });
  assert.deepEqual([none.count, none.hidden, none.groups.length], [0, 5, 0]);
  assert.deepEqual(none.empty, { kind: 'filters', icon: 'filter-x', title: 'No games match these filters',
    text: '6 or more players, Needs the TV', action: 'Reset filters' });
  const search = shelf({ query: '  chess ' });
  assert.equal(search.empty.kind, 'search');
  assert.equal(search.empty.title, 'Nothing matches “chess”');
  assert.equal(search.empty.text, 'The Library has 5 games.');
  assert.equal(search.empty.action, 'Clear search');
  assert.equal(shelf({ tab: 'favorites' }).empty.title, 'No favorites yet');
  assert.equal(shelf({ tab: 'favorites' }).empty.action, 'See all games');
  assert.equal(shelf({ tab: 'recent' }).empty.title, 'Nothing played yet');
  // a search that finds a title the filter then leaves out is the filter's doing, and says so
  const found = shelf({ query: 'gauntlet', filters: { players: 4 } });
  assert.equal(found.empty.kind, 'filters');
  assert.equal(found.hidden, 1);
  // favourites that the filter hides are not "no favourites"
  const fav = shelf({ tab: 'favorites', favorites: ['arcade-gauntlet2'], filters: { players: 4 } });
  assert.equal(fav.empty.kind, 'filters');
  // and no catalog at all is not an empty search: the page says the list is unavailable itself
  assert.equal(arrange({ all: [] }).empty, null);
  assert.equal(arrange({ all: [], query: 'x', filters: { players: 4 } }).empty, null);
});

test('search, favourites and recents each get their own heading; recents are newest first', () => {
  const found = shelf({ people: 4, query: 'CARD' });                                       // summary and category count
  assert.deepEqual(found.groups.map((g) => [g.title, g.meta]), [['Search results', String(found.count)]]);
  assert.ok(ids(found.flat).includes('bluff') && ids(found.flat).includes('expo'));
  const key = (g) => `avrana:${g.id}`;
  const fav = shelf({ tab: 'favorites', keyOf: key, favorites: ['avrana:expo', 'avrana:ps1-worms', 'gone:title'] });
  assert.deepEqual([fav.groups[0].title, ids(fav.flat)], ['Favorites', ['expo', 'ps1-worms']]);
  const recent = shelf({ people: 4, tab: 'recent', keyOf: key, recent: ['avrana:arcade-gauntlet2', 'avrana:bluff'] });
  assert.deepEqual([recent.groups[0].title, ids(recent.flat)], ['Recently played', ['arcade-gauntlet2', 'bluff']]);
  assert.equal(recent.hidden, 0);                                                          // a tab is not a hidden filter
});

test('Home leads with the last title played here, else the first that suits the party', () => {
  const key = (g) => `avrana:${g.id}`;
  const fresh = homeShelves({ all, people: 4, keyOf: key });
  assert.equal(fresh.lead.id, 'bluff');
  assert.equal(fresh.leadPlayed, false);
  assert.equal(fresh.title, 'Great for four');
  assert.deepEqual(ids(fresh.great), ['expo', 'ps1-bomberman', 'ps1-worms']);                // the lead is not repeated
  assert.deepEqual(fresh.played, []);
  const back = homeShelves({ all, people: 4, keyOf: key, recent: ['avrana:arcade-gauntlet2', 'gone:title', 'avrana:expo'] });
  assert.equal(back.lead.id, 'arcade-gauntlet2');                                           // played last, even though it seats two
  assert.equal(back.leadPlayed, true);
  assert.deepEqual(ids(back.played), ['arcade-gauntlet2', 'expo']);
  assert.deepEqual(ids(back.great), ['bluff', 'expo', 'ps1-bomberman', 'ps1-worms']);
  const alone = homeShelves({ all, people: 1, keyOf: key });
  assert.equal(alone.title, 'Games');
  assert.deepEqual([alone.lead.id, alone.great.length], ['bluff', 4]);
  assert.equal(homeShelves({ all, people: 9, keyOf: key }).lead.id, 'bluff');               // nothing suits nine: still a way in
  assert.deepEqual(homeShelves({ all: [], people: 4 }), { lead: null, leadPlayed: false, title: 'Great for four', great: [], played: [] });
});

test('the line under Home’s lead title says what is true of it for this party', () => {
  assert.equal(leadLine(game('bluff'), { people: 4, played: true }), 'You played this last. Room for all four of you.');
  assert.equal(leadLine(game('bluff'), { people: 4 }), 'Room for all four of you.');
  assert.equal(leadLine(game('arcade-gauntlet2'), { people: 3 }), 'Up to 2 play; you’re 3.');
  assert.equal(leadLine({ players: { min: 3, max: 8 } }, { people: 2 }), 'Needs 3 or more.');
  assert.equal(leadLine(game('bluff'), { people: 1, played: true }), 'You played this last.');
  assert.equal(leadLine(game('bluff'), { people: 0 }), '');
});
