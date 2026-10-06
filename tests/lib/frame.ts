import { expect, type Page } from '@playwright/test';

/** The shell's four places (web/party/lib/frame.js). They are views of one document. */
export type Place = 'home' | 'party' | 'library' | 'system';

/** Go to a place the way a person does: the bar at the bottom of the frame. */
export async function place(page: Page, name: Place) {
  await page.locator(`#nav a[data-go="${name}"]`).click();
  await expect(page.locator('html')).toHaveAttribute('data-place', name);
}

/** The Host's start, from the Library, where the games are. */
export async function startForEveryone(page: Page, id: string) {
  await place(page, 'library');
  await page.locator(`[data-id="${id}"]`).getByRole('button', { name: 'Start for everyone' }).click();
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
