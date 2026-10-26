// Strategy probes (framework-independent): does the game keep executing while the console is up?
// Records rAF and tick rates per condition, WebGL loss/restore, bfcache and lifecycle events, and
// whether the layer frame can detect being covered. Writes results/probes-<engine>.json.
import { mkdirSync, writeFileSync } from 'node:fs';
import { PARTY, admin, expect, layerFrame, openConsole, openGame, phone, probe, test, waitReady } from './fixtures';
import type { Frame, Page } from '@playwright/test';

const out: Record<string, unknown> = {};
test.beforeEach(async ({ request }) => { await request.post('http://127.0.0.1:8370/test/reset', { headers: { 'x-cp-test': '1' } }); });
test.afterAll(async ({}, info) => {
  mkdirSync(new URL('../results/', import.meta.url), { recursive: true });
  writeFileSync(new URL(`../results/probes-${info.project.name.split('-')[0]}.json`, import.meta.url), JSON.stringify(out, null, 2) + '\n');
});

/** rAF callbacks and server ticks per second in `target` over `ms`. */
async function rate(target: Page | Frame, ms = 2000) {
  const read = () => target.evaluate(() => { const p = (window as any).__probe; return { raf: p.raf, ticks: p.ticks, missed: p.missed, vis: document.visibilityState, hidden: document.hidden }; });
  const a = await read();
  await new Promise((r) => setTimeout(r, ms));
  const b = await read();
  return { rafPerSec: Math.round((b.raf - a.raf) * 1000 / ms), ticksPerSec: Math.round((b.ticks - a.ticks) * 1000 / ms), missed: b.missed - a.missed, visibility: b.vis };
}

test('rAF and socket ticks: top-level occluded by the open layer vs framed and hidden', async ({ browser, browserName }) => {
  const p = await phone(browser, 'P1', 'rt');
  await openGame(p, 'rt', 'vanilla', 'M');
  out.baseline = await rate(p.page);
  await openConsole(p.page, 'M');
  out.M_layerOpen_occluded = await rate(p.page);
  expect((out.M_layerOpen_occluded as any).missed, 'no tick lost while the console is open over the game').toBe(0);
  expect((out.M_layerOpen_occluded as any).ticksPerSec).toBeGreaterThanOrEqual(15);

  // A second tab in front: is the game's top-level document hidden, and what runs?
  const other = await p.ctx.newPage();
  await other.goto(`${PARTY}/party/x/vanilla/?s=R`);
  await other.bringToFront();
  out.topLevel_backgroundTab = await rate(p.page);
  await other.close();
  await p.page.bringToFront();

  // What a phone does to a backgrounded or locked tab: freeze it (Chromium CDP lifecycle emulation).
  if (browserName === 'chromium') {
    const cdp = await p.ctx.newCDPSession(p.page);
    const before = await probe(p.page);
    await cdp.send('Page.setWebLifecycleState', { state: 'frozen' });
    await new Promise((r) => setTimeout(r, 3000));
    await cdp.send('Page.setWebLifecycleState', { state: 'active' });
    await p.page.waitForTimeout(1500);
    const after = await probe(p.page);
    out.topLevel_frozen3s = { rafDuring3sPlus1_5s: after.raf - before.raf, ticksMissedAfterResume: after.missed - before.missed, reconnects: after.reconnects - before.reconnects,
      events: after.events.slice(before.events.length).map((e: any) => e.type) };
  }

  // The embedded variant: a Party page framing the game, with the frame occluded or hidden.
  for (const hide of ['occlude', 'display', 'visibility', 'offscreen']) {
    const page = p.page;
    await page.goto(`${PARTY}/party/x/vanilla/embed.html?hide=${hide}`);
    const frame = await (await page.locator('#game').elementHandle())!.contentFrame();
    await frame!.waitForFunction(() => (window as any).__probe && (window as any).__probe.ready);
    await page.locator('#open').click();
    out[`embed_${hide}`] = await rate(frame!);
    await page.locator('#back-to-game').click();
  }
  await p.ctx.close();
});

test('WebGL context loss and restore while the console is open (M)', async ({ browser }) => {
  const p = await phone(browser, 'P1', 'rt');
  await openGame(p, 'rt', 'vanilla', 'M');
  await openConsole(p.page, 'M');
  const can = await p.page.evaluate(() => (window as any).__probe.loseGl());
  if (can) await expect.poll(async () => { const x = await probe(p.page); return [x.glLost, x.glRestored]; }).toEqual([1, 1]);
  out.webgl = { loseContextExtension: can, ...(can ? { lost: 1, restored: 1 } : {}) };
  await p.ctx.close();
});

test('R path lifecycle: pagehide on leaving, bfcache on Back, fresh load on Back to Game', async ({ browser }) => {
  const p = await phone(browser, 'P1', 'rt');
  await openGame(p, 'rt', 'vanilla', 'R');
  await openConsole(p.page, 'R');
  // history Back from the console to the game: restored from bfcache, or loaded again?
  await p.page.goBack();
  await waitReady(p.page);
  const back = await probe(p.page);
  out.R_historyBack = { pageshowPersisted: back.events.some((e: any) => e.type === 'pageshow' && e.persisted), leaveEvents: back.previous && back.previous.events.filter((e: any) => e.type !== 'pageshow').map((e: any) => `${e.type}${e.persisted !== undefined ? `(persisted=${e.persisted})` : ''}:${e.vis}`), wsOpens: back.wsOpens };
  await openConsole(p.page, 'R');
  await p.page.locator('#back-to-game').click();
  await p.page.waitForURL(/games\.cp\.test/); await waitReady(p.page);
  const fwd = await probe(p.page);
  out.R_backToGame = { pageshowPersisted: fwd.events.some((e: any) => e.type === 'pageshow' && e.persisted), wsOpens: fwd.wsOpens, readyMs: Math.round(fwd.readyAt) };
  await p.ctx.close();
});

test('can the Party layer frame detect a game element covering it? (IntersectionObserver v2)', async ({ browser }) => {
  const p = await phone(browser, 'P1', 'rt');
  await openGame(p, 'rt', 'vanilla', 'M');
  await openConsole(p.page, 'M');
  const frame = p.page.frames().find((f) => f.url().includes('/layer'))!;
  const watch = () => frame.evaluate(() => new Promise((resolve) => {
    try {
      const el = document.getElementById('back-to-game')!;
      const io = new IntersectionObserver((entries) => { io.disconnect(); resolve((entries[0] as any).isVisible ?? 'unsupported'); }, { trackVisibility: true, delay: 100 } as any);
      io.observe(el);
      setTimeout(() => resolve('timeout'), 2000);
    } catch (e) { resolve('unsupported: ' + (e as Error).message); }
  }));
  const before = await watch();
  await p.page.evaluate(() => { const d = document.createElement('div'); Object.assign(d.style, { position: 'fixed', inset: '0', zIndex: '2147483647', background: 'transparent' }); document.body.append(d); });
  const after = await watch();
  out.occlusionDetect = { uncovered: before, covered: after };
  await p.ctx.close();
});
