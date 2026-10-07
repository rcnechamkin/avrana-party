import { test, expect, type Page } from '@playwright/test';
import { summarizeClientSeries } from './lib/soak-metrics';
import { connectClient, tryConnect, readClientMetrics, sampleServer, serverMaxPlayers, assertReachable } from './lib/soak-driver';

/**
 * Fault injection & recovery (Chromium, @heavy). Exercises the RUNNING service
 * under abnormal client behaviour — abrupt drop, churn, over-subscription — and
 * asserts the survivors keep streaming and the server recovers. It never modifies
 * the service.
 *
 * Limitation: closing a context is a clean "app closed" (TCP FIN), not a silent
 * network partition (that needs packet-level tooling + the WS heartbeat timeout);
 * noted for a future harness iteration.
 */
test.describe.configure({ mode: 'serial' });

test.describe('@heavy fault injection & recovery', () => {
  test.skip(({ browserName }) => browserName !== 'chromium', 'WebRTC on Chromium only.');

  test.beforeEach(async ({ request }) => { await assertReachable(request); });

  async function sampleClient(page: Page, n: number, gapMs = 1500) {
    const s = [];
    for (let i = 0; i < n; i++) { s.push(await readClientMetrics(page, i)); await page.waitForTimeout(gapMs); }
    return summarizeClientSeries(s);
  }

  test('abrupt client drop: survivor keeps streaming and the slot is reclaimed', async ({ browser, request }) => {
    test.setTimeout(90_000);
    const ctxA = await browser.newContext(), ctxB = await browser.newContext();
    try {
      const a = await ctxA.newPage(), b = await ctxB.newPage();
      const slotA = await connectClient(a);
      const slotB = await connectClient(b);
      expect([slotA, slotB].slice().sort()).toEqual([1, 2]);

      // Kill A abruptly.
      await ctxA.close();

      // B must keep streaming smoothly through A's departure.
      const survivor = await sampleClient(b, 6);
      expect(survivor.fps.med, `survivor fps med ${survivor.fps.med}`).toBeGreaterThanOrEqual(55);
      expect((await sampleServer(request, 0)).error).toBeFalsy();

      // The freed slot must be grantable to a new client.
      const ctxC = await browser.newContext();
      try {
        const slotC = await connectClient(await ctxC.newPage());
        expect(slotC).toBe(slotA);
      } finally { await ctxC.close(); }
    } finally {
      await ctxA.close().catch(() => {});
      await ctxB.close().catch(() => {});
    }
  });

  test('connect/disconnect churn leaves the server healthy', async ({ browser, request }) => {
    test.setTimeout(120_000);
    for (let i = 0; i < 5; i++) {
      const ctx = await browser.newContext();
      const page = await ctx.newPage();
      await connectClient(page);
      await ctx.close(); // abrupt drop each cycle
    }
    // After the churn, no error, slots freed, and a fresh client still connects and streams.
    const st = await sampleServer(request, 0);
    expect(st.error).toBeFalsy();
    const ctx = await browser.newContext();
    try {
      const page = await ctx.newPage();
      await connectClient(page);
      const sum = await sampleClient(page, 4);
      expect(sum.fps.med, `post-churn fps med ${sum.fps.med}`).toBeGreaterThanOrEqual(55);
    } finally { await ctx.close(); }
  });

  test('over-subscription: only MAX_PLAYERS connect, extras rejected, then full recovery', async ({ browser, request }) => {
    test.setTimeout(120_000);
    const maxPlayers = await serverMaxPlayers(request);
    const contexts = [];
    try {
      let connected = 0;
      for (let i = 0; i < maxPlayers; i++) {
        const ctx = await browser.newContext(); contexts.push(ctx);
        await connectClient(await ctx.newPage()); connected++;
      }
      expect(connected).toBe(maxPlayers);
      // One extra must be refused.
      const extraCtx = await browser.newContext(); contexts.push(extraCtx);
      const extra = await tryConnect(await extraCtx.newPage());
      expect(extra.connected).toBe(false);
      expect((await sampleServer(request, 0)).error).toBeFalsy();
    } finally {
      for (const c of contexts) await c.close().catch(() => {});
    }
    // Full recovery: after everyone leaves, a fresh client connects again.
    const ctx = await browser.newContext();
    try {
      const slot = await connectClient(await ctx.newPage());
      expect(slot).toBeGreaterThanOrEqual(1);
      expect(slot).toBeLessThanOrEqual(maxPlayers);
    } finally { await ctx.close(); }
  });
});
