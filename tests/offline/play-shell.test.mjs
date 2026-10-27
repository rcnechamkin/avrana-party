// PROPOSAL play_shell (AVR-766; draft ADR 0018 revision 3): with the proposal on, Party Home sends a
// phone to play.html for a game on another origin, which frames it; without it, or for a game on the
// Party's own origin, the phone goes exactly where it went before.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { playShellOn, frameTarget, roundAddress, PLAY_PAGE, FRAME_SANDBOX } from '../../web/party/lib/play.js';

const PARTY = 'https://party.avrana.net';
const GAME = 'https://games.avrana.net/games/tanks/';
const on = { proposals: ['play_shell'] }, off = { proposals: [] };

test('the proposal is read from the view, off unless named', () => {
  assert.equal(playShellOn(on), true);
  assert.equal(playShellOn(off), false);
  assert.equal(playShellOn({}), false);
  assert.equal(playShellOn(null), false);
  assert.equal(playShellOn({ proposals: ['home_in_round'] }), false);
});

test('only an http(s) address on another origin is framed', () => {
  assert.equal(frameTarget(GAME, PARTY), GAME);
  assert.equal(frameTarget('/games/bluff/', PARTY), null);                        // same origin: today's page
  assert.equal(frameTarget(`${PARTY}/games/bluff/`, PARTY), null);
  assert.equal(frameTarget('javascript:alert(1)', PARTY), null);
  assert.equal(frameTarget('data:text/html,hi', PARTY), null);
  assert.equal(frameTarget('https://user:pw@games.avrana.net/games/tanks/', PARTY), null);
  assert.equal(frameTarget('', PARTY), null);
  assert.equal(frameTarget(null, PARTY), null);
});

test('Party Home goes to the shell only with the proposal on and a framed target', () => {
  assert.equal(roundAddress(on, GAME, PARTY), PLAY_PAGE);
  assert.equal(roundAddress(off, GAME, PARTY), GAME);                              // proposal off: unchanged
  assert.equal(roundAddress(on, '/games/bluff/', PARTY), '/games/bluff/');         // same-origin game: unchanged
  assert.equal(roundAddress(on, '/party/', PARTY), '/party/');
});

test('the game frame may not navigate the Party or open windows', () => {
  const words = FRAME_SANDBOX.split(' ');
  assert.ok(words.includes('allow-scripts') && words.includes('allow-same-origin'));
  assert.ok(!words.some((w) => w.startsWith('allow-top-navigation')));
  assert.ok(!words.includes('allow-popups'));
  assert.ok(!words.includes('allow-modals'));
});
