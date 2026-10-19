import { test, expect, type FrameLocator, type Page } from '@playwright/test';
import { keyboard, visibleHeight, visibleTop, withKeyboardModel } from '../lib/keyboard';
import { phone, post, version, view, type Phone } from '../lib/phones';

/**
 * The Party layer over a game (AVR-292; docs/design/proposals/2026-10-16-control-center.md): the
 * floating Party button a game page mounts (bridge/layer-mount.js), drawn by the Party's own frame
 * (layer.html). People, the Party's chat, the Host's controls with a confirmation, and the
 * AssistiveTouch-style button (AVR-579): tap opens, long-press drags and it stays where it is let go
 * (a place per orientation), the drawer or the arrow keys move it without a drag, and parking on an edge
 * as a tab is deliberate.
 *
 * Tier 2: Chromium at phone size against the dev server's real Party Core and its stub game pages
 * (opted in with localStorage avrana-test-layer). Not a phone, not Safari, not BLUFF or EXPO
 * themselves: their opt-in is the Games repository's paired change.
 */

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

const atGame = /\/games\/expo\/\?avrana=1/;
const atHome = /\/party\/(#.*)?$/;
const FRAME = 'iframe[title="Your Party"]';
const layerOf = (page: Page): FrameLocator => page.frameLocator(FRAME);

async function withLayer(p: Phone) {
  await p.context.addInitScript(() => { try { localStorage.setItem('avrana-test-layer', '1'); } catch { /* none */ } });
}

async function startRound(host: Phone, others: Phone[]) {
  expect((await post(host, 'session/launch', { game: 'expo', if_version: await version(host) })).status()).toBe(200);
  for (const p of [host, ...others]) await expect(p.page).toHaveURL(atGame);
}

async function openLayer(page: Page) {
  const layer = layerOf(page);
  await layer.locator('#layer-button').click();
  await expect(layer.locator('#layer-sheet')).toBeVisible();
  return layer;
}

/** The frame once the Party has placed it (it is hidden at 0,0 until then). */
async function placed(page: Page) {
  await expect(page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'button');
  await expect(layerOf(page).locator('#layer-button')).toBeVisible();
}

async function frameBox(page: Page) {
  return (await page.locator(FRAME).boundingBox())!;
}

/** Hold the button, then move the finger in small steps (the frame follows it) and let go. */
async function longPressDrag(page: Page, to: { x: number; y: number }) {
  await placed(page);
  const box = await frameBox(page);
  const from = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.waitForTimeout(550);
  await expect(layerOf(page).locator('#layer-button')).toHaveClass(/lifted/);
  const steps = Math.ceil(Math.hypot(to.x - from.x, to.y - from.y) / 6);
  for (let i = 1; i <= steps; i++) {
    await page.mouse.move(from.x + ((to.x - from.x) * i) / steps, from.y + ((to.y - from.y) * i) / steps);
    await page.waitForTimeout(16);
  }
  await page.mouse.up();
}

test.describe('the Party layer on a game page', () => {
  let host: Phone, bob: Phone;

  test.beforeEach(async ({ browser }) => {
    host = await phone(browser, 'Ada');
    bob = await phone(browser, 'Bob');
    await withLayer(host);
    await withLayer(bob);
  });
  test.afterEach(async () => { for (const p of [host, bob]) await p.context.close(); });

  test('a tap opens the Party over the game: who is here, the Host named; the game page is left as it was', async () => {
    await startRound(host, [bob]);
    await bob.page.evaluate(() => { (window as unknown as { gameState: number }).gameState = 42; });
    await bob.page.evaluate(() => {
      const w = window as unknown as { layerEvents: boolean[] };
      w.layerEvents = [];
      document.addEventListener('avrana-party-layer', (e) => w.layerEvents.push((e as CustomEvent).detail.open));
    });
    const layer = layerOf(bob.page);
    await expect(layer.locator('#layer-button')).toBeVisible();
    await expect(layer.locator('#layer-button')).toHaveAccessibleName('Your Party');
    await openLayer(bob.page);
    await expect(layer.locator('#layer-close')).toBeFocused();
    await expect(layer.locator('#layer-where')).toContainText('Playing');
    await expect(layer.locator('#layer-people-list li')).toHaveCount(2);
    await expect(layer.locator('#layer-people-list')).toContainText('Bob (you)');
    await expect(layer.locator('#layer-people-list li').filter({ hasText: 'Ada' }).locator('.avrana-tag')).toHaveText('Host');
    await expect(layer.locator('#layer-host'), 'no host controls for a follower').toBeHidden();
    await layer.locator('#layer-close').click();
    await expect(layer.locator('#layer-sheet')).toBeHidden();
    await expect(layer.locator('#layer-button')).toBeFocused();
    await expect(bob.page).toHaveURL(atGame);
    expect(await bob.page.evaluate(() => (window as unknown as { gameState: number }).gameState)).toBe(42);
    expect(await bob.page.evaluate(() => (window as unknown as { layerEvents: boolean[] }).layerEvents)).toEqual([true, false]);
  });

  test('chat from the game: a line from another phone is unread on the button, read in the drawer', async () => {
    await startRound(host, [bob]);
    const ada = await openLayer(host.page);
    await ada.locator('#layer-tab-chat').click();
    await expect(ada.locator('#chat-send')).toBeEnabled();
    await ada.locator('#chat-text').fill('Nice move');
    await ada.locator('#chat-text').press('Enter');
    await expect(ada.locator('#chat-text')).toHaveValue('');
    const layer = layerOf(bob.page);
    await expect(layer.locator('#layer-button')).toHaveAccessibleName('Your Party, 1 new message');
    await expect(layer.locator('#layer-unread')).toHaveText('1');
    await openLayer(bob.page);
    await layer.locator('#layer-tab-chat').click();
    await expect(layer.locator('#chat-messages .avrana-chat-line p')).toHaveText(['Nice move']);
    await expect(layer.locator('#chat-messages .avrana-chat-line strong')).toHaveText('Ada');
    await bob.page.keyboard.press('Escape');
    await expect(layer.locator('#layer-button')).toHaveAccessibleName('Your Party');
    // the same room as Party Home's
    await bob.page.goto('/party/');
    await expect(bob.page).toHaveURL(atGame);   // a member follows the Party back to its round
  });

  test('the Host ends the round from the layer, after a confirmation; Cancel changes nothing', async () => {
    await startRound(host, [bob]);
    const layer = await openLayer(host.page);
    await expect(layer.locator('#layer-actions button')).toHaveText(['End the round for everyone', 'Bring everyone back to Party Home', 'Hand over hosting']);
    await layer.locator('[data-action="end"]').click();
    await expect(layer.locator('#layer-confirm-text')).toHaveText('This ends the round for everyone. Everyone goes back to Party Home.');
    await expect(layer.locator('#layer-confirm-text')).toBeFocused();
    await layer.locator('#layer-no').click();
    await expect(layer.locator('[data-action="end"]')).toBeFocused();
    expect((await view(host)).location.at).toBe('game');
    await layer.locator('[data-action="end"]').click();
    await layer.locator('#layer-yes').click();
    for (const p of [host, bob]) await expect(p.page, p.name).toHaveURL(atHome);
    await expect(host.page.locator(FRAME), 'the layer goes with the round').toHaveCount(0);
  });

  test('the Host hands over hosting from the layer; the new Host gets the controls', async () => {
    await startRound(host, [bob]);
    const layer = await openLayer(host.page);
    await layer.locator('[data-action="handover"]').click();
    await expect(layer.locator('#layer-pick option')).toHaveText(['Bob']);
    await layer.locator('#layer-yes').click();
    await expect(layer.locator('#layer-host')).toBeHidden();
    expect((await view(bob)).me.host).toBe(true);
    const bobs = await openLayer(bob.page);
    await expect(bobs.locator('[data-action="end"]')).toBeVisible();
    await expect(bob.page).toHaveURL(atGame);
  });

  const PORTRAIT = { width: 375, height: 667 }, LANDSCAPE = { width: 667, height: 375 };
  const near = (got: { x: number; y: number }, want: { x: number; y: number }, tol = 3) => {
    expect(Math.abs(got.x - want.x), `x ${got.x} vs ${want.x}`).toBeLessThanOrEqual(tol);
    expect(Math.abs(got.y - want.y), `y ${got.y} vs ${want.y}`).toBeLessThanOrEqual(tol);
  };
  const within = (b: { x: number; y: number; width: number; height: number }, vp: { width: number; height: number }) => {
    expect(b.x).toBeGreaterThanOrEqual(0);
    expect(b.y).toBeGreaterThanOrEqual(0);
    expect(b.x + b.width).toBeLessThanOrEqual(vp.width);
    expect(b.y + b.height).toBeLessThanOrEqual(vp.height);
  };
  /** The page's own layout viewport as the layer frame sees it, after a resize has settled. */
  async function resize(page: Page, vp: { width: number; height: number }) {
    await page.setViewportSize(vp);
    await expect.poll(() => page.evaluate(() => innerWidth)).toBe(vp.width);
  }

  test('long-press drags the button; it stays exactly where it is let go, also after a reload', async () => {
    await startRound(host, [bob]);
    await resize(bob.page, PORTRAIT);
    await placed(bob.page);
    const start = await frameBox(bob.page);
    expect(start.x, 'starts on the right').toBeGreaterThan(PORTRAIT.width / 2);
    await longPressDrag(bob.page, { x: 140, y: start.y + 150 });
    const free = { x: 140 - start.width / 2, y: start.y + 150 - start.height / 2 };
    await expect.poll(async () => Math.abs((await frameBox(bob.page)).x - free.x)).toBeLessThanOrEqual(3);
    near(await frameBox(bob.page), free);                  // not on a side: nothing snapped it
    await expect(layerOf(bob.page).locator('#layer-sheet'), 'a drag is not a tap').toBeHidden();
    await bob.page.waitForTimeout(600);
    near(await frameBox(bob.page), free);                  // and nothing slides it later
    await bob.page.reload();
    await resize(bob.page, PORTRAIT);
    await placed(bob.page);
    near(await frameBox(bob.page), free);
  });

  test('let go beyond an edge it stops inside the screen; pushing is not parking', async () => {
    await startRound(host, [bob]);
    await resize(bob.page, PORTRAIT);
    await placed(bob.page);
    const start = await frameBox(bob.page);
    await longPressDrag(bob.page, { x: 1, y: start.y + start.height / 2 });
    const layer = layerOf(bob.page);
    await expect(layer.locator('#layer-button')).toBeVisible();
    await expect(layer.locator('#layer-tab')).toBeHidden();
    const box = await frameBox(bob.page);
    within(box, PORTRAIT);
    expect(box.width).toBeGreaterThan(40);                 // still the whole button, not a tab
  });

  test('a tap opens the Party; a finger that moves, or a short drag, does not', async () => {
    await startRound(host, [bob]);
    await resize(bob.page, PORTRAIT);
    await placed(bob.page);
    const layer = layerOf(bob.page);
    const box = await frameBox(bob.page);
    const c = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    // a quick swipe across it: not a tap, and the button did not move
    await bob.page.mouse.move(c.x, c.y);
    await bob.page.mouse.down();
    await bob.page.mouse.move(c.x - 30, c.y + 30, { steps: 5 });
    await bob.page.mouse.up();
    await expect(layer.locator('#layer-sheet')).toBeHidden();
    near(await frameBox(bob.page), box, 1);
    // a held press with no movement and then release: a drag of nothing; the next tap still opens
    await bob.page.waitForTimeout(600);
    await layer.locator('#layer-button').click();
    await expect(layer.locator('#layer-sheet')).toBeVisible();
  });

  test('turn the phone: each orientation keeps its own place; rotating back finds the first again', async () => {
    await startRound(host, [bob]);
    await resize(bob.page, PORTRAIT);
    await placed(bob.page);
    await longPressDrag(bob.page, { x: 120, y: 200 });
    const portrait = await frameBox(bob.page);
    await resize(bob.page, LANDSCAPE);
    await expect(layerOf(bob.page).locator('#layer-button')).toBeVisible();
    await expect.poll(async () => { const b = await frameBox(bob.page); return b.x + b.width <= LANDSCAPE.width && b.y + b.height <= LANDSCAPE.height; }).toBe(true);
    within(await frameBox(bob.page), LANDSCAPE);
    await longPressDrag(bob.page, { x: 500, y: 120 });
    const landscape = await frameBox(bob.page);
    near(landscape, { x: 500 - 24, y: 120 - 24 });
    await resize(bob.page, PORTRAIT);
    await expect.poll(async () => Math.abs((await frameBox(bob.page)).x - portrait.x)).toBeLessThanOrEqual(3);
    near(await frameBox(bob.page), portrait);
    await resize(bob.page, LANDSCAPE);
    await expect.poll(async () => Math.abs((await frameBox(bob.page)).x - landscape.x)).toBeLessThanOrEqual(3);
    near(await frameBox(bob.page), landscape);
    await bob.page.reload();                                // both are kept
    await resize(bob.page, LANDSCAPE);
    await placed(bob.page);
    near(await frameBox(bob.page), landscape);
    await resize(bob.page, PORTRAIT);
    await expect.poll(async () => Math.abs((await frameBox(bob.page)).x - portrait.x)).toBeLessThanOrEqual(3);
  });

  test('the viewport shrinks and grows: the button is clamped inside, then returns', async () => {
    await startRound(host, [bob]);
    await resize(bob.page, PORTRAIT);
    await placed(bob.page);
    await longPressDrag(bob.page, { x: 330, y: 600 });      // low and to the right
    const before = await frameBox(bob.page);
    const small = { width: 320, height: 400 };
    await resize(bob.page, small);
    await expect.poll(async () => { const b = await frameBox(bob.page); return b.x + b.width <= small.width && b.y + b.height <= small.height; }).toBe(true);
    within(await frameBox(bob.page), small);
    await resize(bob.page, PORTRAIT);
    await expect.poll(async () => Math.abs((await frameBox(bob.page)).y - before.y)).toBeLessThanOrEqual(3);
    near(await frameBox(bob.page), before);
  });

  test('only the button\'s own box takes touches; every other point reaches the game', async () => {
    await startRound(host, [bob]);
    await resize(bob.page, PORTRAIT);
    await placed(bob.page);
    await longPressDrag(bob.page, { x: 200, y: 400 });
    const box = await frameBox(bob.page);
    const tag = (x: number, y: number) => bob.page.evaluate(([px, py]) => document.elementFromPoint(px, py)?.tagName, [x, y]);
    expect(await tag(box.x + 24, box.y + 24)).toBe('IFRAME');
    expect(await tag(box.x + 1, box.y + 1), 'a corner of the box is still the button').toBe('IFRAME');
    for (const [dx, dy] of [[-3, 24], [51, 24], [24, -3], [24, 51], [-20, -20], [70, 70]]) {
      expect(await tag(box.x + dx, box.y + dy), `${dx},${dy}`).not.toBe('IFRAME');
    }
    expect(box.width, 'the frame is the button, no invisible margin').toBeLessThanOrEqual(48);
    await bob.page.evaluate(() => {
      const w = window as unknown as { taps: string[] };
      w.taps = [];
      document.addEventListener('pointerdown', (e) => w.taps.push((e.target as Element).tagName));
    });
    await bob.page.mouse.click(box.x - 4, box.y + 24);      // just beside it
    await bob.page.mouse.click(box.x + 24, box.y + 54);     // just under it
    expect((await bob.page.evaluate(() => (window as unknown as { taps: string[] }).taps)).length, 'both reached the game').toBe(2);
    await expect(layerOf(bob.page).locator('#layer-sheet')).toBeHidden();
    // parked as a tab: the same, only the tab's box
    await bob.page.waitForTimeout(600);        // a click right after a drag is not a tap
    const layer = await openLayer(bob.page);
    await layer.locator('#layer-park-right').click();
    await expect(layer.locator('#layer-tab')).toBeVisible();
    await expect.poll(async () => (await frameBox(bob.page)).width).toBeLessThan(30);
    const tab = await frameBox(bob.page);
    expect(await tag(tab.x + 10, tab.y + 30)).toBe('IFRAME');
    expect(await tag(tab.x - 3, tab.y + 30)).not.toBe('IFRAME');
    expect(await tag(tab.x + 10, tab.y + tab.height + 3)).not.toBe('IFRAME');
  });

  test('parking is deliberate: the drawer parks it on an edge as a tab; the tab brings it back', async () => {
    await startRound(host, [bob]);
    await resize(bob.page, PORTRAIT);
    await placed(bob.page);
    await longPressDrag(bob.page, { x: 180, y: 300 });
    const at = await frameBox(bob.page);
    await bob.page.waitForTimeout(600);        // a click right after a drag is not a tap
    let layer = await openLayer(bob.page);
    await layer.locator('#layer-park-left').click();
    await expect(layer.locator('#layer-sheet')).toBeHidden();
    await expect(layer.locator('#layer-tab')).toBeVisible();
    await expect(layer.locator('#layer-tab')).toBeFocused();
    await expect(layer.locator('#layer-button')).toBeHidden();
    await expect.poll(async () => (await frameBox(bob.page)).width).toBeLessThan(30);
    const tab = await frameBox(bob.page);
    expect(Math.round(tab.x), 'on the left edge').toBe(0);
    expect(Math.abs(tab.y + tab.height / 2 - (at.y + at.height / 2)), 'at the height it was').toBeLessThanOrEqual(12);
    await bob.page.reload();                                // parked stays parked
    await resize(bob.page, PORTRAIT);
    await expect(layerOf(bob.page).locator('#layer-tab')).toBeVisible();
    layer = layerOf(bob.page);
    await layer.locator('#layer-tab').click();
    await expect(layer.locator('#layer-button')).toBeVisible();
    await expect(layer.locator('#layer-button')).toBeFocused();
    const back = await frameBox(bob.page);
    expect(back.x, 'back at the edge it was parked on').toBeLessThanOrEqual(8);
    expect(back.width).toBeGreaterThan(40);
    // and the tab is recoverable on the right as well
    layer = await openLayer(bob.page);
    await layer.locator('#layer-park-right').click();
    await expect(layer.locator('#layer-tab')).toBeVisible();
    expect(Math.round((await frameBox(bob.page)).x + (await frameBox(bob.page)).width)).toBe(PORTRAIT.width);
    await layer.locator('#layer-tab').click();
    await expect(layer.locator('#layer-button')).toBeVisible();
  });

  test('without dragging: the drawer moves the button by steps, parks it, or resets it; the arrow keys move it too', async () => {
    await startRound(host, [bob]);
    await resize(bob.page, PORTRAIT);
    await placed(bob.page);
    const start = await frameBox(bob.page);
    let layer = await openLayer(bob.page);
    await expect(layer.locator('#layer-moves-h')).toHaveText('Party button position');
    await layer.locator('#layer-nudge-down').click();
    await layer.locator('#layer-nudge-left').click();
    await expect(layer.locator('#layer-live-note')).toHaveText('The button moves left.');
    await bob.page.keyboard.press('Escape');
    await expect.poll(async () => (await frameBox(bob.page)).y).toBeGreaterThan(start.y + 40);
    near(await frameBox(bob.page), { x: start.x - 48, y: start.y + 48 });
    // arrow keys, with the button itself focused
    await expect(layer.locator('#layer-button')).toBeFocused();
    await bob.page.keyboard.press('ArrowUp');
    await expect.poll(async () => (await frameBox(bob.page)).y).toBeLessThan(start.y + 10);
    near(await frameBox(bob.page), { x: start.x - 48, y: start.y });
    await expect(layer.locator('#layer-sheet'), 'arrows move, they do not open').toBeHidden();
    layer = await openLayer(bob.page);
    await layer.locator('#layer-reset').click();
    await bob.page.keyboard.press('Escape');
    await expect.poll(async () => Math.abs((await frameBox(bob.page)).x - start.x)).toBeLessThanOrEqual(3);
    near(await frameBox(bob.page), start);
    // every one of those controls is a real button a thumb can hit
    layer = await openLayer(bob.page);
    for (const id of ['nudge-up', 'nudge-down', 'nudge-left', 'nudge-right', 'park-left', 'park-right', 'reset']) {
      const b = (await layer.locator(`#layer-${id}`).boundingBox())!;
      expect(b.height, id).toBeGreaterThanOrEqual(44);
    }
  });

  test('keyboard only: Enter opens, Tab stays in the drawer, Escape closes back to the button', async () => {
    await startRound(host, [bob]);
    const layer = layerOf(host.page);
    await placed(host.page);
    // Tab from the game page's own controls into the Party's frame, as a keyboard does
    await host.page.locator('#nav a').last().focus();
    for (let i = 0; i < 6 && !(await layer.locator('#layer-button').evaluate((el) => el === document.activeElement && document.hasFocus())); i++) {
      await host.page.keyboard.press('Tab');
    }
    await expect(layer.locator('#layer-button')).toBeFocused();
    await host.page.keyboard.press('Enter');
    await expect(layer.locator('#layer-close')).toBeFocused();
    await host.page.keyboard.press('Tab');
    await expect(layer.locator('#layer-tab-people')).toBeFocused();
    // aria-modal: Tab goes round the drawer, never out to the game behind it
    for (let i = 0; i < 12; i++) await host.page.keyboard.press('Tab');
    expect(await layer.locator('#layer-sheet').evaluate((s) => s.contains(document.activeElement) && document.hasFocus())).toBe(true);
    await layer.locator('#layer-close').focus();
    await host.page.keyboard.press('Shift+Tab');
    await expect(layer.locator('#layer-reset')).toBeFocused();
    await host.page.keyboard.press('Escape');
    await expect(layer.locator('#layer-sheet')).toBeHidden();
    await expect(layer.locator('#layer-button')).toBeFocused();
    expect((await view(host)).location.at).toBe('game');
  });
});

test('mounted by a page itself (the vendored file): a phone that is no longer a member gets the game back, nothing over it', async ({ browser }) => {
  const host = await phone(browser, 'Ada');
  const bob = await phone(browser, 'Bob');
  try {
    await startRound(host, [bob]);
    await bob.page.evaluate(async () => {
      const { mountPartyLayer } = await import('/party/bridge/layer-mount.js');
      mountPartyLayer({ partyOrigin: location.origin, game: 'expo' });
    });
    await openLayer(bob.page);
    await expect(bob.page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'open');
    await bob.page.evaluate(() => localStorage.removeItem('wc-name'));   // so nothing joins again
    expect((await post(bob, 'leave', {})).status()).toBe(200);
    await expect(bob.page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'hidden');
    await expect(bob.page.locator(FRAME)).toHaveCSS('visibility', 'hidden');
    const box = (await bob.page.locator('h1').boundingBox())!;
    expect(await bob.page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.tagName, [box.x + 5, box.y + 5])).toBe('H1');
  } finally { await host.context.close(); await bob.context.close(); }
});

test('a game page that does not opt in has no layer', async ({ browser }) => {
  const host = await phone(browser, 'Ada');
  try {
    await startRound(host, []);
    await host.page.waitForTimeout(500);
    await expect(host.page.locator(FRAME)).toHaveCount(0);
  } finally { await host.context.close(); }
});

test('a small phone: the drawer fits, nothing sideways, every control a thumb can hit', async ({ browser }) => {
  const small = await phone(browser, 'Dee', { viewport: { width: 320, height: 568 }, isMobile: true, hasTouch: true });
  const other = await phone(browser, 'Eve');
  try {
    await withLayer(small);
    await startRound(small, [other]);
    const layer = layerOf(small.page);
    await layer.locator('#layer-button').tap();
    await expect(layer.locator('#layer-sheet')).toBeVisible();
    const sheet = (await layer.locator('#layer-sheet').boundingBox())!;
    expect(sheet.x).toBeGreaterThanOrEqual(0);
    expect(sheet.x + sheet.width).toBeLessThanOrEqual(320);
    expect(sheet.y + sheet.height).toBeLessThanOrEqual(568);
    const frame = small.page.frame({ url: /\/party\/layer\.html/ })!;
    expect(await frame.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const tiny = await frame.$$eval('#layer-sheet button:not([hidden]), #layer-sheet select', (els) => els
      .filter((el) => { const b = el.getBoundingClientRect(); return el.getClientRects().length > 0 && b.width > 0 && (b.height < 44 || b.width < 44); })
      .map((el) => el.id || (el.textContent || '').trim()));
    expect(tiny).toEqual([]);
    expect(await small.page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  } finally { await small.context.close(); await other.context.close(); }
});

/**
 * UX-07 / AVR-579: the keyboard opens over the Party chat inside a game. SIMULATED (tests/lib/
 * keyboard.ts: visualViewport shrinks, the layout viewport does not, as on iPhone Safari and
 * Android Chrome); not a real iOS or Android keyboard, and not the game's own pan or scroll.
 */
for (const size of [
  { name: 'small portrait', viewport: { width: 320, height: 568 }, keys: 260 },
  { name: 'landscape', viewport: { width: 740, height: 360 }, keys: 170 },
]) {
  test(`keyboard over the in-game chat (${size.name}): composer above the keys, drawer open, draft and game kept`, async ({ browser }) => {
    const dee = await phone(browser, 'Dee', { viewport: size.viewport, isMobile: true, hasTouch: true });
    const eve = await phone(browser, 'Eve');
    try {
      await withLayer(dee);
      await withKeyboardModel(dee.context);
      await startRound(dee, [eve]);
      for (let i = 0; i < 5; i++) {
        expect((await post(eve, 'messages', { party: (await view(eve)).party, text: `message number ${i} with a few more words in it so that it wraps`,
          client_id: `kb-layer-${size.name.replace(/ /g, '-')}-${i}` })).status()).toBe(200);
      }
      await dee.page.evaluate(() => { (window as unknown as { gameState: number }).gameState = 42; });
      const layer = layerOf(dee.page);
      await placed(dee.page);
      await layer.locator('#layer-button').tap();
      await layer.locator('#layer-tab-chat').tap();
      await expect(layer.locator('#chat-send')).toBeEnabled();
      await expect(layer.locator('#chat-messages .avrana-chat-line')).toHaveCount(5);
      const text = layer.locator('#chat-text');
      await text.fill('half a thought');
      await text.focus();
      await layer.locator('#chat').evaluate((el) => { el.scrollTop = 40; });
      const scrolled = await layer.locator('#chat').evaluate((el) => el.scrollTop);

      for (const cycle of [size.keys, 0, size.keys]) {
        await keyboard(dee.page, cycle);
        const visible = await visibleHeight(dee.page);
        await expect(dee.page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'open');
        await expect(layer.locator('#layer-sheet')).toBeVisible();
        await expect(text).toBeFocused();
        await expect(text).toHaveValue('half a thought');
        // measured in the page's coordinates: the frame sits at the page's top-left when open
        await expect.poll(async () => {
          const f = (await dee.page.locator(FRAME).boundingBox())!;
          const b = (await layer.locator('#chat-form').boundingBox())!;
          return f.y + b.y + b.height;
        }).toBeLessThanOrEqual(visible + 0.5);
        expect(await layer.locator('#chat').evaluate((el) => el.scrollTop)).toBe(scrolled);
      }
      expect(await dee.page.evaluate(() => (window as unknown as { gameState: number }).gameState)).toBe(42);
      await expect(dee.page).toHaveURL(atGame);
    } finally { await dee.context.close(); await eve.context.close(); }
  });
}

test('layer.html may be framed by the Party itself and the game origin, nothing else', async ({ request }) => {
  const res = await request.get('/party/layer.html');
  expect(res.status()).toBe(200);
  const csp = res.headers()['content-security-policy'];
  expect(csp).toMatch(/frame-ancestors 'self' \S+/);
  expect(csp).not.toContain("frame-ancestors 'none'");
  expect((await request.get('/party/')).headers()['content-security-policy']).toContain("frame-ancestors 'none'");
});

/**
 * AVR-583: the same panned keyboard and a turn of the phone with the keyboard up, in the Party-origin
 * layer over a game. The open frame is placed in the game page's layout coordinates, so it must follow
 * visualViewport.offsetTop; the draft, the open drawer, the game's state and the URL must survive, and a
 * collapsed button must remain only its own box afterwards. SIMULATED (tests/lib/keyboard.ts).
 */
test('layer: keyboard panned and the phone turned keep the drawer inside the visible region, the draft and the game', async ({ browser }) => {
  const dee = await phone(browser, 'Dee', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const eve = await phone(browser, 'Eve');
  try {
    await withLayer(dee);
    await withKeyboardModel(dee.context);
    await startRound(dee, [eve]);
    await dee.page.evaluate(() => { (window as unknown as { gameState: number }).gameState = 42; });
    const layer = layerOf(dee.page);
    await placed(dee.page);
    await layer.locator('#layer-button').tap();
    await layer.locator('#layer-tab-chat').tap();
    await expect(layer.locator('#chat-send')).toBeEnabled();
    const text = layer.locator('#chat-text');
    await text.fill('half a thought');
    await text.focus();

    const inRegion = async (label: string) => {
      const top = await visibleTop(dee.page), height = await visibleHeight(dee.page);
      await expect(dee.page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'open');
      await expect.poll(async () => {
        // a frame locator's boxes are already in the page's coordinates
        const sheet = (await layer.locator('#layer-sheet').boundingBox())!, form = (await layer.locator('#chat-form').boundingBox())!;
        return [sheet.y >= top - 0.5, form.y + form.height <= top + height + 0.5];
      }, { message: `${label}: sheet top and composer bottom inside the visible region (${top}..${top + height})` }).toEqual([true, true]);
      await expect(text).toBeFocused();
      await expect(text).toHaveValue('half a thought');
    };

    await keyboard(dee.page, 336, 120);
    await inRegion('portrait, keyboard up and panned');
    await dee.page.setViewportSize({ width: 844, height: 390 });
    await keyboard(dee.page, 170, 60);
    await inRegion('landscape, keyboard up and panned');
    await dee.page.setViewportSize({ width: 390, height: 844 });
    await keyboard(dee.page, 0, 0);
    await inRegion('portrait, keyboard closed');

    expect(await dee.page.evaluate(() => (window as unknown as { gameState: number }).gameState)).toBe(42);
    await expect(dee.page).toHaveURL(atGame);
    await layer.locator('#layer-sheet').press('Escape');   // closing returns the frame to the button alone
    await expect(dee.page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'button');
    const box = await frameBox(dee.page);
    expect(box.width).toBeLessThanOrEqual(48 + 0.5);
    expect(box.height).toBeLessThanOrEqual(48 + 0.5);
  } finally { await dee.context.close(); await eve.context.close(); }
});
