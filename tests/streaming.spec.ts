import { test, expect, type Page } from '@playwright/test';

/**
 * Arcade streaming + control path (Chromium only).
 *
 * This exercises the real WebRTC connect flow against the live Pi: press Play ->
 * server assigns a player slot over the signalling WebSocket -> WebRTC
 * negotiates -> controls unlock -> input round-trips.
 *
 * Chromium only: Playwright's WebKit has no reliable WebRTC media path, so
 * iPhone-Safari streaming must be verified on a real device (the brief). The
 * appliance also has MAX_PLAYERS=2, so these run serially and ALWAYS disconnect
 * to hand the slot back to the next test or a real phone.
 */
test.describe.configure({ mode: 'serial' });

test.describe('Arcade streaming (Chromium / WebRTC)', () => {
  test.skip(
    ({ browserName }) => browserName !== 'chromium',
    'WebRTC media is validated on Chromium; a real iPhone is authoritative for iOS Safari.',
  );

  async function connect(page: Page) {
    await page.goto('/arcade/');
    await expect(page.locator('#connect')).toBeVisible();
    await page.locator('#connect').click();
    // 1) Signalling assigned a player slot.
    await expect(page.locator('#status')).toContainText(/Player\s*\d/i, { timeout: 30_000 });
    // 2) Controls unlock only once pc.connectionState === 'connected'.
    await expect(page.locator('#leave')).toBeEnabled({ timeout: 30_000 });
    await expect(page.locator('[data-key="coin"]')).toBeEnabled();
  }

  async function disconnect(page: Page) {
    await page.locator('#leave').click();
    await expect(page.locator('#start-overlay')).toBeVisible();
    await expect(page.locator('#connect')).toBeEnabled();
  }

  test('connects, gets a slot, unlocks controls, streams video and accepts input', async ({ page }) => {
    test.setTimeout(90_000);
    const consoleErrors: string[] = [];
    page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()));

    await connect(page);

    // Best-effort proof of *decoded* video: the overlay hides on the <video>
    // 'playing' event. Soft so a missing H.264 decoder in the bundled Chromium
    // doesn't mask a genuine signalling/connection regression.
    await expect
      .soft(page.locator('#start-overlay'), 'overlay should hide once frames decode')
      .toBeHidden({ timeout: 20_000 });

    // Input path: pressing "Add coin" changes the held-button snapshot, which the
    // server acks; the UI records ackRtt. Proves the control WebSocket round-trips.
    await page.locator('[data-key="coin"]').click();
    await expect
      .soft(async () => {
        const txt = (await page.locator('#metrics').textContent()) ?? '{}';
        let acks = 0;
        try { acks = JSON.parse(txt)?.ackRtt?.n ?? 0; } catch { /* mid-update */ }
        expect(acks).toBeGreaterThan(0);
      })
      .toPass({ timeout: 8_000 });

    // Report what actually happened for the run log.
    const metrics = await page.locator('#metrics').textContent();
    console.log('[streaming] metrics=%s consoleErrors=%o', metrics, consoleErrors);

    await disconnect(page);
  });

  test('reconnects and re-acquires a player slot after disconnect', async ({ page }) => {
    test.setTimeout(90_000);
    await connect(page);
    await disconnect(page);
    await connect(page); // slot must be released and re-grantable
    await disconnect(page);
  });
});
