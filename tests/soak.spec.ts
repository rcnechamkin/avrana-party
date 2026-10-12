import { test, expect, type Browser, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {
  summarizeClientSeries, summarizeServerSeries, evaluate, formatReport,
  type ClientSample, type ServerSample, type ClientSummary,
} from './lib/soak-metrics';
import { connectClient, tryConnect, readClientMetrics, sampleServer, serverMaxPlayers, assertReachable } from './lib/soak-driver';

/**
 * Load / soak / regression harness (Chromium, tagged @heavy so it stays out of
 * the fast `npm test` run). Connects N real WebRTC clients, holds them for a
 * configurable duration, samples each client's stats + the server /stats every
 * interval, then evaluates regression thresholds and writes a JSON artifact.
 *
 * Config via env:
 *   SOAK_CLIENTS  (default 2)  target client count (extras beyond MAX_PLAYERS must be rejected).
 *                              Two clients is the load that was tried on real phones; the four
 *                              seats (AVR-311) need SOAK_CLIENTS=4, and a real four-phone night.
 *   SOAK_SECONDS  (default 90) hold duration
 *   SOAK_INTERVAL (default 5)  sample interval seconds
 *
 * Real phones remain authoritative; Chromium clients validate the server/
 * encoder behaviour repeatably.
 */
const CLIENTS = Number(process.env.SOAK_CLIENTS ?? 2);
const SECONDS = Number(process.env.SOAK_SECONDS ?? 90);
const INTERVAL = Number(process.env.SOAK_INTERVAL ?? 5);

test.describe('@heavy soak', () => {
  test.skip(({ browserName }) => browserName !== 'chromium',
    'WebRTC load is driven on Chromium; real phones remain authoritative.');

  test(`soak: ${CLIENTS} client(s) for ${SECONDS}s`, async ({ browser, request }, testInfo) => {
    test.setTimeout((SECONDS + 90) * 1000);
    await assertReachable(request);
    const maxPlayers = await serverMaxPlayers(request);
    const expectedConnected = Math.min(CLIENTS, maxPlayers);

    const clients: { label: string; slot: number; page: Page; samples: ClientSample[] }[] = [];
    const rejected: number[] = [];
    const serverSamples: ServerSample[] = [];
    const contexts = [] as Awaited<ReturnType<Browser['newContext']>>[];

    try {
      // Connect the clients that should fit.
      for (let i = 0; i < expectedConnected; i++) {
        const ctx = await browser.newContext();
        contexts.push(ctx);
        const page = await ctx.newPage();
        const slot = await connectClient(page);
        clients.push({ label: `P${slot}`, slot, page, samples: [] });
      }
      // Any extras beyond MAX_PLAYERS must be turned away.
      for (let i = expectedConnected; i < CLIENTS; i++) {
        const ctx = await browser.newContext();
        contexts.push(ctx);
        const page = await ctx.newPage();
        const { connected } = await tryConnect(page);
        if (connected) rejected.push(-1); // sentinel: an extra wrongly connected
      }

      const t0 = Date.now();
      while ((Date.now() - t0) / 1000 < SECONDS) {
        const t = +((Date.now() - t0) / 1000).toFixed(1);
        serverSamples.push(await sampleServer(request, t));
        for (const c of clients) c.samples.push(await readClientMetrics(c.page, t));
        await clients[0]?.page.waitForTimeout(INTERVAL * 1000);
      }
    } finally {
      for (const ctx of contexts) await ctx.close().catch(() => {});
    }

    const clientSummaries = clients.map(c => ({ label: c.label, summary: summarizeClientSeries(c.samples) }));
    const server = summarizeServerSeries(serverSamples);
    const verdict = evaluate(clientSummaries, server, expectedConnected);
    if (rejected.length) verdict.violations.push('an extra client connected beyond MAX_PLAYERS');

    const report = formatReport(`soak ${CLIENTS}c/${SECONDS}s (max_players=${maxPlayers})`, clientSummaries, server, verdict);
    console.log('\n' + report + '\n');

    const dir = path.join('test-results', 'soak');
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, `soak-${CLIENTS}c-${Date.now()}.json`);
    fs.writeFileSync(file, JSON.stringify({
      config: { clients: CLIENTS, seconds: SECONDS, interval: INTERVAL, maxPlayers, expectedConnected },
      startedAt: new Date().toISOString(), verdict,
      clients: clients.map(c => ({ label: c.label, slot: c.slot, summary: summarizeClientSeries(c.samples), samples: c.samples })),
      server: { summary: server, samples: serverSamples },
    }, null, 2));
    await testInfo.attach('soak-report.txt', { body: report, contentType: 'text/plain' });
    await testInfo.attach('soak-data.json', { path: file, contentType: 'application/json' });

    expect(verdict.pass && rejected.length === 0, `\n${report}`).toBeTruthy();
  });
});
