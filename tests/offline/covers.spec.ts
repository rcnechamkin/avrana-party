import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';
import { openGame, place, sideways } from '../lib/frame';
import { lowContrast, unnamed } from '../lib/a11y';

/**
 * The owner's game covers in the shell (AVR-306, Tier 2). A cover is a picture the owner keeps
 * outside Git; covers/index.json says which games have one. The dev server serves none under
 * test controls, so each test answers the page's own requests for the index and the pictures
 * (two flat squares in tests/fixtures/covers, made for this). What a covers folder may hold, and
 * what the build and the installer do with it, is tests/unit/test_web_covers.py and
 * test_web_build.py. Chromium at phone sizes: not a real phone.
 */
const FIXTURES = path.resolve(__dirname, '..', 'fixtures', 'covers');
const INDEX = { schema: 'avrana.covers/v0', covers: {
  'ps1-worms': 'covers/ps1-worms.png', 'arcade-gauntlet2': 'covers/arcade-gauntlet2.png',
  bluff: 'covers/../art/kenney-sword.svg',           // not a cover's path: ignored
  expo: 'covers/ps1-worms.png',                      // another game's picture: ignored
} };
const cover = (page: Page, within: string, id: string) => page.locator(`${within} [data-game="${id}"] .avrana-cover`).first();

async function withCovers(page: Page, index: unknown = INDEX) {
  await page.route('**/party/covers/index.json', (route) => route.fulfill({ json: index }));
  for (const name of ['ps1-worms.png', 'arcade-gauntlet2.png'])
    await page.route(`**/party/covers/${name}`, (route) => route.fulfill({ path: path.join(FIXTURES, name), contentType: 'image/png' }));
}

async function open(page: Page) {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
}

/** Every picture on screen has been drawn: none is a broken image. */
const broken = (page: Page) => page.evaluate(() => [...document.querySelectorAll('img')]
  .filter((img) => img.getClientRects().length > 0 && img.complete && img.naturalWidth === 0).map((img) => img.getAttribute('src')));

test('a cover the owner supplied stands for its game on Home, in the Library and on the game’s page; the rest keep their art', async ({ page }) => {
  await withCovers(page);
  await open(page);
  // Home's shelf
  await expect(cover(page, '#view-home', 'arcade-gauntlet2').locator('img')).toHaveAttribute('src', 'covers/arcade-gauntlet2.png');
  await expect(cover(page, '#view-home', 'arcade-gauntlet2')).toHaveClass(/own-art/);
  // the Library, in every view
  await place(page, 'library');
  for (const view of ['medium', 'large', 'compact', 'list']) {
    await page.locator('#lib-view').click();
    await page.locator(`#view-choices [data-v="${view}"]`).click();
    await page.keyboard.press('Escape');
    await expect(page.locator('#lib-views')).toBeHidden();
    for (const id of ['ps1-worms', 'arcade-gauntlet2']) {
      const img = cover(page, '#games', id).locator('img');
      await img.scrollIntoViewIfNeeded();
      await expect(img, `${view} ${id}`).toHaveAttribute('src', `covers/${id}.png`);
      await expect(img).toHaveAttribute('alt', '');                         // decoration: the name beside it is the name
      await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth), { message: `${view} ${id} drawn` }).toBeGreaterThan(0);
    }
    // a game with no cover, and the two entries of the index that are not covers, keep what they had
    await expect(cover(page, '#games', 'bluff').locator('img')).toHaveAttribute('src', 'art/lan-bluff.svg');
    await expect(cover(page, '#games', 'bluff')).not.toHaveClass(/own-art/);
    await expect(cover(page, '#games', 'expo').locator('img')).toHaveCount(0);
    await expect(cover(page, '#games', 'ps1-bomberman').locator('img')).toHaveAttribute('src', 'art/kenney-exploding.svg');
    await expect(page.locator('#games [data-game="ps1-worms"]').first()).toContainText('Worms Armageddon');
    expect(await sideways(page), view).toBeLessThanOrEqual(0);
    expect(await broken(page), view).toEqual([]);
  }
  expect([...await lowContrast(page, '#main'), ...await unnamed(page, '#main')]).toEqual([]);
  // the game's own page: the same cover, whole, in the wide frame
  await page.locator('#lib-view').click();
  await page.locator('#view-choices [data-v="medium"]').click();
  await page.keyboard.press('Escape');
  const card = await openGame(page, 'arcade-gauntlet2');
  const wide = card.locator('.avrana-cover.wide');
  await expect(wide.locator('img')).toHaveAttribute('src', 'covers/arcade-gauntlet2.png');
  expect(await wide.locator('img').evaluate((el) => getComputedStyle(el).objectFit)).toBe('contain');
  await expect(card.locator('#game-title')).toHaveText('Gauntlet II');
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  expect(await broken(page)).toEqual([]);
});

test('a cover that will not load, or is not a picture, gives way to the art the game had: never a broken image', async ({ page }) => {
  await withCovers(page);
  await page.route('**/party/covers/arcade-gauntlet2.png', (route) => route.abort());                                   // out of reach
  await page.route('**/party/covers/ps1-worms.png', (route) => route.fulfill({ body: 'not a picture', contentType: 'image/png' }));
  await open(page);
  await place(page, 'library');
  const gauntlet = cover(page, '#games', 'arcade-gauntlet2'), worms = cover(page, '#games', 'ps1-worms');
  await expect(gauntlet.locator('img')).toHaveAttribute('src', 'art/kenney-sword.svg');     // what it had before
  await expect(gauntlet).toHaveClass(/icon-art/);
  await expect(gauntlet).not.toHaveClass(/own-art/);
  await expect(worms.locator('img')).toHaveCount(0);                                         // its kind icon
  await expect(worms.locator('svg').first()).toBeVisible();
  expect(await broken(page)).toEqual([]);
  // and it is not asked for again wherever the game is drawn next
  let asked = 0;
  page.on('request', (request) => { if (request.url().endsWith('/covers/arcade-gauntlet2.png')) asked += 1; });
  const card = await openGame(page, 'arcade-gauntlet2');
  await expect(card.locator('.avrana-cover.wide img')).toHaveAttribute('src', 'art/kenney-sword.svg');
  await place(page, 'home');
  await expect(cover(page, '#view-home', 'arcade-gauntlet2').locator('img')).toHaveAttribute('src', 'art/kenney-sword.svg');
  expect(asked).toBe(0);
  expect(await broken(page)).toEqual([]);
});

test('with no covers, or an index that cannot be read, the shell is as it was', async ({ browser, request }) => {
  // the dev server under test controls serves an empty index: nothing a developer keeps is shown
  expect(await (await request.get('/party/covers/index.json')).json()).toEqual({ schema: 'avrana.covers/v0', covers: {} });
  for (const answer of ['empty', 'missing', 'corrupt'] as const) {
    // a phone of its own each time: once a page has a service worker, the worker asks for the
    // index itself, and an answer given to the page would never be used
    const context = await browser.newContext();
    const page = await context.newPage();
    let answered = 0, asked = 0;
    if (answer === 'missing') await page.route('**/party/covers/index.json', (route) => { answered += 1; return route.fulfill({ status: 404, body: 'not found' }); });
    if (answer === 'corrupt') await page.route('**/party/covers/index.json', (route) => { answered += 1; return route.fulfill({ body: '{nope', contentType: 'application/json' }); });
    page.on('request', (req) => { if (/\/covers\/.*\.(png|jpg|jpeg|webp|avif)$/.test(req.url())) asked += 1; });
    await open(page);
    if (answer !== 'empty') expect(answered, `${answer}: the page was given this answer`).toBeGreaterThan(0);
    await place(page, 'library');
    await expect(cover(page, '#games', 'arcade-gauntlet2').locator('img'), answer).toHaveAttribute('src', 'art/kenney-sword.svg');
    await expect(cover(page, '#games', 'ps1-worms').locator('img'), answer).toHaveCount(0);
    await expect(page.locator('#games .own-art'), answer).toHaveCount(0);
    await expect(page.locator('#catalog-error'), answer).toBeHidden();      // covers are never a reason to complain
    expect(asked, answer).toBe(0);                                          // no picture is guessed at
    await context.close();
  }
});
