import { test, expect } from '@playwright/test';
import path from 'node:path';
import { place } from '../lib/frame';
import { cutOff, phone, type Phone } from '../lib/phones';

/**
 * The owner's game covers and a break in the link (AVR-306). A cover that does not load gives
 * way to the art the game had (tests/offline/covers.spec.ts); one that did not load while the
 * Party box was away must not stay gone for as long as the page lives. Two phones against the
 * dev server's real Party Core; the cover is a flat square made for the tests. Not a real phone.
 */
const FIXTURE = path.resolve(__dirname, '..', 'fixtures', 'covers', 'arcade-gauntlet2.png');
const INDEX = { schema: 'avrana.covers/v0', covers: { 'arcade-gauntlet2': 'covers/arcade-gauntlet2.png' } };

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

test('a cover that did not load while the box was away is tried again once the box answers', async ({ browser }) => {
  const ada: Phone = await phone(browser, 'Ada'), bob: Phone = await phone(browser, 'Bob');
  try {
    let reach = false, asked = 0;
    await ada.context.route('**/party/covers/index.json', (route) => route.fulfill({ json: INDEX }));
    await ada.context.route('**/party/covers/arcade-gauntlet2.png', (route) => {
      asked += 1;
      return reach ? route.fulfill({ path: FIXTURE, contentType: 'image/png' }) : route.abort();
    });
    await ada.page.reload();
    await expect(ada.page.locator('html')).toHaveAttribute('data-ready', 'true');
    await place(ada.page, 'library');
    const img = ada.page.locator('#games [data-game="arcade-gauntlet2"] .avrana-cover img').first();
    await expect(img).toHaveAttribute('src', 'art/kenney-sword.svg');        // the picture was out of reach: the art it had
    expect(asked).toBeGreaterThan(0);

    const back = await cutOff(ada, bob);
    await expect(ada.page.locator('html')).toHaveAttribute('data-link', 'reconnecting');
    await expect(img).toHaveAttribute('src', 'art/kenney-sword.svg');        // nothing is retried while the box is away
    reach = true;
    await back();
    await expect(ada.page.locator('html')).toHaveAttribute('data-link', 'ok', { timeout: 12_000 });
    await expect(img).toHaveAttribute('src', 'covers/arcade-gauntlet2.png', { timeout: 12_000 });
    await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);
    await expect(ada.page.locator('#games [data-game="arcade-gauntlet2"]').first()).toContainText('Gauntlet II');
  } finally {
    await ada.context.close();
    await bob.context.close();
  }
});
