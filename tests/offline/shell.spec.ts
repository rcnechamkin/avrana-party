import { test, expect, type Page } from '@playwright/test';
import { place } from '../lib/frame';

/**
 * The Concept K shell (AVR-707): one floating glass bar of four places with a lens that slides to
 * the place on screen, a glass utility at the top right, the Spire-A Home button at the top left,
 * and nothing else made of glass. The page scrolls under them, and its last row ends clear of the
 * bar (owner review, 2026-10-21: "the bottom row is never fully visible").
 */
async function open(page: Page) {
  await page.request.post('/__test__/arcade/up');
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
}

/** At the end of a scroll: the last thing drawn in the place (its innermost boxes: words, art,
 * controls; not the padding a rail keeps for its focus rings), against the bar's top edge. */
async function endGap(page: Page) {
  return page.evaluate(async () => {
    const content = document.getElementById('content')!;
    content.scrollTo(0, 1e6);
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const view = [...content.querySelectorAll('[data-page]')].find((el) => !(el as HTMLElement).hidden)!;
    let last = 0;
    for (const el of view.querySelectorAll('*')) {
      if (el.childElementCount && !(el instanceof HTMLButtonElement || el instanceof HTMLAnchorElement)) continue;
      const box = el.getBoundingClientRect();
      if (box.height && box.width && getComputedStyle(el).visibility !== 'hidden') last = Math.max(last, box.bottom);
    }
    return document.getElementById('nav')!.getBoundingClientRect().top - last;
  });
}

for (const [w, h] of [[390, 844], [390, 664], [320, 568]]) {
  test(`at ${w}x${h} the last row of every place ends 16 px or more above the bar`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await open(page);
    for (const name of ['home', 'party', 'library', 'me'] as const) {
      await place(page, name);
      expect(await endGap(page), name).toBeGreaterThanOrEqual(15.5);
    }
  });
}

test('glass is on the three shell controls only, and each clips to its own shape', async ({ page }) => {
  await open(page);
  const glass = await page.evaluate(() => [...document.querySelectorAll('*')]
    .filter((el) => /blur/.test(getComputedStyle(el).backdropFilter || getComputedStyle(el).getPropertyValue('-webkit-backdrop-filter')))
    .filter((el) => el.getClientRects().length)
    .map((el) => ({ id: el.id || el.className.toString(), overflow: getComputedStyle(el).overflow, radius: getComputedStyle(el).borderTopLeftRadius })));
  expect(glass.map((g) => g.id).sort()).toEqual(['nav', 'top-home', 'utility']);
  for (const g of glass) {
    expect(g.overflow, g.id).toBe('hidden');
    expect(parseFloat(g.radius), g.id).toBeGreaterThan(16);
  }
});

test('the lens sits under the place on screen, and the bar says it in words too', async ({ page }) => {
  await open(page);
  for (const name of ['party', 'library', 'me', 'home'] as const) {
    await place(page, name);
    const tab = page.locator(`#nav a[data-go="${name}"]`);
    await expect(tab).toHaveAttribute('aria-current', 'page');
    // the lens travels on a spring: wait for it to settle under the tab
    await expect.poll(async () => {
      const [lens, at] = await Promise.all([page.locator('#nav .avrana-lens').boundingBox(), tab.boundingBox()]);
      return Math.abs((lens!.x + lens!.width / 2) - (at!.x + at!.width / 2));
    }, { message: name }).toBeLessThan(2);
    expect(await tab.evaluate((el) => getComputedStyle(el).fontWeight)).toBe('600');
  }
});

test('Me is drawn with this phone’s own avatar, and #system still lands on Me', async ({ page }) => {
  await open(page);
  await expect(page.locator('#nav-me .avrana-icon')).toBeVisible();          // no profile yet: a plain figure
  await page.evaluate(() => { localStorage.setItem('wc-name', 'Sam'); localStorage.setItem('wc-avatar', 'gaze-07'); });
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('#nav-me img.avrana-avatar')).toHaveAttribute('src', /gaze-07/);
  await page.goto('/party/#system');
  await expect(page.locator('html')).toHaveAttribute('data-place', 'me');
  await expect(page.locator('#top-title')).toHaveText('Me');
  await expect(page.locator('#player-chip')).toContainText('Sam');
});

test('the utility: Search on every other place, Filters and View on the Library, whose own search field is there', async ({ page }) => {
  await open(page);
  await expect(page.locator('#top-home')).toBeVisible();
  await expect(page.locator('#lib-filter')).toBeHidden();
  await page.locator('#util-search').click();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'library');
  await expect(page.locator('#game-search')).toBeFocused();
  await expect(page.locator('#lib-filter')).toBeVisible();
  await expect(page.locator('#lib-view')).toBeVisible();
  await expect(page.locator('#util-search')).toBeHidden();                 // not twice on one screen
  await expect(page.locator('#top-home')).toBeHidden();
  await place(page, 'party');
  await expect(page.locator('#lib-filter')).toBeHidden();
  await expect(page.locator('#util-search')).toBeVisible();
  await place(page, 'home');
  await expect(page.locator('#top-home')).toHaveAttribute('href', '#home');
  await expect(page.locator('#top-home')).toHaveAccessibleName('Home');
});
