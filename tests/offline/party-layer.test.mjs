// The Party layer's rules (AVR-292): web/party/lib/layer.js and the page-side mount,
// web/party/bridge/layer-mount.js. Run with: node --test tests/offline/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { BUTTON, MARGIN, TAB, layerBox, mountPartyLayer, parseLayerMessage } from '../../web/party/bridge/layer-mount.js';
import { FLING, LONG_PRESS_MS, PROTOCOL, SLOP, actions, buttonLabel, connectionLine, gesture, initialPlace,
  parseFromPage, settle } from '../../web/party/lib/layer.js';

const VP = { w: 375, h: 667, insets: { top: 20, right: 0, bottom: 34, left: 0 } };
const P = (o) => ({ avrana: PROTOCOL, ...o });

test('the frame may say ready, place and drag, exactly, and nothing else', () => {
  assert.ok(parseLayerMessage(P({ type: 'ready' })));
  assert.ok(parseLayerMessage(P({ type: 'place', mode: 'button', side: 'left', y: 10 })));
  assert.ok(parseLayerMessage(P({ type: 'place', mode: 'open', side: 'right', y: 0 })));
  assert.ok(parseLayerMessage(P({ type: 'drag', x: 1, y: 2 })));
  for (const bad of [null, 'x', [], { type: 'ready' }, { avrana: 'avrana.party-bridge/v1', type: 'ready' },
    P({ type: 'ready', extra: 1 }), P({ type: 'place', mode: 'full', side: 'left', y: 1 }),
    P({ type: 'place', mode: 'tab', side: 'top', y: 1 }), P({ type: 'place', mode: 'tab', side: 'left', y: NaN }),
    P({ type: 'place', mode: 'tab', side: 'left' }), P({ type: 'drag', x: '1', y: 2 }), P({ type: 'navigate', url: '/' }),
    P({ type: 'drag', x: 1, y: Infinity })]) {
    assert.equal(parseLayerMessage(bad), null, JSON.stringify(bad));
  }
});

test('the frame accepts only a well-formed viewport from the page', () => {
  assert.deepEqual(parseFromPage(P({ type: 'viewport', ...VP })), { type: 'viewport', ...VP });
  for (const bad of [P({ type: 'viewport', w: 0, h: 1, insets: VP.insets }), P({ type: 'viewport', w: 1, h: 1 }),
    P({ type: 'viewport', w: 1, h: 1, insets: { ...VP.insets, top: -1 } }), P({ type: 'viewport', ...VP, x: 1 }),
    P({ type: 'viewport', w: 1, h: 1, insets: { top: 0, right: 0, bottom: 0 } }), P({ type: 'place', ...VP })]) {
    assert.equal(parseFromPage(bad), null, JSON.stringify(bad));
  }
});

test('the frame box is always inside the viewport and clear of the safe areas', () => {
  assert.deepEqual(layerBox({ type: 'place', mode: 'button', side: 'right', y: 100 }, VP),
    { x: VP.w - MARGIN - BUTTON, y: 100, w: BUTTON, h: BUTTON });
  assert.deepEqual(layerBox({ type: 'place', mode: 'button', side: 'left', y: -50 }, VP),
    { x: MARGIN, y: VP.insets.top + MARGIN, w: BUTTON, h: BUTTON });
  assert.deepEqual(layerBox({ type: 'place', mode: 'button', side: 'left', y: 9999 }, VP).y,
    VP.h - VP.insets.bottom - MARGIN - BUTTON);
  assert.deepEqual(layerBox({ type: 'place', mode: 'tab', side: 'right', y: 100 }, VP), { x: VP.w - TAB.w, y: 100, ...TAB });
  assert.deepEqual(layerBox({ type: 'place', mode: 'tab', side: 'left', y: 100 }, VP), { x: 0, y: 100, ...TAB });
  assert.deepEqual(layerBox({ type: 'place', mode: 'open', side: 'left', y: 100 }, VP), { x: 0, y: 0, w: VP.w, h: VP.h });
  assert.deepEqual(layerBox({ type: 'drag', x: -40, y: 5000 }, VP), { x: 0, y: VP.h - BUTTON, w: BUTTON, h: BUTTON });
  const notch = { ...VP, insets: { top: 0, right: 44, bottom: 0, left: 44 } };     // a phone on its side
  assert.equal(layerBox({ type: 'place', mode: 'button', side: 'left', y: 50 }, notch).x, 44 + MARGIN);
  assert.equal(layerBox({ type: 'place', mode: 'button', side: 'right', y: 50 }, notch).x, notch.w - 44 - MARGIN - BUTTON);
});

test('a release settles on the nearer side; past the edge or a fling tucks it into a tab', () => {
  assert.deepEqual(settle({ x: 40, y: 200, vx: 0 }, VP), { mode: 'button', side: 'left', y: 200 });
  assert.deepEqual(settle({ x: 300, y: 200, vx: 0 }, VP), { mode: 'button', side: 'right', y: 200 });
  assert.equal(settle({ x: -BUTTON / 2, y: 0 }, VP).mode, 'tab');
  assert.equal(settle({ x: VP.w - BUTTON / 2, y: 0 }, VP).mode, 'tab');
  assert.equal(settle({ x: 100, y: 0, vx: -FLING }, VP).mode, 'tab');            // thrown left
  assert.equal(settle({ x: 100, y: 0, vx: FLING * 0.9 }, VP).mode, 'button');    // toward the far side, too slow
  assert.equal(settle({ x: 250, y: 0, vx: FLING * 2 }, VP).mode, 'tab');
  assert.equal(settle({ x: 250, y: 0, vx: -FLING * 2 }, VP).mode, 'button');      // thrown away from its side
});

test('the first place is the kept one, else the right side a third down', () => {
  assert.deepEqual(initialPlace(null, VP), { mode: 'button', side: 'right', y: Math.round(VP.h / 3) });
  assert.deepEqual(initialPlace({ mode: 'tab', side: 'left', y: 80 }, VP), { mode: 'tab', side: 'left', y: 80 });
  assert.deepEqual(initialPlace({ mode: 'open', side: 'left', y: 80 }, VP).mode, 'button');   // never opens by itself
  assert.deepEqual(initialPlace({ mode: 'tab', side: 'top', y: 80 }, VP).side, 'right');
});

test('a short press is a tap, a long one a drag, a moving short one nothing', () => {
  assert.equal(gesture({ heldMs: 100, moved: 2 }), 'tap');
  assert.equal(gesture({ heldMs: 100, moved: SLOP + 1 }), 'cancel');
  assert.equal(gesture({ heldMs: LONG_PRESS_MS, moved: 0 }), 'drag');
});

const view = (at, { host = true, others = 'here' } = {}) => ({
  party: 'p', version: 3, location: { at, game: at === 'home' ? null : 'bluff', session: at === 'home' ? null : 's' },
  me: { id: 'a', host }, members: [{ id: 'a', presence: 'playing' }, ...(others ? [{ id: 'b', presence: others }] : [])],
});

test('only the host is offered host actions, and each where Party Core allows it', () => {
  for (const where of ['home', 'setup', 'game', 'results']) {
    const got = actions(view(where));
    assert.equal(got.includes('end'), where === 'game', where);
    assert.equal(got.includes('lobby'), where !== 'home', where);
    assert.equal(got.includes('spectate'), where === 'setup' || where === 'results', where);
    assert.ok(got.includes('handover'), where);
    assert.deepEqual(actions(view(where, { host: false })), [], where);
  }
  assert.ok(!actions(view('game', { others: 'away' })).includes('handover'));
  assert.ok(!actions(view('game', { others: null })).includes('handover'));
  assert.deepEqual(actions({ me: null }), []);
  assert.deepEqual(actions(null), []);
});

test('the button names new messages; the connection line is empty when all is well', () => {
  assert.equal(buttonLabel(0), 'Your Party');
  assert.equal(buttonLabel(1), 'Your Party, 1 new message');
  assert.equal(buttonLabel(3), 'Your Party, 3 new messages');
  assert.equal(connectionLine({ party: 'online', chat: 'live' }), '');
  assert.match(connectionLine({ party: 'offline', chat: 'live' }), /Not connected/);
  assert.match(connectionLine({ party: 'online', chat: 'unavailable' }), /reconnecting/);
});

// ---- the mount, against a tiny fake page ----
function fakePage() {
  const listeners = {}, docListeners = {}, posted = [], events = [];
  const el = (tag) => ({ tag, style: {}, dataset: {}, attrs: {}, removed: false, setAttribute(k, v) { this.attrs[k] = v; },
    remove() { this.removed = true; }, focus() { this.focused = true; } });
  const frameWin = { postMessage: (m, o) => posted.push([m, o]) };
  const body = { children: [], append(n) { this.children.push(n); if (n.tag === 'iframe') n.contentWindow = frameWin; } };
  const doc = { body, createElement: el, dispatchEvent: (e) => events.push(e.detail), addEventListener() {} };
  const win = { innerWidth: 375, innerHeight: 667, document: doc, CustomEvent: class { constructor(n, o) { this.detail = o.detail; } },
    getComputedStyle: () => ({ paddingTop: '20px', paddingRight: '0px', paddingBottom: '34px', paddingLeft: '0px' }),
    addEventListener: (n, f) => { listeners[n] = f; }, removeEventListener: (n) => { delete listeners[n]; } };
  const say = (data, { origin = 'https://party.test', source = frameWin } = {}) => listeners.message({ data, origin, source });
  return { win, doc, body, frameWin, posted, events, listeners, docListeners, say };
}

test('the mount frames the layer page for this game, hidden until placed', () => {
  const page = fakePage();
  const layer = mountPartyLayer({ partyOrigin: 'https://party.test', game: 'bluff', window: page.win });
  assert.equal(layer.frame.src, 'https://party.test/party/layer.html?game=bluff');
  assert.equal(layer.frame.attrs.sandbox, 'allow-scripts allow-same-origin allow-forms');
  assert.equal(layer.frame.style.visibility, 'hidden');
  page.say(P({ type: 'ready' }));
  assert.deepEqual(page.posted.at(-1), [P({ type: 'viewport', ...VP }), 'https://party.test']);
  page.say(P({ type: 'place', mode: 'button', side: 'right', y: 200 }));
  assert.equal(layer.frame.style.visibility, 'visible');
  assert.equal(layer.frame.style.left, `${375 - MARGIN - BUTTON}px`);
  page.say(P({ type: 'place', mode: 'open', side: 'right', y: 200 }));
  assert.equal(layer.isOpen(), true);
  assert.equal(layer.frame.style.width, '375px');
  assert.deepEqual(page.events, [{ open: true }]);
  layer.stop();
  assert.equal(layer.frame.removed, true);
  assert.deepEqual(page.events, [{ open: true }, { open: false }]);
  assert.equal(page.listeners.message, undefined);
});

test('the mount ignores messages from any other origin or window, and malformed ones', () => {
  const page = fakePage();
  const layer = mountPartyLayer({ partyOrigin: 'https://party.test', game: 'bluff', window: page.win });
  page.say(P({ type: 'place', mode: 'open', side: 'left', y: 0 }), { origin: 'https://evil.test' });
  page.say(P({ type: 'place', mode: 'open', side: 'left', y: 0 }), { source: {} });
  page.say({ ...P({ type: 'place', mode: 'open', side: 'left', y: 0 }), href: 'https://evil.test' });
  assert.equal(layer.isOpen(), false);
  assert.equal(layer.frame.style.visibility, 'hidden');
  assert.throws(() => mountPartyLayer({ partyOrigin: 'https://party.test/x', game: 'bluff', window: page.win }));
  assert.throws(() => mountPartyLayer({ partyOrigin: 'https://party.test', game: '../x', window: page.win }));
});
