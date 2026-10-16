import { test, expect, type FrameLocator, type Page } from '@playwright/test';
import { phone, post, version, view, type Phone } from '../lib/phones';

/**
 * The Party layer over a game (AVR-292; docs/design/proposals/2026-10-16-control-center.md): the
 * floating Party button a game page mounts (bridge/layer-mount.js), drawn by the Party's own frame
 * (layer.html). People, the Party's chat, the Host's controls with a confirmation, and the
 * AssistiveTouch-style button: tap opens, long-press drags, pushed into a side it tucks into a tab.
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

  test('long-press drags the button; it settles on the nearer side and stays there after a reload', async () => {
    await startRound(host, [bob]);
    const vw = bob.page.viewportSize()!.width;
    await placed(bob.page);
    const start = await frameBox(bob.page);
    expect(start.x, 'starts on the right').toBeGreaterThan(vw / 2);
    await longPressDrag(bob.page, { x: 80, y: start.y + 120 });
    await expect.poll(async () => (await frameBox(bob.page)).x).toBeLessThan(20);
    const settled = await frameBox(bob.page);
    expect(settled.y).toBeGreaterThan(start.y + 60);
    await expect(layerOf(bob.page).locator('#layer-sheet'), 'a drag is not a tap').toBeHidden();
    await bob.page.reload();
    await expect(layerOf(bob.page).locator('#layer-button')).toBeVisible();
    await expect.poll(async () => (await frameBox(bob.page)).x).toBeLessThan(20);
  });

  test('pushed into the side it tucks into a tab with an arrow; the tab brings the button back', async () => {
    await startRound(host, [bob]);
    const vw = bob.page.viewportSize()!.width;
    await placed(bob.page);
    const start = await frameBox(bob.page);
    await longPressDrag(bob.page, { x: vw - 2, y: start.y + start.height / 2 });
    const layer = layerOf(bob.page);
    await expect(layer.locator('#layer-tab')).toBeVisible();
    await expect(layer.locator('#layer-button')).toBeHidden();
    await expect.poll(async () => (await frameBox(bob.page)).width).toBeLessThan(30);
    expect(Math.round((await frameBox(bob.page)).x + (await frameBox(bob.page)).width)).toBe(vw);
    await layer.locator('#layer-tab').click();
    await expect(layer.locator('#layer-button')).toBeVisible();
    await expect(layer.locator('#layer-button')).toBeFocused();
  });

  test('without dragging: the drawer moves the button to the other side or tucks it away', async () => {
    await startRound(host, [bob]);
    let layer = await openLayer(bob.page);
    await layer.locator('#layer-tuck').click();
    await expect(layer.locator('#layer-tab')).toBeVisible();
    await expect(layer.locator('#layer-tab')).toBeFocused();
    await layer.locator('#layer-tab').click();
    layer = await openLayer(bob.page);
    await layer.locator('#layer-move').click();
    await bob.page.keyboard.press('Escape');
    await expect.poll(async () => (await frameBox(bob.page)).x).toBeLessThan(20);
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
    await host.page.keyboard.press('Escape');
    await expect(layer.locator('#layer-sheet')).toBeHidden();
    await expect(layer.locator('#layer-button')).toBeFocused();
    expect((await view(host)).location.at).toBe('game');
  });
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

test('layer.html may be framed by the Party itself and the game origin, nothing else', async ({ request }) => {
  const res = await request.get('/party/layer.html');
  expect(res.status()).toBe(200);
  const csp = res.headers()['content-security-policy'];
  expect(csp).toMatch(/frame-ancestors 'self' \S+/);
  expect(csp).not.toContain("frame-ancestors 'none'");
  expect((await request.get('/party/')).headers()['content-security-policy']).toContain("frame-ancestors 'none'");
});
