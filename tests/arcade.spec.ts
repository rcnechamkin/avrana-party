import { test, expect } from '@playwright/test';

/**
 * Arcade UI structure at /arcade/ (runs on both chromium and iphone-safari).
 *
 * Pure DOM/layout regression — no WebRTC. This is the "arcade launch" step of
 * the player flow: the page loads with a Play overlay, the controls exist but
 * are locked until a connection is established, and the escape hatch back to the
 * hub is present.
 */
test.describe('Arcade UI (/arcade/)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/arcade/');
  });

  test('loads with the Play overlay, title and ready status', async ({ page }) => {
    await expect(page).toHaveTitle(/Gauntlet II/);
    const connect = page.locator('#connect');
    await expect(connect).toBeVisible();
    await expect(connect).toHaveText(/Play Gauntlet II/);
    await expect(page.locator('#start-overlay')).toBeVisible();
    await expect(page.locator('#status')).toContainText(/Ready to play/i);
  });

  test('has the video surface and an "Other games" link back to the hub', async ({ page }) => {
    await expect(page.locator('video#screen')).toHaveCount(1);
    const other = page.getByRole('link', { name: 'Other games' });
    await expect(other).toHaveAttribute('href', '/');
  });

  test('all controls are disabled until a connection is established', async ({ page }) => {
    const keys = page.locator('[data-key]');
    await expect(keys).toHaveCount(8); // up/down/left/right + fire/magic/coin/start
    const count = await keys.count();
    for (let i = 0; i < count; i++) {
      await expect(keys.nth(i)).toBeDisabled();
    }
    await expect(page.locator('#leave')).toBeDisabled();
    await expect(page.locator('#sound')).toBeDisabled();
  });
});
