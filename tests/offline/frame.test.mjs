// Tier 1 (node --test): the shell's frame. Which place a fragment names, the words that say who is
// here, and when today's chat (served by the retiring games runtime, ADR 0014) is on offer.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PAGES, chatOffered, hereLine, hostLine, hudLabel, namesLine, pageOf, pageTitle, startTab }
  from '../../web/party/lib/frame.js';

const html = readFileSync(new URL('../../web/party/index.html', import.meta.url), 'utf8');

test('a fragment names a place, and anything else is Home', () => {
  assert.deepEqual(PAGES, ['home', 'party', 'library', 'system']);
  for (const page of PAGES) assert.equal(pageOf(`#${page}`), page);
  assert.equal(pageOf('library'), 'library');
  for (const odd of ['', '#', '#diag', '#Library', '#library/x', '#__proto__', null, undefined, 7])
    assert.equal(pageOf(odd), 'home', String(odd));
});

test('every place has a title, a view and a link in the bar', () => {
  assert.equal(pageTitle('home'), 'Avrana Party');
  assert.deepEqual(PAGES.slice(1).map(pageTitle), ['Party', 'Library', 'System']);
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
  assert.equal(hostLine(ben, null), 'Nobody is hosting right now.');
  assert.equal(hostLine(null, ana), '');
});

test('chat is offered only while the runtime that serves it answers, or it is already connected', () => {
  assert.equal(chatOffered({ reachable: true, hub: true, status: 'closed' }), true);
  assert.equal(chatOffered({ reachable: true, hub: false, status: 'closed' }), false);
  assert.equal(chatOffered({ reachable: true, hub: false, status: 'reconnecting' }), false);
  assert.equal(chatOffered({ reachable: true, hub: false, status: 'connected' }), true);
  assert.equal(chatOffered({ reachable: false, hub: true, status: 'connected' }), false);
  assert.equal(chatOffered(), false);
});

test('the drawer opens on the side asked for when it exists, else chat, else people', () => {
  assert.equal(startTab({ party: true, chat: true }), 'chat');
  assert.equal(startTab({ party: true, chat: true, want: 'people' }), 'people');
  assert.equal(startTab({ party: true, chat: false, want: 'chat' }), 'people');
  assert.equal(startTab({ party: false, chat: true, want: 'people' }), 'chat');
  assert.equal(startTab({ party: false, chat: false, want: 'chat' }), null);
  assert.equal(startTab(), null);
});

test('the Party control names itself for a screen reader', () => {
  assert.equal(hudLabel({ party: true, count: 4, chat: true }), 'Your Party: 4 people here. Open people and chat');
  assert.equal(hudLabel({ party: true, count: 1, chat: false }), 'Your Party: 1 person here. Open people');
  assert.equal(hudLabel({ party: false, chat: true }), 'Party chat');
  assert.equal(hudLabel({ party: false, chat: false }), '');
  assert.equal(hudLabel(), '');
});
