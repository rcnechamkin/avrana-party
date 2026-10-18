import { test, expect, type Page } from '@playwright/test';
import { place, sideways } from '../lib/frame';

/**
 * AVR-429: Home and Library read as one interface. What is chosen looks the same wherever it is
 * chosen, every sheet is the same sheet, and the Library keeps its shape while it loads.
 */
async function open(page: Page) {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
}
const tint = (page: Page) => page.evaluate(() => {
  const probe = document.createElement('i');
  probe.style.background = 'var(--color-select)';
  document.body.append(probe);
  const value = getComputedStyle(probe).backgroundColor;
  probe.remove();
  return value;
});

test('what is chosen is tinted the same way in the bar, the tabs, a segment and a list', async ({ page }) => {
  await open(page);
  await place(page, 'library');
  const select = await tint(page);
  const ground = (selector: string, pseudo?: string) => page.locator(selector).first()
    .evaluate((el, p) => getComputedStyle(el, p || undefined).backgroundColor, pseudo);
  expect(await ground('#nav a[aria-current="page"]', '::before')).toBe(select);
  expect(await ground('#game-views [aria-pressed="true"]')).toBe(select);
  await page.locator('#lib-filter').click();
  expect(await ground('#filter-players [aria-pressed="true"]')).toBe(select);
  await page.keyboard.press('Escape');
  await page.locator('#lib-view').click();
  expect(await ground('#view-choices [aria-pressed="true"]')).toBe(select);
  await page.keyboard.press('Escape');
  // and never by colour alone: the chosen word is heavier too
  const weight = (selector: string) => page.locator(selector).first().evaluate((el) => Number(getComputedStyle(el).fontWeight));
  expect(await weight('#nav a[aria-current="page"]')).toBeGreaterThan(await weight('#nav a:not([aria-current])'));
  expect(await weight('#game-views [aria-pressed="true"]')).toBeGreaterThan(await weight('#game-views [aria-pressed="false"]'));
});

test('every sheet is the same sheet, How to play included', async ({ page }) => {
  await open(page);
  for (const id of ['rules', 'lib-filters', 'lib-views', 'about-limited']) {
    const sheet = page.locator(`#${id}`);
    await expect(sheet).toHaveClass(/\bavrana-sheet\b/);
    await expect(sheet.locator('> .head h2')).toHaveCount(1);
    await expect(sheet.locator('> .head button[aria-label="Close"]')).toHaveCount(1);
  }
  const look = (id: string) => page.locator(`#${id}`).evaluate((el) => { const cs = getComputedStyle(el); return [cs.backgroundColor, cs.borderTopLeftRadius, cs.borderTopColor].join('|'); });
  expect(await look('rules')).toBe(await look('lib-filters'));
});

test('the Library keeps the shape of a shelf while the list of games is on its way', async ({ page }) => {
  let release = () => {};
  await page.route('**/party/catalog.json', (route) => new Promise<void>((done) => { release = () => { route.continue(); done(); }; }));
  await page.goto('/party/#library', { waitUntil: 'domcontentloaded' });
  const waiting = page.locator('#games .avrana-loading');
  await expect(waiting).toBeVisible();
  await expect(page.locator('#games')).toHaveAttribute('aria-busy', 'true');
  expect(await waiting.locator('.avrana-grid .skeleton').first().evaluate((el) => { const r = el.getBoundingClientRect(); return Math.abs(r.width - r.height) < 1; })).toBe(true);
  expect(await sideways(page)).toBe(0);
  release();
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(waiting).toHaveCount(0);
  await expect(page.locator('#games')).toHaveAttribute('aria-busy', 'false');
});

test('on a wide screen the four places sit under the page column, and a sheet is a panel in the middle', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page);
  await place(page, 'library');
  const column = (await page.locator('#content > .wrap').boundingBox())!;
  const first = (await page.locator('#nav a').first().boundingBox())!;
  const last = (await page.locator('#nav a').last().boundingBox())!;
  expect(first.x).toBeGreaterThanOrEqual(column.x - 1);
  expect(last.x + last.width).toBeLessThanOrEqual(column.x + column.width + 1);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.locator('#lib-view').click();
  const sheet = (await page.locator('#lib-views').boundingBox())!;
  expect(Math.abs((sheet.y + sheet.height / 2) - 400)).toBeLessThan(2);
  expect(sheet.y + sheet.height).toBeLessThan(800);
});
