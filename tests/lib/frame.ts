import { expect, type Page } from '@playwright/test';

/** The shell's four places (web/party/lib/frame.js). They are views of one document. */
export type Place = 'home' | 'party' | 'library' | 'system';

/** Go to a place the way a person does: the bar at the bottom of the frame. It does not close a
 * sheet for the test: a sheet that should have closed by itself, and did not, fails here. */
export async function place(page: Page, name: Place) {
  await page.locator(`#nav a[data-go="${name}"]`).click();
  await expect(page.locator('html')).toHaveAttribute('data-place', name);
}

/** Open a game's page from its cover in the Library (be there first, or on another game's page).
 * Returns the page's article: its facts and its own button. */
export async function openGame(page: Page, id: string) {
  if (await page.locator('dialog[open]').count()) await page.keyboard.press('Escape');
  if ((await page.locator('html').getAttribute('data-place')) === 'game') await place(page, 'library');
  await page.locator(`#games [data-game="${id}"]`).click();
  const card = page.locator(`#game-detail[data-id="${id}"]`);
  await expect(card).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'game');
  return card;
}

/** The Host's start: the Library, the game's cover, its own button. */
export async function startForEveryone(page: Page, id: string) {
  await place(page, 'library');
  await (await openGame(page, id)).getByRole('button', { name: 'Start for everyone' }).click();
}

/** Controls a thumb would miss: visible and less than 44 px tall or wide. */
export async function smallTargets(page: Page, selector: string) {
  return page.$$eval(selector, (els) => els
    .filter((el) => {
      const box = el.getBoundingClientRect();
      return el.getClientRects().length > 0 && box.width > 0 && (box.height < 44 || box.width < 44);
    })
    .map((el) => `${el.id || el.tagName.toLowerCase()}: ${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 30)}`));
}

/** Sideways overflow of the document or of the frame's scrolling middle, in px (0 when none). */
export async function sideways(page: Page) {
  return page.evaluate(() => {
    const content = document.getElementById('content');
    return Math.max(document.documentElement.scrollWidth - window.innerWidth,
      content ? content.scrollWidth - content.clientWidth : 0);
  });
}
