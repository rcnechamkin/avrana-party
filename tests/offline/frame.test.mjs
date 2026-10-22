// Tier 1 (node --test): the shell's frame. Which place a fragment names, the words that say who is
// here, and when today's chat (served by the retiring games runtime, ADR 0014) is on offer.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PAGES, chatOffered, hereLine, hostLine, partyTabLabel, presenceLabel, presenceLine, namesLine, pageOf, pageTitle, startTab, gameOf, backWord, unreadMark } from '../../web/party/lib/frame.js';

const html = readFileSync(new URL('../../web/party/index.html', import.meta.url), 'utf8');

test('a fragment names a place, and anything else is Home', () => {
  // Concept K (AVR-707): System became Me, and #system, still linked from older words, lands there
  assert.deepEqual(PAGES, ['home', 'party', 'library', 'me']);
  for (const page of PAGES) assert.equal(pageOf(`#${page}`), page);
  assert.equal(pageOf('#system'), 'me');
  assert.equal(pageOf('library'), 'library');
  for (const odd of ['', '#', '#diag', '#Library', '#library/x', '#__proto__', null, undefined, 7])
    assert.equal(pageOf(odd), 'home', String(odd));
});

test('every place has a title, a view and a link in the bar', () => {
  assert.equal(pageTitle('home'), 'Avrana Party');
  assert.deepEqual(PAGES.slice(1).map(pageTitle), ['Party', 'Library', 'Me']);
  assert.equal(pageTitle('nowhere'), 'Avrana Party');
  for (const page of PAGES) {
    assert.match(html, new RegExp(`<section id="view-${page}"[^>]*data-page="${page}"`), `view ${page}`);
    assert.match(html, new RegExp(`<a[^>]*href="#${page}"[^>]*data-go="${page}"|<a[^>]*data-go="${page}"[^>]*href="#${page}"`), `link ${page}`);
  }
});

test('who is here, as a sentence', () => {
  assert.equal(hereLine(0), 'You’re the only one here.');
  assert.equal(hereLine(1), 'You’re the only one here.');
  assert.equal(hereLine(2), 'Two of you are here.');
  assert.equal(hereLine(4), 'Four of you are here.');
  assert.equal(hereLine(12), 'Twelve of you are here.');
  assert.equal(hereLine(13), '13 of you are here.');
});

test('the names put this phone first and leave the list as it was', () => {
  const people = [{ name: 'Ben' }, { name: 'Ana', me: true }, { name: 'Cleo' }];
  assert.equal(namesLine(people), 'Ana (you), Ben and Cleo.');
  assert.deepEqual(people.map((m) => m.name), ['Ben', 'Ana', 'Cleo']);
  assert.equal(namesLine([{ name: 'Ana', me: true }, { name: 'Ben' }]), 'Ana (you) and Ben.');
  assert.equal(namesLine([{ name: 'Ana', me: true }]), '');
  assert.equal(namesLine([]), '');
  assert.equal(namesLine(null), '');
});

test('who picks the games', () => {
  const ana = { name: 'Ana', host: true }, ben = { name: 'Ben' };
  assert.match(hostLine(ana, ana), /^You’re the host\. Pick a game in the Library/);
  assert.equal(hostLine(ben, ana), 'Ana is the host and picks the games.');
  assert.equal(hostLine(ben, ana, true), 'Ana is the host, and is away.');
  assert.match(hostLine(ana, ana, true), /^You’re the host\./);            // this phone is never told it is away
  assert.equal(hostLine(ben, null, true), 'Nobody is hosting right now.');
  assert.equal(hostLine(ben, null), 'Nobody is hosting right now.');
  assert.equal(hostLine(null, ana), '');
});

test('the Party room is offered to a member of the Party, whatever else runs, never out of reach', () => {
  assert.equal(chatOffered({ reachable: true, member: true }), true);
  assert.equal(chatOffered({ reachable: true, member: false }), false);
  assert.equal(chatOffered({ reachable: false, member: true }), false);
  assert.equal(chatOffered(), false);
});

test('the unread mark is a small count', () => {
  assert.equal(unreadMark(0), '');
  assert.equal(unreadMark(3), '3');
  assert.equal(unreadMark(10), '9+');
});

test('the drawer opens on the side asked for when it exists, else chat, else people', () => {
  assert.equal(startTab({ party: true, chat: true }), 'chat');
  assert.equal(startTab({ party: true, chat: true, want: 'people' }), 'people');
  assert.equal(startTab({ party: true, chat: false, want: 'chat' }), 'people');
  assert.equal(startTab({ party: false, chat: true, want: 'people' }), 'chat');
  assert.equal(startTab({ party: false, chat: false, want: 'chat' }), null);
  assert.equal(startTab(), null);
});

// Concept K retired the Party control at the top (AVR-707): what is new in the chat is said on the
// bar's Party tab, as a badge and in the tab's name.
test('the Party tab names what is new in the chat for a screen reader', () => {
  assert.equal(partyTabLabel(0), 'Party');
  assert.equal(partyTabLabel(), 'Party');
  assert.equal(partyTabLabel(1), 'Party, 1 new message');
  assert.equal(partyTabLabel(2), 'Party, 2 new messages');
  assert.match(html, /<a[^>]*data-go="party"[^>]*>[\s\S]*?id="nav-unread"/);
  assert.doesNotMatch(html, /id="hud"/);
});

test('a game’s page is named by its address, and only by a well-formed one', () => {
  assert.equal(gameOf('#game/bluff'), 'bluff');
  assert.equal(gameOf('game/arcade-gauntlet2'), 'arcade-gauntlet2');
  assert.equal(gameOf('#game/ps1-worms'), 'ps1-worms');
  assert.equal(gameOf('#game/Some_Title-2'), 'Some_Title-2');     // whatever shape a catalog id may take, short of a path
  for (const bad of ['', '#', '#game', '#game/', '#game/bluff/extra', '#game/../x', '#game/-x', '#game/_x', '#game/a b', '#game/a.b', '#game/a%2Fb',
    '#games/bluff', '#library', '#game/' + 'a'.repeat(65), '#game/<img>', null, undefined, 7])
    assert.equal(gameOf(bad), null, String(bad));
  // it is never one of the four places: an address that names a game is not a place in the bar
  assert.equal(pageOf('#game/bluff'), 'home');
  assert.equal(PAGES.includes('game'), false);
});

test('the way back from a game’s page is named after the place it returns to', () => {
  assert.equal(backWord('library'), 'Library');
  assert.equal(backWord('home'), 'Home');
  assert.equal(backWord('party'), 'Party');
  assert.equal(backWord('me'), 'Me');
  for (const odd of ['game', '', undefined, 'nowhere']) assert.equal(backWord(odd), 'Library', String(odd));
});

test('the presence row says how many are here and who is away, in words, and its name says the same', () => {
  const m = (name, away = false) => ({ name, away });
  assert.equal(presenceLine([]), '0 here');
  assert.equal(presenceLine([m('Ana')]), '1 here');
  assert.equal(presenceLine([m('Ana'), m('Riley', true), m('Ben'), m('Cy')]), '4 here · Riley away');
  assert.equal(presenceLine([m('A'), m('B', true), m('C', true), ...Array.from({ length: 9 }, (_, i) => m(`P${i}`))]), '12 here · 2 away');
  assert.equal(presenceLabel([m('Ana'), m('Riley', true)]), '2 here · Riley away. Open people');
  assert.equal(presenceLine(null), '0 here');
});
