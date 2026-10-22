import { test, expect, type Page } from '@playwright/test';

/**
 * Tier-3 motion (Concept K, AVR-711): the briefing's entrance, the frame's return and Home's turn
 * to "Just played" run at 200 ms (--motion-3). AVR-704's 600 ms is a proposal: only with
 * ?concept=motion, and said on screen while it is on (the owner, 2026-10-21). Nothing moves under
 * Reduce Motion. Computed styles, so it holds whether or not a Party is here.
 */
async function open(page: Page, search = '') {
  await page.addInitScript(() => localStorage.setItem('wc-name', 'Robin'));
  await page.goto('/party/' + search);
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
}

/** What the entrances would run as, with each marked as entering. */
const entrances = (page: Page) => page.evaluate(() => {
  for (const id of ['scene', 'content', 'home-lead']) document.getElementById(id)!.setAttribute('data-enter', '');
  const of = (el: Element | null) => (el ? getComputedStyle(el) : null);
  const brief = of(document.getElementById('scene')), content = of(document.getElementById('content'));
  return { brief: [brief!.animationName, brief!.animationDuration], content: [content!.animationName, content!.animationDuration],
    // (the token as milliseconds: the stylesheet is minified, so 200ms may read ".2s")
    tier3: `${Math.round(parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--motion-3')) * (/ms$/.test(getComputedStyle(document.documentElement).getPropertyValue('--motion-3').trim()) ? 1 : 1000))}ms` };
});

test('tier 3 is 200 ms by default, and no proposal is on', async ({ page }) => {
  await open(page);
  expect(await entrances(page)).toEqual({ brief: ['avrana-rise', '0.2s'], content: ['avrana-fade', '0.2s'], tier3: '200ms' });
  await expect(page.locator('#concept-badge')).toBeHidden();
  await expect(page.locator('html')).not.toHaveAttribute('data-concept', /motion/);
});

test('?concept=motion runs tier 3 at AVR-704’s 600 ms, and says "Proposal" while it does', async ({ page }) => {
  await open(page, '?concept=motion');
  expect(await entrances(page)).toEqual({ brief: ['avrana-rise', '0.6s'], content: ['avrana-fade', '0.6s'], tier3: '600ms' });
  await expect(page.locator('#concept-badge')).toBeVisible();
  await expect(page.locator('#concept-badge')).toContainText(/proposal/i);
  // it takes no taps and covers none of the shell's controls
  expect(await page.locator('#concept-badge').evaluate((el) => getComputedStyle(el).pointerEvents)).toBe('none');
  const badge = (await page.locator('#concept-badge').boundingBox())!;
  for (const id of ['#top-home', '#utility']) {
    const box = await page.locator(id).boundingBox();
    if (!box) continue;
    const overlap = badge.x < box.x + box.width && box.x < badge.x + badge.width && badge.y < box.y + box.height && box.y < badge.y + badge.height;
    expect(overlap, id).toBe(false);
  }
});

test('an unknown concept is ignored: nothing is switched on by a typo', async ({ page }) => {
  await open(page, '?concept=motoin');
  expect((await entrances(page)).tier3).toBe('200ms');
  await expect(page.locator('#concept-badge')).toBeHidden();
});

test('under Reduce Motion nothing enters: no animation, proposal or not', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const search of ['', '?concept=motion']) {
    await open(page, search);
    const e = await entrances(page);
    expect(e.brief[0], search).toBe('none');
    expect(e.content[0], search).toBe('none');
  }
});
