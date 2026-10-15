import { test, expect } from '@playwright/test';
import { startForEveryone } from '../lib/frame';
import { phone, type Phone } from '../lib/phones';

/**
 * AVR-469 (EXPERIMENTAL, Tier 2): a game's contract may declare `requires.device_caps`; a phone
 * that fails one is shown Watch with Play disabled and the failing check in plain words, through
 * the EXISTING Play/Watch choice. Real Chromium and a real Party Core behind the dev server. The
 * fixture contract is BLUFF's catalog entry with a declared requirement added on one phone's
 * catalog.json (the shipped catalog declares none), and one phone's storage report is a small
 * quota. Nothing here proves a real phone's memory, Safari, or the game page's own preflight
 * (Tier 3, the owner).
 */
type Caps = Record<string, unknown>;

async function declare(p: Phone, caps: Caps | null) {
  if (!caps) return;
  await p.context.route('**/party/catalog.json', async (route) => {
    const doc = await (await route.fetch()).json();
    for (const game of doc.games) if (game.id === 'bluff') for (const pr of game.presentations) pr.requires.device_caps = caps;
    await route.fulfill({ json: doc });
  });
  await p.page.reload();
  await expect(p.page.locator('html')).toHaveAttribute('data-ready', 'true');
}

async function smallStorage(p: Phone, quotaMb: number) {
  await p.context.addInitScript((q) => {
    Object.defineProperty(navigator.storage, 'estimate', { value: async () => ({ quota: q * 1024 * 1024, usage: 0 }) });
  }, quotaMb);
  await p.page.reload();
  await expect(p.page.locator('html')).toHaveAttribute('data-ready', 'true');
}

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

test.describe('device requirements before Play', () => {
  let host: Phone, weak: Phone, plain: Phone;
  test.beforeEach(async ({ browser }) => {
    host = await phone(browser, 'Ada');
    weak = await phone(browser, 'Bob');
    plain = await phone(browser, 'Cleo');
  });
  test.afterEach(async () => { for (const p of [host, weak, plain]) await p.context.close(); });

  test('an impossible requirement leaves Watch, names the reason, and changes nobody else', async () => {
    await smallStorage(weak, 200);
    await declare(weak, { storage_mb: 2000 });
    await startForEveryone(host.page, 'bluff');
    for (const p of [host, weak, plain]) await expect(p.page.locator('#scene'), p.name).toBeVisible();
    await expect(weak.page.locator('#choose-play')).toBeDisabled();
    await expect(weak.page.locator('#choose-watch')).toBeEnabled();
    await expect(weak.page.locator('#scene-seat')).toContainText('does not have enough free storage');
    await expect(weak.page.locator('#scene-seat')).toContainText('You can watch this one.');
    await weak.page.locator('#choose-watch').click();
    await expect(weak.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    // a phone whose catalog declares nothing: exactly as before
    await expect(plain.page.locator('#choose-play')).toBeEnabled();
    await expect(plain.page.locator('#choose-watch')).toBeEnabled();
    await expect(plain.page.locator('#scene-seat')).toBeHidden();
    await expect(host.page.locator('#choose-play')).toBeEnabled();
  });

  test('requirements this phone meets leave Play open and say nothing', async () => {
    await declare(weak, { memory_mb: 16, opfs: true, webgl2_offscreen: 'main' });
    await startForEveryone(host.page, 'bluff');
    await expect(weak.page.locator('#scene')).toBeVisible();
    await expect(weak.page.locator('#choose-play')).toBeEnabled();
    await expect(weak.page.locator('#scene-seat')).toBeHidden();
    await weak.page.locator('#choose-play').click();
    await expect(weak.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'true');
  });

  test('shared memory is left to the game: Play stays open and the briefing says so', async () => {
    await declare(weak, { shared_memory: true });
    await startForEveryone(host.page, 'bluff');
    await expect(weak.page.locator('#choose-play')).toBeEnabled();
    await expect(weak.page.locator('#scene-seat')).toContainText('The game checks this phone’s shared memory when it starts.');
  });
});
