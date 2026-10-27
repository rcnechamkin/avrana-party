import { test, expect, type Page } from '@playwright/test';
import { place } from '../lib/frame';

/**
 * The owner's shelves (AVR-155) in the page: the committed contracts/shelves.json places nothing until
 * the owner decides (D1), so this serves the real catalog with shelves added, as the build would write
 * them. Featured leads Home and the Library; classics then lab follow; hidden is not listed anywhere.
 * Chromium at phone sizes: not a real phone (docs/TESTING.md, Tier 3).
 */
const SHELVES = { checkers: 'classics', expo: 'featured', bluff: 'lab', 'ps1-worms': 'hidden' };

async function curated(page: Page, shelves: Record<string, string>) {
  await page.route('**/party/catalog.json', async (route) => {
    const doc = await (await route.fetch()).json();
    await route.fulfill({ json: { ...doc, shelves } });
  });
}

async function open(page: Page, where: 'home' | 'library') {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await place(page, where);
  await expect(page.locator('#games')).toHaveAttribute('aria-busy', 'false');
}

const shown = (page: Page) => page.locator('#games [data-game]').evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.game));

test.beforeEach(async ({ page }) => {
  expect((await page.request.post('/__test__/arcade/up')).status()).toBe(204);
});

test('the Library lists featured first, then unplaced, classics and lab, and leaves hidden out', async ({ page }) => {
  await curated(page, SHELVES);
  await open(page, 'library');
  expect(await shown(page)).toEqual(['expo', 'arcade-gauntlet2', 'ps1-bomberman', 'checkers', 'bluff']);
  await expect(page.locator('#game-count')).toHaveText('5 games');
  await expect(page.locator('#games [data-game="ps1-worms"]')).toHaveCount(0);
  // search does not find a hidden title either
  await page.locator('#game-search').fill('worms');
  await expect(page.locator('#games [data-game]')).toHaveCount(0);
});

test('Home leads with the featured title on a fresh phone, and a hidden one is on no shelf', async ({ page }) => {
  await curated(page, SHELVES);
  await open(page, 'home');
  await expect(page.locator('#home-lead [data-game]').first()).toHaveAttribute('data-game', 'expo');
  await expect(page.locator('#view-home [data-game="ps1-worms"]')).toHaveCount(0);
});

test('no shelves: the catalog order, exactly as before', async ({ page }) => {
  await open(page, 'library');
  expect(await shown(page)).toEqual(['bluff', 'checkers', 'expo', 'arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms']);
});
