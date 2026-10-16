import { test, expect } from '@playwright/test';
import { lookup } from 'node:dns/promises';

/**
 * Reachability + LAN Games hub.
 *
 * Guards the two things everything else depends on: this machine is on the
 * Avrana Party Wi-Fi, and party.avrana resolves to the Pi's AP address
 * (10.42.0.1), not the home-LAN address. If these fail, the rest of the suite
 * is testing the wrong path (or nothing).
 */
test.describe('Reachability & LAN Games hub', () => {
  test('party.avrana serves the LAN Games hub', async ({ page }) => {
    const res = await page.goto('/');
    expect(res?.ok(), 'GET / should be 2xx').toBeTruthy();
    await expect(page).toHaveTitle(/LAN GAMES/i);
    await expect(page.locator('.hub-logo')).toBeVisible();
  });

  test('party.avrana resolves to the AP address 10.42.0.1 (not the home LAN)', async () => {
    // The brief: never client-test against the Pi's home-LAN address
    // (10.0.0.143). The canonical name must resolve to the AP address so tests
    // route over the Avrana Party Wi-Fi. Checked at the OS resolver level.
    const { address } = await lookup('party.avrana');
    expect(address, `party.avrana resolved to ${address}`).toBe('10.42.0.1');
  });
});
