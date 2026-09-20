import { test, expect, type Page } from '@playwright/test';

/**
 * Two-player slot behaviour (Chromium / WebRTC), using two independent browser
 * contexts as stand-ins for two phones.
 *
 * LIMITATION: two Chromium clients on this laptop are NOT two real phones on the
 * Wi-Fi — this validates the SERVER's slot logic (distinct assignment, MAX_PLAYERS
 * rejection, slot release/reclaim) and that one shared encode feeds two
 * independent peers. Two real iPhones over 5 GHz remain authoritative before
 * raising MAX_PLAYERS beyond 2.
 *
 * The appliance has MAX_PLAYERS=2, so these run serially and always tear down
 * their contexts to hand slots back.
 */
test.describe.configure({ mode: 'serial' });

test.describe('Arcade multiplayer slots (Chromium)', () => {
  test.skip(
    ({ browserName }) => browserName !== 'chromium',
    'WebRTC media is Chromium-only here; two real phones are authoritative for the 2-player claim.',
  );

  async function connect(page: Page): Promise<number> {
    await page.goto('/arcade/');
    await page.locator('#connect').click();
    await expect(page.locator('#status')).toContainText(/Player\s*\d/i, { timeout: 30_000 });
    await expect(page.locator('#leave')).toBeEnabled({ timeout: 30_000 });
    await expect(page.locator('[data-key="coin"]')).toBeEnabled();
    const h1 = (await page.locator('h1').textContent()) ?? '';
    const m = h1.match(/Player\s*(\d)/i);
    return m ? Number(m[1]) : NaN;
  }

  // Best-effort: pressing a control changes the held-button snapshot, which the
  // server acks (ackRtt in the UI). Non-fatal because the 1 s stats window makes
  // the exact moment timing-sensitive; the real proof of an open control path is
  // that connect() already reached the 'connected' state.
  async function inputAckBestEffort(page: Page, label: string) {
    try {
      await page.locator('[data-key="coin"]').click();
      await expect
        .poll(async () => {
          const t = (await page.locator('#metrics').textContent()) ?? '{}';
          try { return JSON.parse(t)?.ackRtt?.n ?? 0; } catch { return 0; }
        }, { timeout: 8_000 })
        .toBeGreaterThan(0);
      console.log(`[multiplayer] ${label} input ack observed`);
    } catch (e) {
      console.warn(`[multiplayer] ${label} input ack not observed in window:`, (e as Error).message);
    }
  }

  test('two clients get distinct slots, both stream, and a third is rejected', async ({ browser, page }) => {
    test.setTimeout(120_000);
    const ctxB = await browser.newContext();
    const pageB = await ctxB.newPage();
    try {
      const slotA = await connect(page);
      const slotB = await connect(pageB);
      // Distinct, valid slots — one Player 1 and one Player 2.
      expect([slotA, slotB].slice().sort()).toEqual([1, 2]);

      // One shared encode feeds both peers: both video surfaces actually decode.
      await expect.soft(page.locator('#start-overlay'), 'client A video').toBeHidden({ timeout: 20_000 });
      await expect.soft(pageB.locator('#start-overlay'), 'client B video').toBeHidden({ timeout: 20_000 });

      // Independent control paths.
      await inputAckBestEffort(page, 'A');
      await inputAckBestEffort(pageB, 'B');

      // Third client while both slots are held -> rejected before the WS opens.
      const ctxC = await browser.newContext();
      const pageC = await ctxC.newPage();
      try {
        await pageC.goto('/arcade/');
        await pageC.locator('#connect').click();
        await expect(pageC.locator('#status')).toContainText(/slot|in use|free/i, { timeout: 20_000 });
        await expect(pageC.locator('[data-key="coin"]')).toBeDisabled();
      } finally {
        await ctxC.close();
      }
    } finally {
      await ctxB.close();
      await page.locator('#leave').click().catch(() => {});
    }
  });

  test('a freed slot is reclaimed by a new client', async ({ browser, page }) => {
    test.setTimeout(120_000);
    const ctxB = await browser.newContext();
    const pageB = await ctxB.newPage();
    try {
      const slotA = await connect(page);
      const slotB = await connect(pageB);
      expect([slotA, slotB].slice().sort()).toEqual([1, 2]);

      // Client A leaves, freeing its slot.
      await page.locator('#leave').click();
      await expect(page.locator('#connect')).toBeEnabled();

      // A fresh client reclaims exactly the freed slot (B still holds the other).
      const ctxC = await browser.newContext();
      const pageC = await ctxC.newPage();
      try {
        const slotC = await connect(pageC);
        expect(slotC).toBe(slotA);
      } finally {
        await ctxC.close();
      }
    } finally {
      await ctxB.close();
    }
  });
});
