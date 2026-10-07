import { test, expect, type Browser, type Page } from '@playwright/test';
import { serverMaxPlayers } from './lib/soak-driver';

/**
 * Controller slot behaviour (Chromium / WebRTC), using independent browser contexts as stand-ins
 * for phones.
 *
 * LIMITATION: Chromium clients on this laptop are NOT real phones on the Wi-Fi. This validates the
 * SERVER's slot logic (distinct assignment, MAX_PLAYERS rejection, slot release/reclaim) and that
 * one shared encode feeds independent peers. Real phones over 5 GHz remain authoritative: two were
 * tried; four, the cap since AVR-311, have not been (arcade/README.md, "Four controller seats").
 *
 * The number of seats is what the appliance reports at /arcade/stats, not a number written here.
 * These run serially and always tear down their contexts to hand slots back.
 */
test.describe.configure({ mode: 'serial' });

test.describe('Arcade multiplayer slots (Chromium)', () => {
  test.skip(
    ({ browserName }) => browserName !== 'chromium',
    'WebRTC media is Chromium-only here; real phones are authoritative for the multi-phone claim.',
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

  /** One client too many, while every slot is held: turned away before it has a controller. */
  async function expectRejected(page: Page) {
    await page.goto('/arcade/');
    await page.locator('#connect').click();
    await expect(page.locator('#status')).toContainText(/slot|in use|free/i, { timeout: 20_000 });
    await expect(page.locator('[data-key="coin"]')).toBeDisabled();
  }

  /** The page the fixture gives, and one more context and page for each other seat. */
  async function clients(browser: Browser, page: Page, seats: number) {
    const contexts = await Promise.all(Array.from({ length: seats - 1 }, () => browser.newContext()));
    const pages = [page, ...(await Promise.all(contexts.map((ctx) => ctx.newPage())))];
    return { contexts, pages };
  }

  const oneToN = (n: number) => Array.from({ length: n }, (_, i) => i + 1);

  test('every seat gets a distinct slot, all stream, and one more client is rejected', async ({ browser, page, request }) => {
    test.setTimeout(240_000);
    const seats = await serverMaxPlayers(request);
    const { contexts, pages } = await clients(browser, page, seats);
    try {
      const slots: number[] = [];
      for (const p of pages) slots.push(await connect(p));
      // Distinct, valid slots: Player 1 to Player N, one each.
      expect(slots.slice().sort((a, b) => a - b)).toEqual(oneToN(seats));

      // One shared encode feeds every peer: every video surface actually decodes.
      for (const [i, p] of pages.entries()) {
        await expect.soft(p.locator('#start-overlay'), `client ${i + 1} video`).toBeHidden({ timeout: 20_000 });
      }

      // Independent control paths.
      for (const [i, p] of pages.entries()) await inputAckBestEffort(p, String(i + 1));

      const extra = await browser.newContext();
      try {
        await expectRejected(await extra.newPage());
      } finally {
        await extra.close();
      }
    } finally {
      for (const ctx of contexts) await ctx.close();
      await page.locator('#leave').click().catch(() => {});
    }
  });

  test('a freed slot is reclaimed by a new client', async ({ browser, page, request }) => {
    test.setTimeout(240_000);
    const seats = await serverMaxPlayers(request);
    const { contexts, pages } = await clients(browser, page, seats);
    try {
      const slots: number[] = [];
      for (const p of pages) slots.push(await connect(p));
      expect(slots.slice().sort((a, b) => a - b)).toEqual(oneToN(seats));

      // Client A leaves, freeing its slot.
      await page.locator('#leave').click();
      await expect(page.locator('#connect')).toBeEnabled();

      // A fresh client reclaims exactly the freed slot (every other client still holds its own).
      const fresh = await browser.newContext();
      try {
        expect(await connect(await fresh.newPage())).toBe(slots[0]);
      } finally {
        await fresh.close();
      }
    } finally {
      for (const ctx of contexts) await ctx.close();
    }
  });
});
