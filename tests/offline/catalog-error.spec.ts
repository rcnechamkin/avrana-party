import { test, expect, type Page } from '@playwright/test';

/**
 * AVR-220: a missing, corrupt or wrong-shaped catalog.json must not take Party Home down.
 * The three failures the audit reproduced in Chromium, each against the simulated Party (Tier 2):
 * the page finishes booting, says the game list is unavailable, offers a Retry that works, and
 * throws nothing. The module-level cases are in tests/offline/catalog-load.test.mjs.
 */
const BROKEN: Record<string, { status: number; body: string }> = {
  'a missing file (404)': { status: 404, body: 'not found' },
  'truncated JSON': { status: 200, body: '{"schema":"avrana.catalog/v0","games":[{"id":"bl' },
  'valid JSON without games': { status: 200, body: '{"schema":"avrana.catalog/v0"}' },
};

async function breakCatalog(page: Page, reply: { status: number; body: string }) {
  await page.route('**/party/catalog.json', (route) => route.fulfill({
    status: reply.status, contentType: 'application/json', body: reply.body }));
}

for (const [name, reply] of Object.entries(BROKEN)) {
  test(`Party Home survives ${name} and Retry recovers`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await breakCatalog(page, reply);

    await page.goto('/party/');
    await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
    await expect(page.locator('#status')).not.toContainText('Checking the connection');
    const notice = page.locator('#catalog-error');
    await expect(notice).toBeVisible();
    await expect(notice).toContainText('Game list unavailable');
    await expect(page.locator('[data-id]')).toHaveCount(0);            // no game cards, no crash
    await expect(page.locator('#away')).toBeHidden();                  // the party itself is reachable

    await page.unroute('**/party/catalog.json');                       // the file is back
    await page.locator('#catalog-retry').click();
    await expect(notice).toBeHidden();
    await expect(page.locator('[data-id="arcade-gauntlet2"]')).toContainText('Gauntlet II');
    expect(errors).toEqual([]);
  });
}
