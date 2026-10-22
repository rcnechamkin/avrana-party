import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';
import { openGame, place, sideways, startForEveryone } from '../lib/frame';

/**
 * A package's banner in the shell (AVR-466). The catalog row's appliance-set `images` may name a cover, an icon
 * and a banner under /party/pkgart/, which nginx serves only once that location is deployed (a separate, gated
 * step); here the page's requests for them are answered (or refused) by the test, which is also what a phone sees
 * when the location is absent. Which picture a place draws is lib/cover-art.js (tests/offline/cover-art.test.mjs);
 * this is the real shell drawing it: Home's stage by its measured box, a game's page, a tile, a rail, a row.
 * Chromium at phone sizes: not a real phone.
 */
const FIXTURES = path.resolve(__dirname, '..', 'fixtures', 'covers');
const PICTURE = path.join(FIXTURES, 'ps1-worms.png');
const art = (id: string, name: string) => `/party/pkgart/${id}/${name}.png`;
const images = (id: string, roles: string[]) => Object.fromEntries(roles.map((r) => [r, {
  url: art(id, { cover: '0123456789abcdef', icon: 'fedcba9876543210', banner: 'aaaaaaaaaaaaaaaa' }[r]!),
  ...{ cover: { w: 1024, h: 1024 }, icon: { w: 512, h: 512 }, banner: { w: 1920, h: 1080 } }[r]!,
}]));

type Roles = Record<string, string[]>;

/** The catalog with these package games first (the first that suits one person leads Home), and their pictures
 * served, except the paths in `refuse`. Returns the list of picture paths the page asked for. */
async function withPackages(page: Page, roles: Roles, refuse: string[] = []) {
  const asked: string[] = [];
  await page.route('**/party/catalog.json', async (route) => {
    const body = await (await route.fetch()).json();
    const template = body.games.find((g: { id: string }) => g.id === 'checkers');
    body.games.unshift(...Object.entries(roles).map(([id, rs]) => ({
      ...template, id, name: id.replace('pkg-', 'Pkg '), artwork: undefined, accent: undefined, players: { min: 1, max: 6 },
      installed: true, entry: `/games/${id}/`, tier: 'community', ...(rs.length ? { images: images(id, rs) } : {}),
    })));
    await route.fulfill({ json: body });
  });
  await page.route('**/party/pkgart/**', (route) => {
    const p = new URL(route.request().url()).pathname;
    asked.push(p);
    return refuse.includes(p) ? route.fulfill({ status: 404, body: 'not found' }) : route.fulfill({ path: PICTURE, contentType: 'image/png' });
  });
  return asked;
}

async function open(page: Page, size?: { width: number, height: number }) {
  if (size) await page.setViewportSize(size);
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
}

const PORTRAIT = { width: 390, height: 844 };      // a phone held upright: the stage is taller than it is wide
const WIDE = { width: 900, height: 700 };          // a tablet or a phone on its side: the stage is wider than 4:3
const stage = (page: Page) => page.locator('#home-lead .avrana-stage .avrana-cover.stage');
const broken = (page: Page) => page.evaluate(() => [...document.querySelectorAll('img')]
  .filter((img) => img.getClientRects().length > 0 && img.complete && img.naturalWidth === 0).map((img) => img.getAttribute('src')));

test('Home’s stage draws the cover while its box is narrow and the banner when it is wide, and follows a turn of the phone', async ({ page }) => {
  const asked = await withPackages(page, { 'pkg-all': ['cover', 'icon', 'banner'] });
  await open(page, PORTRAIT);
  await expect(stage(page)).toHaveAttribute('data-art', 'package-cover');
  await expect(stage(page).locator('img')).toHaveAttribute('src', art('pkg-all', '0123456789abcdef'));
  await expect(stage(page).locator('img')).toHaveAttribute('loading', 'eager');           // the first thing on the page: not lazy
  await expect(stage(page).locator('img')).toHaveAttribute('fetchpriority', 'high');
  expect(asked.filter((p) => p.includes('aaaaaaaa')), 'a banner is not asked for while it is not drawn').toEqual([]);
  const box = await page.locator('#home-lead .avrana-stage').boundingBox();
  expect(box!.width / box!.height).toBeLessThan(1.2);

  await page.setViewportSize(WIDE);                                                       // the phone turns: the box is wide
  await expect(stage(page)).toHaveAttribute('data-art', 'package-banner');
  await expect(stage(page)).toHaveClass(/banner-art/);
  await expect(stage(page).locator('img')).toHaveAttribute('src', art('pkg-all', 'aaaaaaaaaaaaaaaa'));
  await expect(stage(page).locator('img')).toHaveAttribute('width', '1920');
  const wide = await page.locator('#home-lead .avrana-stage').boundingBox();
  expect(wide!.width / wide!.height).toBeGreaterThan(1.3);
  // it is fitted to the stage's width, never stretched: the picture's own 16:9 at the stage's width, from the top
  const img = await stage(page).locator('img').boundingBox();
  expect(Math.abs(img!.width / img!.height - 16 / 9)).toBeLessThan(0.02);
  expect(img!.width).toBeGreaterThanOrEqual(wide!.width - 1);
  expect(await sideways(page)).toBeLessThanOrEqual(0);

  await page.setViewportSize(PORTRAIT);                                                   // and back
  await expect(stage(page)).toHaveAttribute('data-art', 'package-cover');
  expect(await broken(page)).toEqual([]);
});

test('the narrow stage keeps the banner for a game that has only a banner, drawn whole; a tile and a row never use it', async ({ page }) => {
  await withPackages(page, { 'pkg-ban': ['banner'] });
  await open(page, PORTRAIT);
  await expect(stage(page)).toHaveAttribute('data-art', 'package-banner');
  await expect(stage(page)).toHaveClass(/own-art/);
  await expect(stage(page)).not.toHaveClass(/banner-art/);
  expect(await stage(page).locator('img').evaluate((el) => getComputedStyle(el).objectFit)).toBe('contain');   // whole, not cropped
  await place(page, 'library');
  const tile = page.locator('#games [data-game="pkg-ban"] .avrana-cover').first();
  await expect(tile.locator('img')).toHaveCount(0);                                       // its kind icon: a 16:9 picture is not cut to a square
  await expect(tile.locator('svg').first()).toBeVisible();
  await page.setViewportSize(WIDE);
  await place(page, 'home');
  await expect(stage(page)).toHaveAttribute('data-art', 'package-banner');
  await expect(stage(page)).toHaveClass(/banner-art/);
  expect(await broken(page)).toEqual([]);
});

test('a game’s page draws the banner in its 16:9 frame, and the cover when there is none', async ({ page }) => {
  await withPackages(page, { 'pkg-all': ['cover', 'icon', 'banner'], 'pkg-cov': ['cover', 'icon'] });
  await open(page, PORTRAIT);
  await place(page, 'library');
  let card = await openGame(page, 'pkg-all');
  let wide = card.locator('.avrana-cover.wide');
  await expect(wide).toHaveAttribute('data-art', 'package-banner');
  await expect(wide.locator('img')).toHaveAttribute('src', art('pkg-all', 'aaaaaaaaaaaaaaaa'));
  expect(await wide.locator('img').evaluate((el) => getComputedStyle(el).objectFit)).toBe('cover');
  const frame = await wide.boundingBox();
  expect(Math.abs(frame!.width / frame!.height - 16 / 9)).toBeLessThan(0.02);              // the frame is the picture's own shape: nothing is cut
  await expect(card.locator('#game-title')).toHaveText('Pkg all');
  card = await openGame(page, 'pkg-cov');
  wide = card.locator('.avrana-cover.wide');
  await expect(wide).toHaveAttribute('data-art', 'package-cover');
  expect(await wide.locator('img').evaluate((el) => getComputedStyle(el).objectFit)).toBe('contain');   // the square cover, whole, as before
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  expect(await broken(page)).toEqual([]);
});

test('the Library tile draws the cover, a list row the icon, Home’s rail the cover: a banner changes none of them', async ({ page }) => {
  await withPackages(page, { 'pkg-lead': [], 'pkg-all': ['cover', 'icon', 'banner'] });
  await open(page, PORTRAIT);
  const rail = page.locator('#home-games [data-game="pkg-all"] .avrana-cover').first();
  await rail.scrollIntoViewIfNeeded();
  await expect(rail).toHaveAttribute('data-art', 'package-cover');                         // Home's rail: 3:4, the cover
  await place(page, 'library');
  for (const view of ['medium', 'large', 'compact', 'list']) {
    await page.locator('#lib-view').click();
    await page.locator(`#view-choices [data-v="${view}"]`).click();
    await page.keyboard.press('Escape');
    const cover = page.locator('#games [data-game="pkg-all"] .avrana-cover').first();
    await cover.scrollIntoViewIfNeeded();
    await expect(cover, view).toHaveAttribute('data-art', view === 'list' ? 'package-icon' : 'package-cover');
    await expect(page.locator('#games img[src*="aaaaaaaa"]'), `${view}: the banner is not drawn`).toHaveCount(0);
  }
  expect(await broken(page)).toEqual([]);
});

test('a banner that will not load gives way to the cover, then the icon, and is not asked for again', async ({ page }) => {
  const asked = await withPackages(page, { 'pkg-all': ['cover', 'icon', 'banner'] }, [art('pkg-all', 'aaaaaaaaaaaaaaaa')]);
  await open(page, WIDE);
  await expect(stage(page)).toHaveAttribute('data-art', 'package-cover');                  // the banner 404ed: the next rung
  await expect(stage(page).locator('img')).toHaveAttribute('src', art('pkg-all', '0123456789abcdef'));
  await expect.poll(() => stage(page).locator('img').evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);
  expect(await broken(page)).toEqual([]);
  await place(page, 'library');
  const card = await openGame(page, 'pkg-all');                                           // wherever it is drawn next
  await expect(card.locator('.avrana-cover.wide')).toHaveAttribute('data-art', 'package-cover');
  await place(page, 'home');
  await expect(stage(page)).toHaveAttribute('data-art', 'package-cover');
  expect(asked.filter((p) => p.includes('aaaaaaaa')).length, 'remembered once it failed (a first, eager draw may overlap one request)').toBeLessThanOrEqual(2);
  expect(await broken(page)).toEqual([]);

  // every picture refused: the kind icon and the visible name, and no broken image
  const ctx = await page.context().browser()!.newContext({ viewport: WIDE, serviceWorkers: 'block' });
  const bare = await ctx.newPage();
  await withPackages(bare, { 'pkg-all': ['cover', 'icon', 'banner'] }, Object.values(images('pkg-all', ['cover', 'icon', 'banner'])).map((i: any) => i.url));
  await open(bare);
  await expect(stage(bare)).toHaveAttribute('data-art', 'icon');
  await expect(stage(bare).locator('img')).toHaveCount(0);
  await expect(bare.locator('#stage-title')).toHaveText('Pkg all');
  expect(await broken(bare)).toEqual([]);
  await ctx.close();
});

test('a game with no banner, a cover only, or no artwork draws what it has in a wide stage', async ({ page }) => {
  await withPackages(page, { 'pkg-cov': ['cover', 'icon'] });
  await open(page, WIDE);
  await expect(stage(page)).toHaveAttribute('data-art', 'package-cover');
  await expect(stage(page)).toHaveClass(/own-art/);                                        // the whole cover, as it always was
  const ctx = await page.context().browser()!.newContext({ viewport: WIDE, serviceWorkers: 'block' });
  const bare = await ctx.newPage();
  await withPackages(bare, { 'pkg-none': [] });
  await open(bare);
  await expect(stage(bare)).toHaveAttribute('data-art', 'icon');
  await expect(bare.locator('#stage-title')).toHaveText('Pkg none');
  expect(await broken(bare)).toEqual([]);
  await ctx.close();
});

test('the owner’s cover still leads in a wide stage and on the game’s page; the banner is not shadowed for games without one', async ({ page }) => {
  await page.route('**/party/covers/index.json', (route) => route.fulfill({ json: { schema: 'avrana.covers/v0', covers: { 'pkg-own': 'covers/pkg-own.png' } } }));
  await page.route('**/party/covers/pkg-own.png', (route) => route.fulfill({ path: PICTURE, contentType: 'image/png' }));
  await withPackages(page, { 'pkg-own': ['cover', 'icon', 'banner'], 'pkg-all': ['cover', 'icon', 'banner'] });
  await open(page, WIDE);
  await expect(stage(page)).toHaveAttribute('data-art', 'own');
  await expect(stage(page).locator('img')).toHaveAttribute('src', 'covers/pkg-own.png');
  await place(page, 'library');
  expect(await (await openGame(page, 'pkg-own')).locator('.avrana-cover.wide').getAttribute('data-art')).toBe('own');
  expect(await (await openGame(page, 'pkg-all')).locator('.avrana-cover.wide').getAttribute('data-art')).toBe('package-banner');
});

test('200% text and reduced motion: the stage keeps one valid picture, nothing overflows, nothing animates the art', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await withPackages(page, { 'pkg-all': ['cover', 'icon', 'banner'] });
  await open(page, WIDE);
  await page.evaluate(() => document.documentElement.style.setProperty('font-size', '200%'));
  await expect.poll(() => stage(page).getAttribute('data-art')).toMatch(/^package-(banner|cover)$/);
  const art1 = await stage(page).getAttribute('data-art');
  await page.waitForTimeout(400);
  expect(await stage(page).getAttribute('data-art'), 'settled: it does not flip back and forth').toBe(art1);
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  expect(await broken(page)).toEqual([]);
  expect(await page.evaluate(() => document.querySelector('.avrana-stage .avrana-cover')!.getAnimations({ subtree: true }).length)).toBe(0);
  // the live title is still text on the stage, in front of the picture, whatever the picture says
  await expect(page.locator('#stage-title')).toBeVisible();
  await expect(page.locator('#home-lead .avrana-stage')).toHaveAttribute('aria-labelledby', 'stage-title');
});

test('the briefing’s compact stage follows its own box too: the banner on a phone held upright, where it is 4:3 or wider', async ({ page, context }) => {
  // a real Party Core behind the dev server (the second one): the Host selects a game and the briefing opens
  const FULL = `http://127.0.0.1:${Number(process.env.AVRANA_DEV_PORT || 8181) + 1}`;
  expect((await page.request.post(`${FULL}/__test__/party/reset`)).status()).toBe(204);
  await context.addInitScript(() => { try { localStorage.setItem('wc-name', 'Lena'); } catch { /* no storage */ } });
  await page.route('**/party/catalog.json', async (route) => {
    const body = await (await route.fetch()).json();
    const row = body.games.find((g: { id: string }) => g.id === 'bluff');
    row.images = images('bluff', ['cover', 'icon', 'banner']);
    await route.fulfill({ json: body });
  });
  await page.route('**/party/pkgart/**', (route) => route.fulfill({ path: PICTURE, contentType: 'image/png' }));
  await page.setViewportSize(PORTRAIT);
  await page.goto(`${FULL}/party/`);
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await startForEveryone(page, 'bluff');
  await expect(page.locator('#scene')).toBeVisible();
  const cover = page.locator('#scene-cover .avrana-cover.stage');
  const box = await page.locator('#scene-stage').boundingBox();
  expect(box!.width / box!.height, 'the compact stage on an upright phone is wider than 4:3').toBeGreaterThan(1.3);
  await expect(cover).toHaveAttribute('data-art', 'package-banner');
  // a turn of the phone redraws it from its own box (the briefing's stage is the one observed, not Home's)
  await page.setViewportSize(WIDE);
  await expect(cover).toHaveAttribute('data-art', 'package-banner');
  await page.setViewportSize(PORTRAIT);
  await expect(cover).toHaveAttribute('data-art', 'package-banner');
  expect(await broken(page)).toEqual([]);
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await page.screenshot({ path: test.info().outputPath('briefing.png') });
  await test.info().attach('briefing-stage', { body: `stage ${Math.round(box!.width)} x ${Math.round(box!.height)} (${(box!.width / box!.height).toFixed(2)}): ${await cover.getAttribute('data-art')}` });
});
