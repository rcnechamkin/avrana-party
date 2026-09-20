/**
 * Playwright driver helpers for the load/soak/fault harness: connect a client as
 * a real WebRTC peer, read its self-reported #metrics, and sample the server
 * /stats. Kept separate from soak-metrics.ts (pure logic) so the analysis is
 * unit-testable without a browser.
 */
import { expect, type Page, type APIRequestContext } from '@playwright/test';
import type { ClientSample, ServerSample } from './soak-metrics';

/** Connect a client through the full Play → slot → WebRTC-connected flow. Returns the player slot. */
export async function connectClient(page: Page): Promise<number> {
  await page.goto('/arcade/');
  await expect(page.locator('#connect')).toBeVisible();
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toContainText(/Player\s*\d/i, { timeout: 30_000 });
  await expect(page.locator('#leave')).toBeEnabled({ timeout: 30_000 });
  await expect(page.locator('[data-key="coin"]')).toBeEnabled();
  const h1 = (await page.locator('h1').textContent()) ?? '';
  const m = h1.match(/Player\s*(\d)/i);
  return m ? Number(m[1]) : NaN;
}

/**
 * Attempt to connect, tolerating rejection (used for over-subscription tests).
 * Resolves { connected, slot? } once the client either reaches 'connected' or is
 * turned away (WS refused because all slots are held).
 */
export async function tryConnect(page: Page): Promise<{ connected: boolean; slot?: number }> {
  await page.goto('/arcade/');
  await page.locator('#connect').click();
  const connected = page.locator('#leave');
  const rejected = page.locator('#status');
  const outcome = await Promise.race([
    connected.waitFor({ state: 'attached' }).then(async () => {
      await expect(connected).toBeEnabled({ timeout: 30_000 });
      return 'connected' as const;
    }).catch(() => 'unknown' as const),
    rejected.filter({ hasText: /slot|in use|free/i }).waitFor({ timeout: 30_000 })
      .then(() => 'rejected' as const).catch(() => 'unknown' as const),
  ]);
  if (outcome === 'connected' && await connected.isEnabled()) {
    const h1 = (await page.locator('h1').textContent()) ?? '';
    const m = h1.match(/Player\s*(\d)/i);
    return { connected: true, slot: m ? Number(m[1]) : NaN };
  }
  return { connected: false };
}

/** Read a connected client's self-reported WebRTC stats from the #metrics element. */
export async function readClientMetrics(page: Page, t: number): Promise<ClientSample> {
  const txt = (await page.locator('#metrics').textContent()) ?? '{}';
  let o: any = {};
  try { o = JSON.parse(txt); } catch { /* mid-update; leave empty */ }
  const v = o.video ?? {};
  const rtt = o.pair?.rtt;
  return {
    t,
    fps: v.fps ?? null,
    pktLostD: v.pktLostD ?? null,
    jitterBufMs: v.jitterBufMs ?? null,
    pairRttMs: typeof rtt === 'number' ? +(rtt * 1000).toFixed(1) : null,
    freezes: v.freezes ?? null,
    kbps: v.kbps ?? null,
  };
}

/** Sample the server /stats endpoint. */
export async function sampleServer(request: APIRequestContext, t: number): Promise<ServerSample> {
  const res = await request.get('/arcade/stats');
  const s = await res.json();
  return {
    t,
    players: s.players,
    error: s.error,
    audioAgeP50: s.capture_age_ms?.audio?.p50 ?? null,
    videoAgeP50: s.capture_age_ms?.video?.p50 ?? null,
    uptime: typeof s.uptime === 'number' ? Math.round(s.uptime) : null,
  };
}

/** MAX_PLAYERS as reported by the live server (so the harness doesn't hard-code it). */
export async function serverMaxPlayers(request: APIRequestContext): Promise<number> {
  const s = await (await request.get('/arcade/stats')).json();
  return s.max_players;
}

/**
 * Fail fast with an actionable message if the appliance is unreachable — almost
 * always because this laptop fell off the "Avrana Party" Wi-Fi (a recurring
 * environmental flake), not a Pi problem.
 */
export async function assertReachable(request: APIRequestContext): Promise<void> {
  try {
    const r = await request.get('/arcade/stats', { timeout: 8000 });
    if (!r.ok()) throw new Error(`/arcade/stats returned HTTP ${r.status()}`);
  } catch (e) {
    throw new Error(
      'Cannot reach http://party.avrana/arcade/stats — is this machine joined to the ' +
      `"Avrana Party" Wi-Fi (10.42.0.1)? Underlying: ${(e as Error).message}`);
  }
}
