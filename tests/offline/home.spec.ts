import { test, expect, type Page } from '@playwright/test';
import { place } from '../lib/frame';

/**
 * Home's K0 (Concept K, AVR-708) on one phone with no Party: the stage, its Preview, and the rail.
 * A cover opens its facts in place and never selects; one primary action is live at a time; focus
 * goes to the facts and back to what opened them. The Host's Select is a Party matter: see
 * tests/party/home-k0.spec.ts.
 */
async function open(page: Page) {
  await page.addInitScript(() => localStorage.setItem('wc-name', 'Robin'));
  await page.request.post('/__test__/arcade/up');
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('#home-lead [data-game]')).toBeVisible();
}

test('the stage: full bleed under the top row, Featured (never Selected), its words over a fixed ink gradient', async ({ page }) => {
  await open(page);
  const stage = page.locator('#home-lead .avrana-stage');
  await expect(stage.locator('.avrana-eyebrow')).toHaveText('Featured');
  await expect(stage.locator('.avrana-eyebrow')).not.toHaveClass(/selected/);
  await expect(stage.locator('h2')).toHaveText('BLUFF');
  const box = (await stage.boundingBox())!;
  const vw = page.viewportSize()!.width;
  expect(box.x).toBeLessThanOrEqual(0.5);                                       // edge to edge
  expect(box.x + box.width).toBeGreaterThanOrEqual(vw - 0.5);
  expect(box.y).toBeLessThanOrEqual(0.5);                                       // from the top, under the glass controls
  // the gradients are the stage's own and do not depend on the art
  const bottom = await stage.locator('.art').evaluate((el) => getComputedStyle(el, '::after').backgroundImage);
  expect(bottom).toContain('rgba(18, 18, 20, 0.82)');
  expect(await stage.locator('.art').evaluate((el) => getComputedStyle(el, '::before').height)).toBe('150px');
  // no Party: no one to select for; Preview is the one thing to do
  await expect(page.locator('#home-actions button')).toHaveText(['Preview']);
});

test('Preview opens the facts in place: focus on the title, the stage dimmed, and every way out returns focus', async ({ page }) => {
  await open(page);
  const panel = page.locator('#home-preview'), preview = page.locator('#stage-preview');
  for (const close of ['Escape', 'X', 'art'] as const) {
    await preview.click();
    await expect(panel).toBeVisible();
    await expect(page.locator('#preview-title')).toBeFocused();
    await expect(page.locator('#preview-title')).toHaveText('BLUFF');
    await expect(preview).toHaveAttribute('aria-expanded', 'true');
    expect(await page.locator('#home-actions').evaluate((el) => (el as HTMLElement).inert)).toBe(true);
    await expect.poll(() => page.locator('#home-actions').evaluate((el) => getComputedStyle(el).opacity)).toBe('0.3');   // (a 150 ms fade)
    await expect(panel.locator('.avrana-chips li').first()).toBeVisible();
    await expect(panel.getByRole('link', { name: 'More about BLUFF' })).toHaveAttribute('href', '#game/bluff');
    await expect(panel.getByRole('button', { name: 'Select for Party' })).toHaveCount(0);   // no Party here
    if (close === 'Escape') await page.keyboard.press('Escape');
    else if (close === 'X') await panel.getByRole('button', { name: 'Close' }).click();
    else await page.locator('#home-lead .art').click({ position: { x: 40, y: 120 } });    // the same art again
    await expect(panel, close).toBeHidden();
    await expect(preview, close).toBeFocused();
    await expect(preview).toHaveAttribute('aria-expanded', 'false');
    expect(await page.locator('#home-actions').evaluate((el) => (el as HTMLElement).inert), close).toBe(false);
  }
  // the art opens it too, for a pointer (the keyboard has Preview)
  await page.locator('#home-lead .art').click({ position: { x: 40, y: 120 } });
  await expect(panel).toBeVisible();
});

test('a rail cover opens its facts under the rail; it never opens a page or selects', async ({ page }) => {
  await open(page);
  const card = page.locator('#home-great [data-game="expo"]');
  await expect(card).toHaveJSProperty('tagName', 'BUTTON');
  await card.click();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'home');
  const panel = page.locator('#home-preview');
  await expect(panel).toBeVisible();
  await expect(page.locator('#preview-title')).toHaveText('EXPO');
  expect(await panel.evaluate((el) => el.previousElementSibling?.id)).toBe('home-great');
  await expect(card).toHaveAttribute('aria-expanded', 'true');
  // another cover: the facts follow it
  await page.locator('#home-great [data-game="checkers"]').click();
  await expect(page.locator('#preview-title')).toHaveText('Checkers');
  await expect(card).toHaveAttribute('aria-expanded', 'false');
  // the same cover again puts them away, and focus is on it
  await page.locator('#home-great [data-game="checkers"]').click();
  await expect(panel).toBeHidden();
  await expect(page.locator('#home-great [data-game="checkers"]')).toBeFocused();
});

test('2.2 covers to a row on a phone, in portrait', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  const widths = await page.locator('#home-great').evaluate((rail) => {
    const box = rail.getBoundingClientRect(), pad = parseFloat(getComputedStyle(rail).paddingRight);
    const items = [...rail.children].map((li) => li.getBoundingClientRect());
    // how much of the third cover shows at the rail's edge, in covers: the ".2" of 2.2
    return { third: (box.right - pad - items[2].left) / items[2].width, art: rail.querySelector('.avrana-cover')!.getBoundingClientRect() };
  });
  expect(widths.third).toBeGreaterThan(0.1);
  expect(widths.third).toBeLessThan(0.3);
  expect(widths.art.height / widths.art.width).toBeCloseTo(4 / 3, 1);
});

test('a title whose art will not load is its name, set large: never an empty box or an invented picture', async ({ page }) => {
  // no picture loads at all: the owner's covers, a package's, the title's own art
  await page.route(/\/(covers|art|games)\/.*\.(png|jpe?g|webp|avif|svg|json)(\?|$)/, (route) => route.abort());
  await open(page);
  const art = page.locator('#home-lead .art');
  await expect(art.locator('.noart')).toBeVisible();
  await expect(art.locator('.noart')).toHaveText('BLUFF');
  await expect(art.locator('img')).toHaveCount(0);
});

test('under Reduce Motion the preview just appears: no flight', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await open(page);
  await page.evaluate(() => {
    (window as unknown as { flights: number }).flights = 0;
    const real = document.startViewTransition?.bind(document);
    if (real) (document as unknown as { startViewTransition: unknown }).startViewTransition = (cb: () => void) => { (window as unknown as { flights: number }).flights++; return real(cb); };
  });
  await page.locator('#stage-preview').click();
  await expect(page.locator('#home-preview')).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { flights: number }).flights)).toBe(0);
});

test('the presence row is the Party’s: with no Party there is none', async ({ page }) => {
  await open(page);
  await expect(page.locator('#home-presence')).toBeHidden();
  await place(page, 'party');
  await expect(page.locator('#party-off')).toBeVisible();
});

test('the preview belongs to Home: Escape elsewhere is the page’s own, and Home comes back undimmed', async ({ page }) => {
  await open(page);
  await page.locator('#stage-preview').click();
  await expect(page.locator('#preview-title')).toBeFocused();
  await place(page, 'library');
  const search = page.locator('#game-search');
  await search.fill('blu');
  await search.press('Escape');
  await expect(search).toHaveValue('');                                       // the search field's own Escape
  await place(page, 'home');
  await expect(page.locator('#home-preview')).toBeHidden();
  expect(await page.locator('#home-actions').evaluate((el) => (el as HTMLElement).inert)).toBe(false);
  await expect(page.locator('#stage-preview')).toHaveAttribute('aria-expanded', 'false');
});

test('a flight leaves no trace on the covers: no name and no empty style (the next draw keeps them, and focus)', async ({ page }) => {
  await open(page);
  await page.locator('#stage-preview').click();
  await expect(page.locator('#preview-title')).toBeFocused();
  await expect.poll(() => page.evaluate(() => document.querySelectorAll('#view-home [style=""]').length)).toBe(0);
  await expect.poll(() => page.evaluate(() => [...document.querySelectorAll('#content *')]
    .filter((el) => (el as HTMLElement).style.viewTransitionName).length)).toBe(0);
  await page.locator('#home-preview .close').click();
  await expect(page.locator('#stage-preview')).toBeFocused();
  await expect.poll(() => page.evaluate(() => document.querySelectorAll('#view-home [style=""]').length)).toBe(0);
});
