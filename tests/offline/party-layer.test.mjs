// The Party layer's rules (AVR-292): web/party/lib/layer.js and the page-side mount,
// web/party/bridge/layer-mount.js. Run with: node --test tests/offline/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { BUTTON, MARGIN, TAB, layerBox, mountPartyLayer, parseLayerMessage } from '../../web/party/bridge/layer-mount.js';
import { DEFAULT_SPOT, LONG_PRESS_MS, PROTOCOL, SLOP, STEP, actions, buttonLabel, connectionLine, gesture, keptSpots, nudge,
  orientationOf, park, parseFromPage, requestFor, spotAt, spotFor, toSpot, unpark, usable,
  HOLD_MS, HOLD_VERBS, holdState, panelOn, sheetSide } from '../../web/party/lib/layer.js';

const VP = { w: 375, h: 667, insets: { top: 20, right: 0, bottom: 34, left: 0 } };
const P = (o) => ({ avrana: PROTOCOL, ...o });

test('the frame may say ready, place and drag, exactly, and nothing else', () => {
  assert.ok(parseLayerMessage(P({ type: 'ready' })));
  assert.ok(parseLayerMessage(P({ type: 'place', mode: 'button', side: 'left', y: 10 })));
  assert.ok(parseLayerMessage(P({ type: 'place', mode: 'open', side: 'right', y: 0 })));
  assert.ok(parseLayerMessage(P({ type: 'drag', x: 1, y: 2 })));
  assert.ok(parseLayerMessage(P({ type: 'hide' })));
  assert.equal(parseLayerMessage(P({ type: 'hide', mode: 'open' })), null);
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
  assert.deepEqual(layerBox({ type: 'drag', x: -40, y: 5000 }, VP),
    { x: MARGIN, y: VP.h - VP.insets.bottom - MARGIN - BUTTON, w: BUTTON, h: BUTTON });
  assert.deepEqual(layerBox({ type: 'drag', x: 123, y: 234 }, VP), { x: 123, y: 234, w: BUTTON, h: BUTTON });   // free: no edge snapping
  const notch = { ...VP, insets: { top: 0, right: 44, bottom: 0, left: 44 } };     // a phone on its side
  assert.equal(layerBox({ type: 'place', mode: 'button', side: 'left', y: 50 }, notch).x, 44 + MARGIN);
  assert.equal(layerBox({ type: 'place', mode: 'button', side: 'right', y: 50 }, notch).x, notch.w - 44 - MARGIN - BUTTON);
});

test('the button is where it was put: free, kept as fractions, and always inside the safe areas', () => {
  const u = usable(VP);
  assert.deepEqual(u, { x0: MARGIN, y0: VP.insets.top + MARGIN, x1: VP.w - MARGIN - BUTTON, y1: VP.h - VP.insets.bottom - MARGIN - BUTTON });
  const mid = toSpot({ x: 150, y: 300 }, VP);
  assert.equal(mid.parked, null);
  assert.deepEqual(spotAt(mid, VP), { x: 150, y: 300 });                      // a point in the middle stays in the middle
  assert.deepEqual(toSpot({ x: -999, y: 99999 }, VP), { nx: 0, ny: 1, parked: null });   // let go off-screen: clamped
  assert.deepEqual(requestFor(mid, VP), { type: 'drag', x: 150, y: 300 });
  assert.deepEqual(requestFor({ nx: 0.3, ny: 0.5, parked: 'left' }, VP), { type: 'place', mode: 'tab', side: 'left', y: spotAt({ nx: 0, ny: 0.5 }, VP).y });
});

test('a turn of the phone keeps each orientation\'s own place; a size change clamps', () => {
  const portrait = VP, landscape = { w: 667, h: 375, insets: { top: 0, right: 44, bottom: 21, left: 44 } };
  assert.equal(orientationOf(portrait), 'portrait');
  assert.equal(orientationOf(landscape), 'landscape');
  const spots = { portrait: { nx: 0.2, ny: 0.8, parked: null } };
  assert.deepEqual(spotFor(spots, portrait), spots.portrait);
  assert.deepEqual(spotFor(spots, landscape), spots.portrait, 'the first time sideways, it follows the other orientation');
  const both = { ...spots, landscape: { nx: 1, ny: 0, parked: null } };
  assert.deepEqual(spotFor(both, landscape), both.landscape);
  assert.deepEqual(spotFor(both, portrait), both.portrait, 'turning back finds the first place again');
  const box = layerBox(requestFor(both.landscape, landscape), landscape);
  assert.equal(box.x, landscape.w - 44 - MARGIN - BUTTON);                    // the notch side is respected
  assert.equal(box.y, MARGIN);
  for (const vp of [{ w: 320, h: 200, insets: VP.insets }, { w: 80, h: 80, insets: { top: 30, right: 30, bottom: 30, left: 30 } }]) {
    const at = requestFor(both.portrait, vp);
    const b = layerBox(at, vp);
    assert.ok(b.x >= 0 && b.y >= 0 && b.x + b.w <= vp.w + MARGIN * 2 && b.y >= vp.insets.top, JSON.stringify(vp));
  }
  assert.deepEqual(spotFor({}, VP), DEFAULT_SPOT);
});

test('kept places are checked; anything else is dropped', () => {
  const good = { nx: 0.5, ny: 0.5, parked: null };
  assert.deepEqual(keptSpots({ portrait: good, landscape: { ...good, parked: 'left' } }), { portrait: good, landscape: { ...good, parked: 'left' } });
  assert.deepEqual(keptSpots({ portrait: { nx: 2, ny: 0, parked: null } }), {});
  assert.deepEqual(keptSpots({ portrait: { nx: 0, ny: 0, parked: 'top' } }), {});
  assert.deepEqual(keptSpots({ mode: 'button', side: 'right', y: 80 }), {});   // the old shape: start fresh
  assert.deepEqual(keptSpots(null), {});
});

test('without dragging: nudges, parking on an edge, the tab back, all deliberate', () => {
  const at = { nx: 0.5, ny: 0.5, parked: null };
  const from = spotAt(at, VP);
  assert.deepEqual(spotAt(nudge(at, 'down', VP), VP), { x: from.x, y: from.y + STEP });
  assert.deepEqual(spotAt(nudge(at, 'left', VP), VP), { x: from.x - STEP, y: from.y });
  assert.equal(nudge({ nx: 0, ny: 0, parked: null }, 'up', VP).ny, 0, 'a nudge stops at the edge of the room');
  const parked = park(at, 'right');
  assert.deepEqual(parked, { nx: 0.5, ny: 0.5, parked: 'right' });
  assert.equal(requestFor(parked, VP).mode, 'tab');
  assert.deepEqual(unpark(parked), { nx: 1, ny: 0.5, parked: null });          // back at the edge it was parked on
  assert.equal(nudge(parked, 'down', VP).parked, null, 'moving a parked button brings it back');
  assert.equal(requestFor(unpark(park(at, 'left')), VP).x, MARGIN);
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
  // on another origin's page, only what bridge v1 already allows a game page (D3: coverable)
  assert.deepEqual(actions(view('game'), { crossOrigin: true }), ['end', 'lobby']);
  assert.deepEqual(actions(view('results'), { crossOrigin: true }), ['lobby']);
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
  assert.equal(layer.frame.attrs.allow, 'gamepad');   // the controller shortcut is read in the frame (AVR-581)
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
  page.say(P({ type: 'hide' }));                          // no longer a member: nothing over the game
  assert.equal(layer.frame.style.visibility, 'hidden');
  assert.equal(layer.isOpen(), false);
  assert.deepEqual(page.events, [{ open: true }, { open: false }]);
  page.say(P({ type: 'place', mode: 'open', side: 'right', y: 200 }));
  layer.stop();
  assert.equal(layer.frame.removed, true);
  assert.deepEqual(page.events, [{ open: true }, { open: false }, { open: true }, { open: false }]);
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

test('the mount leaves a dragged button where it is put, and keeps it inside when the page resizes', () => {
  const page = fakePage();
  const layer = mountPartyLayer({ partyOrigin: 'https://party.test', game: 'bluff', window: page.win });
  page.say(P({ type: 'ready' }));
  page.say(P({ type: 'drag', x: 170, y: 300 }));
  assert.equal(layer.frame.style.left, '170px');
  assert.equal(layer.frame.style.top, '300px');
  assert.equal(layer.frame.style.width, `${BUTTON}px`, 'the frame is the button: a tap beside it is the game\'s');
  assert.equal(layer.frame.style.height, `${BUTTON}px`);
  assert.equal(layer.frame.dataset.avranaPartyLayer, 'button');
  page.win.innerWidth = 200; page.win.innerHeight = 250;               // the page shrinks
  page.listeners.resize();
  assert.equal(layer.frame.style.left, `${200 - MARGIN - BUTTON}px`);
  assert.equal(layer.frame.style.top, `${250 - 34 - MARGIN - BUTTON}px`);
  assert.deepEqual(page.posted.at(-1), [P({ type: 'viewport', w: 200, h: 250, insets: VP.insets }), 'https://party.test']);
  page.say(P({ type: 'place', mode: 'tab', side: 'left', y: 100 }));   // parked
  assert.equal(layer.frame.style.left, '0px');
  assert.equal(layer.frame.style.width, `${TAB.w}px`);
  layer.stop();
});

test('a panned keyboard moves the open frame with the visible region; a pan alone is not a resize, and stop leaks nothing', () => {
  const page = fakePage(), vvl = {};
  const vv = { width: 375, height: 667, offsetTop: 0, offsetLeft: 0,
    addEventListener: (n, f) => { (vvl[n] ||= new Set()).add(f); }, removeEventListener: (n, f) => { vvl[n]?.delete(f); } };
  page.win.visualViewport = vv;
  const layer = mountPartyLayer({ partyOrigin: 'https://party.test', game: 'bluff', window: page.win });
  page.say(P({ type: 'ready' }));
  page.say(P({ type: 'place', mode: 'open', side: 'right', y: 200 }));
  const sent = page.posted.length;
  vv.height = 331; vv.offsetTop = 120;                          // keyboard up, and Safari panned the page to the field
  for (const f of [...vvl.resize, ...vvl.scroll]) f();
  assert.equal(layer.frame.style.top, '120px', 'the frame starts where the visible region starts');
  assert.equal(layer.frame.style.height, '331px', 'and is only as tall as what is visible');
  const sizes = page.posted.slice(sent).filter(([m]) => m.type === 'viewport');
  assert.equal(sizes.length, 1, 'one for the new size; the scroll that follows repeats nothing');
  assert.deepEqual(sizes[0][0], P({ type: 'viewport', w: 375, h: 331, insets: VP.insets }), 'the bridge message is unchanged: no offsets on the wire');
  vv.offsetTop = 60; for (const f of vvl.scroll) f();           // panned further: moves, sends nothing
  assert.equal(layer.frame.style.top, '60px');
  assert.equal(page.posted.slice(sent).filter(([m]) => m.type === 'viewport').length, 1);
  vv.offsetTop = -14; for (const f of vvl.scroll) f();          // rubber-banding past the top never lifts the frame off screen
  assert.equal(layer.frame.style.top, '0px');
  layer.stop();
  assert.equal(vvl.resize.size + vvl.scroll.size, 0, 'both visualViewport listeners are removed');
});

// ---- PROPOSAL fab_panel (AVR-769) ----------------------------------------------------------------------
test('fab_panel: the bounded panel only where the Party mounted the frame and the proposal is on', () => {
  const on = { proposals: ['fab_panel'], me: { id: 'a' } };
  assert.equal(panelOn(on, { crossOrigin: false }), true);
  assert.equal(panelOn(on, { crossOrigin: true }), false);           // over a game page of another origin: the drawer as before
  assert.equal(panelOn(on), false);                                  // unknown is another origin
  assert.equal(panelOn({ proposals: ['play_shell'] }, { crossOrigin: false }), false);
  assert.equal(panelOn(null, { crossOrigin: false }), false);
});

test('fab_panel: a sheet along the bottom in portrait, along the button\'s side in landscape', () => {
  const portrait = { w: 390, h: 844, insets: { top: 47, right: 0, bottom: 34, left: 0 } };
  const landscape = { w: 844, h: 390, insets: { top: 0, right: 47, bottom: 21, left: 47 } };
  assert.equal(sheetSide({ nx: 0, ny: 0.3, parked: null }, portrait), 'bottom');
  assert.equal(sheetSide({ nx: 1, ny: 0.3, parked: null }, landscape), 'right');
  assert.equal(sheetSide({ nx: 0.2, ny: 0.3, parked: null }, landscape), 'left');
  assert.equal(sheetSide({ nx: 0.9, ny: 0.3, parked: 'left' }, landscape), 'left');
  assert.equal(sheetSide(null, null), 'bottom');
});

test('fab_panel: a destructive verb confirms only when held for HOLD_MS', () => {
  assert.equal(HOLD_MS, 800);
  assert.deepEqual(HOLD_VERBS.sort(), ['end', 'handover', 'lobby', 'spectate']);
  assert.equal(holdState({ downAt: null, now: 5 }), 'idle');
  assert.equal(holdState({ downAt: 0, now: 400 }), 'holding');
  assert.equal(holdState({ downAt: 0, upAt: 300, now: 900 }), 'short');
  assert.equal(holdState({ downAt: 0, now: 800 }), 'held');
  assert.equal(holdState({ downAt: 100, upAt: 950, now: 950 }), 'held');
});
