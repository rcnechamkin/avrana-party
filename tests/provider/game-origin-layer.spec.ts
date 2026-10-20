import { test, expect as baseExpect, devices, type Browser, type BrowserContext, type Page } from '@playwright/test';

/**
 * The Party layer (AVR-292, avrana.party-layer/v1) on the GAME origin, over REAL BLUFF and EXPO:
 * the real Party Core and shell at party.avrana.test, the real games server, BLUFF and EXPO at
 * games.avrana.test (two host names of one site, like party.avrana.net and games.avrana.net).
 * The game page mounts the Party's frame from its own vendored copy of bridge/layer-mount.js
 * (avrana-party-games web/avrana-party-layer.js, served at /shared/), so this run needs a games
 * checkout that carries it. Harness: tests/provider/server.py --party-session --game-origin --expo-game.
 *
 * What it covers: the button mounts for every member and survives a reload; the drawer shows the
 * people, the Host, the chat and the connection; a guest has no Host controls and the Host has only
 * what bridge v1 already allows a game origin (End, Party Home); End takes everyone to Party Home on
 * the Party origin and removes the frame; drag, edge parking and orientation; the keyboard; the game
 * stays usable with the layer closed; forged messages and an unregistered origin get nothing; the
 * game page holds no Party credential before, during or after.
 * Laptop Chromium at phone size, plain HTTP: TESTED here, not a phone measurement. Safari, HTTPS,
 * the __Host- cookie, nginx, touch and screen readers are Tier 3 (party-layer-device-validation).
 */
const PORT = 8187;
const PARTY = `http://party.avrana.test:${PORT}`;
const GAMES = `http://games.avrana.test:${PORT}`;
const STRANGER = `http://other.avrana.test:${PORT}`;     // an origin Party Core does not register
const LOOPBACK = `http://127.0.0.1:${PORT}`;
test.beforeEach(({}, info) => test.skip(info.project.name !== 'android-size', 'runs once, phone-sized'));
test.setTimeout(180_000);
const expect = baseExpect.configure({ timeout: 20_000 });

const FRAME = 'iframe[data-avrana-party-layer]';
const PORTRAIT = { width: 390, height: 844 }, LANDSCAPE = { width: 844, height: 390 };
type Phone = { context: BrowserContext; page: Page; direct: string[] };

function record() {
  const Native = window.WebSocket;
  const log = { rx: [] as any[], sockets: [] as WebSocket[] };
  (window as any).__avr = log;
  class Recorded extends Native {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      log.sockets.push(this);
      this.addEventListener('message', (e) => { try { log.rx.push(JSON.parse(e.data)); } catch {} });
    }
  }
  (window as any).WebSocket = Recorded;
}

async function phone(browser: Browser): Promise<Phone> {
  const { defaultBrowserType, ...device } = devices['iPhone 13'] as any;
  const context = await browser.newContext({ ...device, serviceWorkers: 'block' });
  await context.addInitScript(() => { try { localStorage.setItem('bluff-briefed', '1'); } catch { /* private */ } });
  const page = await context.newPage();
  await page.addInitScript(record);
  // Every request the game PAGE itself (not a Party frame inside it) sends to the Party API.
  const direct: string[] = [];
  page.on('request', (r) => {
    if (r.frame() === page.mainFrame() && !r.isNavigationRequest() && !page.url().startsWith(PARTY) && r.url().includes('/party/api/')) direct.push(r.url());
  });
  return { context, page, direct };
}
const close = async (...phones: Phone[]) => { for (const p of phones) await p.context.close(); };

async function api(page: Page, path: string, body?: unknown) {
  return page.evaluate(async ([p, b]) => {
    const res = await fetch('/party/api/' + p, b === undefined ? { cache: 'no-store' } : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
    return { status: res.status, body: await res.json().catch(() => null) };
  }, [path, body] as const);
}
/** Join on the Party origin from a Party document with no script of its own. */
async function join(page: Page, name: string) {
  await page.goto(`${PARTY}/party/api/state`);
  const joined = await api(page, 'join', { name });
  expect(joined.status).toBe(200);
  return joined.body;
}
async function launch(page: Page, game: string) {
  await page.goto(`${PARTY}/party/api/state`);
  const v = await api(page, 'state');
  expect((await api(page, 'session/launch', { game, if_version: v.body.version })).status).toBe(200);
}
const rx = (page: Page) => page.evaluate(() => (window as any).__avr?.rx ?? []);
const layer = (page: Page) => page.frameLocator(FRAME);
async function placed(page: Page) {
  await expect(page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'button');
  await expect(layer(page).locator('#layer-button')).toBeVisible();
}
const frameBox = async (page: Page) => (await page.locator(FRAME).boundingBox())!;
const isOpen = (page: Page) => page.evaluate(() => (window as any).AvranaIntegration.partyLayerOpen);
async function openDrawer(page: Page) {
  await layer(page).locator('#layer-button').click();
  await expect(layer(page).locator('#layer-sheet')).toBeVisible();
  await expect.poll(() => isOpen(page)).toBe(true);
}
async function closeDrawer(page: Page) {
  await layer(page).locator('#layer-close').click();
  await expect(layer(page).locator('#layer-sheet')).toBeHidden();
  await expect.poll(() => isOpen(page)).toBe(false);
}
/** Nothing of the Party on the game origin: no cookie, no Party storage, no call to the Party API. */
async function holdsNoParty(p: Phone) {
  expect(p.page.url().startsWith(GAMES)).toBe(true);
  expect(await p.page.evaluate(() => document.cookie)).toBe('');
  const stored = await p.page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  for (const bad of ['member-', 'device-', 'participant-', 'avrana_device', 'avrana-profile', 'aps0.']) expect(stored).not.toContain(bad);
  expect(p.direct).toEqual([]);
  // The frame is the Party's document: the game page can neither read it nor reach into it.
  expect(await p.page.evaluate((sel) => {
    const f = document.querySelector(sel) as HTMLIFrameElement | null;
    if (!f) return 'no frame';
    try { return f.contentDocument ? 'readable' : 'opaque'; } catch { return 'opaque'; }
  }, FRAME)).toBe('opaque');
}

/** Ana (the Host) and Ben join, Ana starts BLUFF, and both open it on the game origin. */
async function bluff(browser: Browser, request: any) {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser), ben = await phone(browser);
  await join(ana.page, 'Ana');
  await join(ben.page, 'Ben');
  await launch(ana.page, 'bluff');
  for (const p of [ana, ben]) {
    await p.page.goto(`${GAMES}/games/bluff/?avrana=1`);
    await expect.poll(async () => (await rx(p.page)).filter((m: any) => m.type === 'state' && m.game).at(-1)?.game?.me?.cards?.length ?? 0,
      { timeout: 30_000 }).toBe(2);
    await placed(p.page);
  }
  return { ana, ben };
}

test('BLUFF on the game origin: the Party-origin frame mounts for every member, and the page holds no Party', async ({ browser, request }) => {
  const { ana, ben } = await bluff(browser, request);
  for (const p of [ana, ben]) {
    const frame = p.page.locator(FRAME);
    await expect(frame).toHaveCount(1);
    await expect(frame).toHaveAttribute('src', `${PARTY}/party/layer.html?game=bluff`);
    await expect(frame).toHaveAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms');   // no top navigation, no popups
    await expect(p.page.locator('iframe[title="Avrana Party"]')).toHaveCount(1);                    // the bridge, still the only seam
    await holdsNoParty(p);
  }
  await close(ana, ben);
});

test('the drawer names the people and the Host; a guest has no Host controls; a reload keeps the button and the seat', async ({ browser, request }) => {
  const { ana, ben } = await bluff(browser, request);
  await openDrawer(ben.page);
  const l = layer(ben.page);
  await expect(l.locator('#layer-people-list li')).toHaveCount(2);
  await expect(l.locator('#layer-people-list li', { hasText: 'Ana' })).toContainText('Host');
  await expect(l.locator('#layer-host')).toBeHidden();
  await closeDrawer(ben.page);
  await expect(l.locator('#layer-button')).toBeFocused();                 // focus goes back where it was
  await ben.page.reload();
  await placed(ben.page);
  await expect(ben.page.locator(FRAME)).toHaveCount(1);
  await expect.poll(async () => (await rx(ben.page)).filter((m: any) => m.type === 'state' && m.game).at(-1)?.game?.me?.cards?.length ?? 0).toBe(2);
  await holdsNoParty(ben);
  await close(ana, ben);
});

test('the Host on the game origin is offered only End and Party Home, asked first; End takes everyone to Party Home and removes the frame', async ({ browser, request }) => {
  const { ana, ben } = await bluff(browser, request);
  await openDrawer(ana.page);
  const l = layer(ana.page);
  await expect(l.locator('#layer-host')).toBeVisible();
  const offered = await l.locator('#layer-actions [data-action]').evaluateAll((els) => els.map((e) => e.getAttribute('data-action')));
  expect(offered.sort()).toEqual(['end', 'lobby']);                       // no hand-over, no stop-hosting across origins
  await l.locator('#layer-actions [data-action="end"]').click();
  await expect(l.locator('#layer-confirm')).toBeVisible();
  await l.locator('#layer-no').click();
  expect(ana.page.url().startsWith(`${GAMES}/games/bluff/`)).toBe(true); // declined: nothing happened
  await l.locator('#layer-actions [data-action="end"]').click();
  await l.locator('#layer-yes').click();
  for (const p of [ana, ben]) {
    await p.page.waitForURL(`${PARTY}/party/`, { timeout: 30_000 });   // the Party origin, never a URL from a message
    await expect(p.page.locator(FRAME)).toHaveCount(0);
  }
  const state = await (await ana.page.goto(`${PARTY}/party/api/state`))!.json();
  expect(state.state).toBe('lobby');
  await close(ana, ben);
});

test('chat across origins: sent in one drawer, an unread count on the other button, read there', async ({ browser, request }) => {
  const { ana, ben } = await bluff(browser, request);
  await openDrawer(ben.page);
  await layer(ben.page).locator('#layer-tab-chat').click();
  await layer(ben.page).locator('#chat-text').fill('good luck, Ana');
  await layer(ben.page).locator('#chat-form button[type="submit"]').click();
  await expect(layer(ben.page).locator('#chat-messages')).toContainText('good luck, Ana');
  await expect(layer(ana.page).locator('#layer-button')).toHaveAccessibleName(/1 new message/);
  await openDrawer(ana.page);
  await layer(ana.page).locator('#layer-tab-chat').click();
  await expect(layer(ana.page).locator('#chat-messages')).toContainText('good luck, Ana');
  for (const p of [ana, ben]) await holdsNoParty(p);                       // the chat never touched the game page
  await close(ana, ben);
});

test('drag, edge parking and orientation: the frame is the button or the tab only, and stays on the screen', async ({ browser, request }) => {
  const { ana, ben } = await bluff(browser, request);
  const page = ben.page;
  await page.setViewportSize(PORTRAIT);
  await placed(page);
  // a long press, then a drag: the frame follows and stays where it is let go
  const box = await frameBox(page);
  const from = { x: box.x + box.width / 2, y: box.y + box.height / 2 }, to = { x: 180, y: 300 };
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.waitForTimeout(550);
  await expect(layer(page).locator('#layer-button')).toHaveClass(/lifted/);
  const steps = Math.ceil(Math.hypot(to.x - from.x, to.y - from.y) / 6);
  for (let i = 1; i <= steps; i++) {
    await page.mouse.move(from.x + ((to.x - from.x) * i) / steps, from.y + ((to.y - from.y) * i) / steps);
    await page.waitForTimeout(16);
  }
  await page.mouse.up();
  const moved = await frameBox(page);
  expect(Math.abs(moved.x + moved.width / 2 - to.x)).toBeLessThanOrEqual(30);
  expect(Math.abs(moved.y + moved.height / 2 - to.y)).toBeLessThanOrEqual(30);
  expect(moved.width).toBeLessThanOrEqual(48);                             // closed, the frame is only the button
  // the game keeps every tap outside the button
  await page.evaluate(() => { (window as any).taps = 0; document.addEventListener('pointerdown', () => { (window as any).taps++; }); });
  await page.mouse.click(moved.x - 6, moved.y + 24);
  expect(await page.evaluate(() => (window as any).taps)).toBe(1);
  // parked on purpose, as a tab on the edge; the tab brings it back
  await page.waitForTimeout(600);
  await openDrawer(page);
  await layer(page).locator('#layer-park-right').click();
  await expect(layer(page).locator('#layer-tab')).toBeVisible();
  await expect.poll(async () => (await frameBox(page)).width).toBeLessThan(30);
  const tab = await frameBox(page);
  expect(Math.round(tab.x + tab.width)).toBe(PORTRAIT.width);
  await layer(page).locator('#layer-tab').click();
  await expect(layer(page).locator('#layer-button')).toBeVisible();
  // turned to landscape and back: the button is still inside the screen, and opens to the whole of it
  await page.setViewportSize(LANDSCAPE);
  await expect.poll(async () => { const b = await frameBox(page); return b.x >= 0 && b.y >= 0 && b.x + b.width <= LANDSCAPE.width && b.y + b.height <= LANDSCAPE.height; }).toBe(true);
  await openDrawer(page);
  await expect.poll(async () => { const b = await frameBox(page); return [Math.round(b.width), Math.round(b.height)]; }).toEqual([LANDSCAPE.width, LANDSCAPE.height]);
  await closeDrawer(page);
  await page.setViewportSize(PORTRAIT);
  await expect.poll(async () => { const b = await frameBox(page); return b.x + b.width <= PORTRAIT.width && b.y + b.height <= PORTRAIT.height; }).toBe(true);
  await close(ana, ben);
});

test('the keyboard: the button opens with Enter, Escape closes it and focus returns; closed, BLUFF has its own keys back', async ({ browser, request }) => {
  const { ana, ben } = await bluff(browser, request);
  const page = ben.page;
  await layer(page).locator('#layer-button').focus();
  await page.keyboard.press('Enter');
  await expect(layer(page).locator('#layer-sheet')).toBeVisible();
  await expect.poll(() => isOpen(page)).toBe(true);
  await page.keyboard.press('Escape');                                    // the drawer's Escape, inside the Party's frame
  await expect(layer(page).locator('#layer-sheet')).toBeHidden();
  await expect.poll(() => isOpen(page)).toBe(false);
  await expect(layer(page).locator('#layer-button')).toBeFocused();
  // closed, the game is usable as before: its rules sheet opens and closes with its own keys
  await page.locator('#rules').click();
  await expect(page.locator('#briefing')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('#briefing')).toBeHidden();
  await expect(page.locator('#rules')).toBeFocused();
  await close(ana, ben);
});

test('BLUFF stays quiet while the drawer is open and catches up when it closes', async ({ browser, request }) => {
  const { ana, ben } = await bluff(browser, request);
  const income = (p: Phone) => p.page.getByRole('button', { name: /Income/ });
  let mover = ana, watcher = ben;
  await expect.poll(async () => {
    for (const [m, w] of [[ana, ben], [ben, ana]] as const) {
      if (await income(m).isVisible() && await income(m).isEnabled()) { mover = m; watcher = w; return true; }
    }
    return false;
  }, { timeout: 30_000, intervals: [300] }).toBe(true);
  const live = () => watcher.page.locator('#live').innerText();
  const before = await live();
  const seen = (await rx(watcher.page)).length;
  await openDrawer(watcher.page);
  await income(mover).click();
  await expect.poll(async () => (await rx(watcher.page)).length, { timeout: 20_000 }).toBeGreaterThan(seen);
  expect(await live()).toBe(before);
  await closeDrawer(watcher.page);
  await expect.poll(live, { timeout: 10_000 }).not.toBe(before);
  await close(ana, ben);
});

test('a lost connection is said in the drawer and recovers; the seat is kept', async ({ browser, request }) => {
  const { ana, ben } = await bluff(browser, request);
  await openDrawer(ben.page);
  await ben.context.setOffline(true);
  await expect(layer(ben.page).locator('#layer-link')).not.toBeEmpty({ timeout: 30_000 });
  await ben.context.setOffline(false);
  await expect(layer(ben.page).locator('#layer-link')).toBeEmpty({ timeout: 40_000 });
  await expect(layer(ben.page).locator('#layer-people-list li')).toHaveCount(2);
  await expect.poll(async () => (await rx(ben.page)).filter((m: any) => m.type === 'state' && m.game).at(-1)?.game?.me?.cards?.length ?? 0).toBe(2);
  await expect(ben.page.locator(FRAME)).toHaveCount(1);
  await close(ana, ben);
});

test('forged layer messages from the game page move nothing, and the page cannot ask the frame for anything', async ({ browser, request }) => {
  const { ana, ben } = await bluff(browser, request);
  const page = ben.page;
  const before = await frameBox(page);
  await page.evaluate(() => {
    // the page posts to itself as if it were the Party frame: the mount listens only to its frame
    for (const m of [{ type: 'place', mode: 'open', side: 'left', y: 0 }, { type: 'drag', x: 0, y: 0 }, { type: 'hide' }])
      window.postMessage({ avrana: 'avrana.party-layer/v1', ...m }, '*');
    // and asks the frame for what it does not answer: Host verbs, a view, other protocols
    const f = (document.querySelector('iframe[data-avrana-party-layer]') as HTMLIFrameElement).contentWindow!;
    for (const m of [{ avrana: 'avrana.party-layer/v1', type: 'end' }, { avrana: 'avrana.party-layer/v1', type: 'open' },
      { avrana: 'avrana.party-bridge/v1', type: 'end', id: 'r1' }, { avrana: 'avrana.party-bridge/v1', type: 'ticket', id: 'r2' }, 'end'])
      f.postMessage(m, '*');
  });
  await page.waitForTimeout(1500);
  expect(await frameBox(page)).toEqual(before);
  await expect(page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'button');
  expect(await isOpen(page)).toBe(false);
  await expect(layer(page).locator('#layer-sheet')).toBeHidden();
  const state = await (await ana.page.goto(`${PARTY}/party/api/state`))!.json();
  expect(state.state).toBe('active');                                     // nothing ended: the round is still on
  await close(ana, ben);
});

test('an origin the Party has not registered gets no layer: the frame is refused and says nothing', async ({ browser, request }) => {
  const { ana, ben } = await bluff(browser, request);
  const eve = await phone(browser);
  await eve.page.goto(`${STRANGER}/shared/avrana-party-layer.js`);       // any document on that origin
  const shown = await eve.page.evaluate(async (party) => {
    const { mountPartyLayer } = await import('/shared/avrana-party-layer.js');
    const got: unknown[] = [];
    addEventListener('message', (e) => { if (e.origin === party) got.push(e.data); });
    const l = mountPartyLayer({ partyOrigin: party, game: 'bluff' });
    await new Promise((r) => setTimeout(r, 4000));
    const out = { visible: l.frame.style.visibility, got };
    l.stop();
    return out;
  }, PARTY);
  expect(shown.visible).toBe('hidden');                                   // never placed, never shown
  expect(shown.got).toEqual([]);                                          // frame-ancestors refused it: not even `ready`
  await close(ana, ben, eve);
});

test('mounting and stopping again and again leaves one frame or none, and no listener behind', async ({ browser, request }) => {
  const { ana, ben } = await bluff(browser, request);
  const page = ben.page;
  const left = await page.evaluate(async () => {
    const { mountPartyLayer } = await import('/shared/avrana-party-layer.js?again');
    const party = (await (await fetch('/api/avrana', { cache: 'no-store' })).json()).partyOrigin;
    const counts: number[] = [];
    for (let i = 0; i < 10; i++) {
      const l = mountPartyLayer({ partyOrigin: party, game: 'bluff' });
      counts.push(document.querySelectorAll('iframe[data-avrana-party-layer]').length);
      l.stop();
    }
    return { counts, after: document.querySelectorAll('iframe[data-avrana-party-layer]').length };
  });
  expect(left.counts).toEqual(Array(10).fill(2));                         // the page's own layer, and the one being tried
  expect(left.after).toBe(1);                                              // only the page's own remains
  await placed(page);
  await openDrawer(page);                                                  // and it still works
  await closeDrawer(page);
  // a new round mounts a fresh frame: End, then BLUFF again
  await openDrawer(ana.page);
  await layer(ana.page).locator('#layer-actions [data-action="end"]').click();
  await layer(ana.page).locator('#layer-yes').click();
  for (const p of [ana, ben]) await p.page.waitForURL(`${PARTY}/party/`, { timeout: 30_000 });
  await launch(ana.page, 'bluff');
  for (const p of [ana, ben]) {
    await p.page.goto(`${GAMES}/games/bluff/?avrana=1`);
    await placed(p.page);
    await expect(p.page.locator(FRAME)).toHaveCount(1);
  }
  await close(ana, ben);
});

test('EXPO on the game origin: the button mounts, the drawer names the people, a reload keeps it, nothing of EXPO covers it', async ({ browser, request }) => {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser), ben = await phone(browser);
  await join(ana.page, 'Ana');
  await join(ben.page, 'Ben');
  await launch(ana.page, 'expo');
  for (const p of [ana, ben]) {
    await p.page.goto(`${GAMES}/games/expo/?avrana=1`);
    await placed(p.page);
    await expect(p.page.locator(FRAME)).toHaveAttribute('src', `${PARTY}/party/layer.html?game=expo`);
  }
  const page = ben.page;
  const hit = await page.evaluate((sel) => {
    const f = document.querySelector(sel) as HTMLElement, r = f.getBoundingClientRect();
    return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === f;
  }, FRAME);
  expect(hit).toBe(true);
  await openDrawer(page);
  await expect(layer(page).locator('#layer-people-list li')).toHaveCount(2);
  await expect(layer(page).locator('#layer-people-list li', { hasText: 'Ana' })).toContainText('Host');
  await expect(layer(page).locator('#layer-host')).toBeHidden();
  await closeDrawer(page);
  await page.reload();
  await placed(page);
  for (const p of [ana, ben]) await holdsNoParty(p);
  await close(ana, ben);
});
