import { test, expect, type Frame, type Page } from '@playwright/test';
import { phone, post, version, type Phone } from '../lib/phones';

/**
 * The controller shortcut into the Party drawer (AVR-581; web/party/lib/controller.js). A connected
 * controller keeps the floating button; a shortcut is learned, then must work once before hiding is
 * offered; the shortcut opens the same drawer; a disconnect brings the button back at once.
 *
 * Tier 2: Chromium against the dev server's Party Core and a stub game page, with navigator.getGamepads
 * replaced in every frame by a fake the test presses. Not a real controller, not Safari, not a phone:
 * whether a browser delivers the Home button, and in a frame of another origin, is the hardware matrix.
 */

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

const FRAME = 'iframe[title="Your Party"]';

async function withFakePad(p: Phone) {
  await p.context.addInitScript(() => {
    try { localStorage.setItem('avrana-test-layer', '1'); } catch { /* none */ }
    (window as any).__pads = [];
    Object.defineProperty(Navigator.prototype, 'getGamepads', { configurable: true, value() { return (window as any).__pads; } });
  });
}

async function layerFrame(page: Page): Promise<Frame> {
  await expect(page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'button');
  return (await (await page.locator(FRAME).elementHandle())!.contentFrame())!;
}

/** Press (or let go of) buttons on a fake standard-mapping controller; null pulls it out. */
async function pad(frame: Frame, down: number[] | null) {
  await frame.evaluate((d) => {
    const w = window as any;
    w.__ts = (w.__ts || 0) + 1;
    w.__pads = d === null ? [] : [{ id: 'Xbox Wireless Controller', mapping: 'standard', index: 0, connected: true,
      timestamp: w.__ts, buttons: Array.from({ length: 17 }, (_, i) => ({ pressed: d.includes(i), value: d.includes(i) ? 1 : 0 })) }];
  }, down);
}

async function hold(frame: Frame, down: number[]) {
  await pad(frame, down);
  await frame.page().waitForTimeout(1100);
  await pad(frame, []);
  await frame.page().waitForTimeout(150);
}

test('controller: bare connection keeps the button; learn, verify, hide by choice; the shortcut opens the drawer; disconnect restores', async ({ browser }) => {
  const host = await phone(browser, 'Ada');
  const bob = await phone(browser, 'Bob');
  for (const p of [host, bob]) await withFakePad(p);
  try {
    expect((await post(host, 'session/launch', { game: 'expo', if_version: await version(host) })).status()).toBe(200);
    await expect(bob.page).toHaveURL(/\/games\/expo\/\?avrana=1/);
    const page = bob.page, frame = await layerFrame(page);
    const layer = page.frameLocator(FRAME);

    // A controller arrives: the button stays (owner decision), and nothing is offered to hide it yet.
    await pad(frame, []);
    await page.waitForTimeout(300);
    await expect(page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'button');
    await layer.locator('#layer-button').click();
    await expect(layer.locator('#layer-pad-status')).toContainText('The Party button stays on screen');
    await expect(layer.locator('#layer-pad-hide-row')).toBeHidden();

    // Learn: one game button alone is refused; View + Menu is taken, then must work once.
    await layer.locator('#layer-pad-learn').click();
    await hold(frame, [0]);
    await expect(layer.locator('#layer-pad-status')).toContainText('One button alone');
    await hold(frame, [8, 9]);
    await expect(layer.locator('#layer-pad-status')).toContainText('Now hold View + Menu again');
    await expect(layer.locator('#layer-pad-hide-row')).toBeHidden();
    await hold(frame, [8, 9]);
    await expect(layer.locator('#layer-pad-status')).toContainText('Hold View + Menu to open this menu');
    await expect(layer.locator('#layer-sheet')).toBeVisible();          // verifying did not close the drawer

    // Hide by choice: closing the drawer leaves nothing over the game.
    await layer.locator('#layer-pad-hide').check();
    await layer.locator('#layer-close').click();
    await expect(page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'hidden');

    // Normal play (a tap, half the chord) does not open it; the shortcut opens the same drawer.
    await pad(frame, [8]); await page.waitForTimeout(1000); await pad(frame, [0, 9]); await page.waitForTimeout(300); await pad(frame, []);
    await expect(page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'hidden');
    await hold(frame, [8, 9]);
    await expect(page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'open');
    await expect(layer.locator('#layer-people-list')).toContainText('Ada');
    await hold(frame, [8, 9]);                                          // the same shortcut closes it
    await expect(page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'hidden');

    // Pull the controller out: the button is back at once, and the setting is kept for next time.
    await pad(frame, null);
    await expect(page.locator(FRAME)).toHaveAttribute('data-avrana-party-layer', 'button', { timeout: 500 });
    const kept = await frame.evaluate(() => JSON.parse(localStorage.getItem('avrana-controller/v1') || 'null'));
    expect(kept).toEqual({ v: 1, shortcut: { buttons: [8, 9], mapping: 'standard', id: '' }, verified: true, hide: true });

    // The Host's page never moved, and no round control fired.
    await expect(host.page).toHaveURL(/\/games\/expo\/\?avrana=1/);
  } finally {
    for (const p of [host, bob]) await p.context.close();
  }
});
