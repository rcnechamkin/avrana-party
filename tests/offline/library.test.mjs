// Tier 1 (node --test): the Library's shelf (web/party/lib/library.js). What is listed, in what
// order, under which heading, and the words that say why. The rule under test: the size of the
// party orders the shelf and never empties it; only a filter, a search or a tab leaves a title out.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PLAYER_CHOICES, SCREEN_CHOICES, SCREEN_NAMES, TABS, VIEWS, VIEW_NAMES, arrange, consequence, countWord, filterLabel, filterWords, fits, homeShelves, leadLine, seatsMark, seatsPhrase, viewOf, fitLine } from '../../web/party/lib/library.js';
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
  assert.equal(fits(game('arcade-gauntlet2'), 4), true);             // four controller seats (AVR-311)
  assert.equal(fits(game('arcade-gauntlet2'), 5), false);
  assert.deepEqual(seatsMark(game('bluff'), 4), { ok: true, text: '2–6' });
  assert.deepEqual(seatsMark(game('arcade-gauntlet2'), 4), { ok: true, text: '1–4' });
  assert.deepEqual(seatsMark(game('arcade-gauntlet2'), 5), { ok: false, text: 'Max 4' });
  assert.deepEqual(seatsMark({ players: { min: 3, max: 8 } }, 2), { ok: false, text: 'Needs 3' });
  assert.deepEqual(seatsMark({ players: { min: 2, max: 2 } }, 2), { ok: true, text: '2' });
  // one phone, or no party at all, is told nothing is wrong: there is nobody to leave out yet
  for (const people of [0, 1]) assert.equal(seatsMark(game('bluff'), people).ok, true, String(people));
  assert.equal(seatsPhrase(game('bluff'), 4), '2–6');
  assert.equal(seatsPhrase(game('arcade-gauntlet2'), 4), '1–4');
  assert.equal(seatsPhrase(game('arcade-gauntlet2'), 5), 'Max 4, you’re 5');
});

test('filters in words, and the filter button says how many are on', () => {
  assert.deepEqual(filterWords(), []);
  assert.deepEqual(filterWords({ players: 1 }), ['1 player']);
  assert.deepEqual(filterWords({ players: 4, screen: 'tv_optional' }), ['4 players', 'TV optional']);
  assert.deepEqual(filterWords({ players: 6, screen: 'any' }), ['Room for 6 or more']);
  assert.equal(filterLabel({ players: 0, screen: 'any' }), 'Filters');
  assert.equal(filterLabel({ players: 4, screen: 'any' }), 'Filters, 1 on: 4 players');
  assert.equal(filterLabel({ players: 2, screen: 'phone' }), 'Filters, 2 on: 2 players, Phone only');
});

test('one consequence line per title, the most decisive first', () => {
  const up = { running: true }, down = { running: false };
  assert.equal(consequence({ installed: true, outcome: 'ready', live: up }), null);
  assert.equal(consequence({ installed: true, outcome: 'limited', live: null }), null);       // unknown is not "off"
  assert.equal(consequence({ installed: true, outcome: 'ready', live: undefined }), null);
  // a question nobody answered is this phone's connection, not the game: never "off"
  assert.equal(consequence({ installed: true, outcome: 'ready', live: { running: false, unknown: true } }), null);
  assert.equal(consequence({ installed: true, outcome: 'watch', live: { running: false, unknown: true } }).kind, 'watch');
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
  const four = shelf({ people: 4 });                                                    // all five seat four
  assert.deepEqual(four.groups.map((g) => [g.title, g.meta]), [['Great for four', '5']]);
  const five = shelf({ people: 5 });
  assert.deepEqual(five.groups.map((g) => [g.title, g.meta, ids(g.games)]), [
    ['Great for five', '2', ['bluff', 'expo']],
    ['Not for five', '3', ['arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms']]]);
  // best fit first, nothing left out: the titles that seat five come before the ones that do not
  const reordered = [game('ps1-worms'), game('bluff'), game('arcade-gauntlet2'), game('expo'), game('ps1-bomberman')];
  assert.deepEqual(ids(arrange({ all: reordered, people: 5 }).flat), ['bluff', 'expo', 'ps1-worms', 'arcade-gauntlet2', 'ps1-bomberman']);
  const two = shelf({ people: 2 });
  assert.deepEqual(two.groups.map((g) => g.title), ['Great for two']);                    // no empty second shelf
  const nine = shelf({ people: 9 });
  assert.deepEqual(nine.groups.map((g) => [g.title, g.meta]), [['Not for nine', '5']]);   // still all five
});

test('a filter leaves titles out, says so, and its count, heading and hidden number agree', () => {
  const five = shelf({ people: 5, filters: { players: 5, screen: 'any' } });
  assert.equal(five.total, 5);
  assert.equal(five.count, 2);
  assert.equal(five.hidden, 3);
  assert.equal(five.filtersOn, 1);
  assert.deepEqual(five.groups.map((g) => [g.title, g.reset, g.games.length]), [['2 games for 5 players', true, 2]]);
  assert.equal(five.count + five.hidden, five.total);
  const four = shelf({ people: 4, filters: { players: 4, screen: 'any' } });              // Gauntlet II seats four now
  assert.deepEqual([four.count, four.hidden], [5, 0]);
  const both = shelf({ filters: { players: 2, screen: 'phone' } });
  assert.deepEqual(ids(both.flat), ['bluff', 'expo']);
  assert.equal(both.groups[0].title, '2 games for 2 players, Phone only');
  assert.equal(both.hidden, 3);
  assert.equal(both.filtersOn, 2);
  assert.deepEqual(ids(shelf({ filters: { players: 6 } }).flat), ['bluff']);              // "6 or more" is a title that seats six
  assert.equal(shelf({ filters: { players: 6 } }).groups[0].title, '1 game with room for 6 or more');   // not "for seven"
  assert.equal(arrange({ all: [...all, { ...game('bluff'), id: 'big', players: { min: 4, max: 10 } }], filters: { players: 6 } }).groups[0].title,
    '2 games with room for 6 or more');
  assert.deepEqual(ids(shelf({ filters: { players: 1 } }).flat), ['arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms']);
  assert.deepEqual(ids(shelf({ filters: { screen: 'tv_optional' } }).flat), ['arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms']);
  // a title that is off or not installed is still listed: only an explicit filter leaves one out
  assert.ok(ids(shelf({ filters: { players: 4 } }).flat).includes('ps1-worms'));
});

test('nothing to show always says why, and offers the way back', () => {
  const none = shelf({ filters: { players: 6, screen: 'tv_required' } });
  assert.deepEqual([none.count, none.hidden, none.groups.length], [0, 5, 0]);
  assert.deepEqual(none.empty, { kind: 'filters', icon: 'filter-x', title: 'No games match these filters',
    text: 'Room for 6 or more, Needs the TV', action: 'Reset filters' });
  const search = shelf({ query: '  chess ' });
  assert.equal(search.empty.kind, 'search');
  assert.equal(search.empty.title, 'Nothing matches “chess”');
  assert.equal(search.empty.text, 'The Library has 5 games.');
  assert.equal(search.empty.action, 'Clear search');
  assert.equal(shelf({ tab: 'favorites' }).empty.title, 'No favorites yet');
  assert.equal(shelf({ tab: 'favorites' }).empty.action, 'See all games');
  assert.equal(shelf({ tab: 'recent' }).empty.title, 'Nothing played yet');
  // a search that finds a title the filter then leaves out is the filter's doing, and says so
  const found = shelf({ query: 'gauntlet', filters: { players: 5 } });
  assert.equal(found.empty.kind, 'filters');
  assert.equal(found.hidden, 1);
  // favourites that the filter hides are not "no favourites"
  const fav = shelf({ tab: 'favorites', favorites: ['arcade-gauntlet2'], filters: { players: 5 } });
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
  assert.deepEqual(ids(fresh.great), ['expo', 'arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms']);   // the lead is not repeated
  assert.deepEqual(fresh.played, []);
  const back = homeShelves({ all, people: 5, keyOf: key, recent: ['avrana:arcade-gauntlet2', 'gone:title', 'avrana:expo'] });
  assert.equal(back.lead.id, 'arcade-gauntlet2');                                           // played last, even though it seats four
  assert.equal(back.leadPlayed, true);
  assert.deepEqual(ids(back.played), ['expo']);                                             // the lead is not listed again
  assert.deepEqual(ids(back.great), ['bluff', 'expo']);                                     // what seats five
  const once = homeShelves({ all, people: 4, keyOf: key, recent: ['avrana:bluff'] });
  assert.deepEqual([once.lead.id, once.leadPlayed, once.played.length, ids(once.great)],
    ['bluff', true, 0, ['expo', 'arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms']]);
  const alone = homeShelves({ all, people: 1, keyOf: key });
  assert.equal(alone.title, 'Games');
  assert.deepEqual([alone.lead.id, alone.great.length], ['bluff', 4]);
  // six: only BLUFF seats them, it leads, and nothing is left for a "Great for six" shelf
  const six = homeShelves({ all, people: 6, keyOf: key });
  assert.deepEqual([six.lead.id, six.great.length], ['bluff', 0]);
  const nine = homeShelves({ all, people: 9, keyOf: key });                                 // nothing suits nine: still a way in
  assert.deepEqual([nine.lead.id, nine.great.length], ['bluff', 0]);
  assert.deepEqual(homeShelves({ all: [], people: 4 }), { lead: null, leadPlayed: false, title: 'Great for four', great: [], played: [] });
});

test('the line under Home’s lead title says what is true of it for this party', () => {
  assert.equal(leadLine(game('bluff'), { people: 4, played: true }), 'You played this last. Room for all four of you.');
  assert.equal(leadLine(game('bluff'), { people: 4 }), 'Room for all four of you.');
  assert.equal(leadLine(game('arcade-gauntlet2'), { people: 3 }), 'Room for all three of you.');
  assert.equal(leadLine(game('arcade-gauntlet2'), { people: 5 }), 'Up to 4 play; you’re 5.');
  assert.equal(leadLine({ players: { min: 3, max: 8 } }, { people: 2 }), 'Needs 3 or more.');
  assert.equal(leadLine(game('bluff'), { people: 1, played: true }), 'You played this last.');
  assert.equal(leadLine(game('bluff'), { people: 0 }), '');
});

test('a game’s page says whether it suits the people here, and what happens to the rest', () => {
  const game = (min, max, spectators) => ({ players: { min, max }, spectators });
  // nobody to suit: no sentence at all
  for (const n of [0, 1, undefined]) assert.equal(fitLine(game(2, 6, 'watch'), n), null);
  assert.deepEqual(fitLine(game(2, 6, 'watch'), 4), { ok: true, icon: 'check', text: 'Room for all four of you.' });
  assert.equal(fitLine(game(2, 6, 'watch'), 2).text, 'Room for both of you.');
  assert.equal(fitLine(game(2, 6, 'watch'), 6).text, 'Room for all six of you.');
  // too many: a game with a watch view says how many watch; one without says how many sit out
  assert.deepEqual(fitLine(game(2, 6, 'watch'), 7), { ok: false, icon: 'triangle-alert', text: 'Up to 6 play; one of you watches.' });
  assert.equal(fitLine(game(2, 6, 'watch'), 9).text, 'Up to 6 play; three of you watch.');
  assert.equal(fitLine(game(1, 2, 'none'), 3).text, 'Up to 2 play; one of you sits out.');
  assert.equal(fitLine(game(1, 2, 'none'), 4).text, 'Up to 2 play; two of you sit out.');
  assert.equal(fitLine(game(1, 2, undefined), 5).text, 'Up to 2 play; three of you sit out.');   // unknown is not a promise of a watch view
  // too few
  assert.deepEqual(fitLine(game(3, 5, 'watch'), 2), { ok: false, icon: 'triangle-alert', text: 'Needs 3 or more; you’re 2.' });
  // every sentence that is not a plain yes carries a mark: never colour alone
  for (let n = 2; n <= 12; n++) for (const g of [game(2, 6, 'watch'), game(1, 2, 'none'), game(3, 5, 'watch'), game(1, 4, 'watch')]) {
    const line = fitLine(g, n);
    assert.equal(line.ok, n >= g.players.min && n <= g.players.max, `${n} ${JSON.stringify(g)}`);
    assert.ok(line.icon && line.text, `${n}`);
    assert.doesNotMatch(line.text, /undefined|NaN/);
  }
});

test('the fit sentence on the five real titles, for a party of four and of five', () => {
  const lines = (people) => Object.fromEntries(catalog.games.map((g) => [g.id, fitLine(g, people).text]));
  assert.deepEqual(lines(4), {
    bluff: 'Room for all four of you.',
    expo: 'Room for all four of you.',
    'arcade-gauntlet2': 'Room for all four of you.',
    'ps1-bomberman': 'Room for all four of you.',
    'ps1-worms': 'Room for all four of you.',
  });
  assert.deepEqual(lines(5), {
    bluff: 'Room for all five of you.',
    expo: 'Room for all five of you.',
    'arcade-gauntlet2': 'Up to 4 play; one of you sits out.',          // it declares no spectators (rule 4.4a)
    'ps1-bomberman': 'Up to 4 play; one of you watches.',
    'ps1-worms': 'Up to 4 play; one of you watches.',
  });
});
