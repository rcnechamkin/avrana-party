// AVR-762 measurements: load bytes/requests/time, heap, and open / tab / Back to Game latency
// (20-run medians), for vanilla vs Svelte and mounted (M) vs restored (R). Needs the proof's
// servers running (node server/start.mjs, after npm run build). Optional baseline of the real
// console: BASELINE_URL=http://127.0.0.1:8380/party/ with `python -m avrana.web.devserver --port 8380 --party`.
//
//   node tests/measure.mjs [runs=20]     -> results/measure.json
import { chromium, webkit } from '@playwright/test';
import { gzipSync } from 'node:zlib';
import { mkdirSync, writeFileSync } from 'node:fs';

const RUNS = Number(process.argv[2] || 20);
const PARTY = 'http://party.cp.test:8370', GAME = 'http://games.cp.test:8371', ADMIN = 'http://127.0.0.1:8370';
const phone = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, serviceWorkers: 'block' };
const engines = {
  chromium: { type: chromium, launch: { args: ['--host-resolver-rules=MAP *.cp.test 127.0.0.1'] }, ctx: {} },
  webkit: { type: webkit, launch: {}, ctx: { proxy: { server: 'http://127.0.0.1:8372', bypass: '127.0.0.1' } } },
};
const median = (xs) => { const s = [...xs].sort((a, b) => a - b); return s.length ? Math.round(s[Math.floor(s.length / 2)] * 10) / 10 : null; };
const p90 = (xs) => { const s = [...xs].sort((a, b) => a - b); return s.length ? Math.round(s[Math.floor(s.length * 0.9)] * 10) / 10 : null; };
const admin = (path, body = {}) => fetch(ADMIN + path, { method: 'POST', headers: { 'x-cp-test': '1', 'content-type': 'application/json' }, body: JSON.stringify(body) }).then((r) => r.json());

/** Raw and gzip bytes of everything a page requested (bodies fetched again from the servers). */
async function inventory(urls) {
  let raw = 0, gz = 0, js = 0, jsGz = 0;
  for (const u of urls) {
    const url = new URL(u);
    const port = url.port || 80;
    if (url.pathname.startsWith('/api/')) continue;                    // data, not the app
    const body = Buffer.from(await (await fetch(`http://127.0.0.1:${port}${url.pathname}${url.search}`)).arrayBuffer());
    raw += body.length; const g = gzipSync(body, { level: 9 }).length; gz += g;
    if (/\.m?js$/.test(url.pathname)) { js += body.length; jsGz += g; }
  }
  return { requests: urls.length, raw, gzip: gz, jsRaw: js, jsGzip: jsGz };
}

async function heap(ctx, page) {
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('HeapProfiler.enable'); await cdp.send('HeapProfiler.collectGarbage');
  await cdp.send('Performance.enable');
  const m = Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((x) => [x.name, x.value]));
  return { jsHeapUsedKB: Math.round(m.JSHeapUsedSize / 1024), nodes: m.Nodes, documents: m.Documents, frames: m.Frames };
}

async function joined(browser, engine, seat = 'rt') {
  const ctx = await browser.newContext({ ...phone, ...engines[engine].ctx });
  const page = await ctx.newPage();
  await page.goto(`${PARTY}/api/dev-join?name=M&seat=${seat}`);
  return { ctx, page };
}
const ready = (page) => page.waitForFunction(() => window.__probe && window.__probe.ready && window.__probe.role, null, { timeout: 15000 });
const layerFrame = (page) => page.frames().find((f) => f.url().includes('/layer?'));

async function measureLoad(browser, engine, fw) {
  const { ctx, page } = await joined(browser, engine);
  const urls = [];
  page.on('request', (r) => { if (!r.url().includes('/api/')) urls.push(r.url()); });
  const cold = [], warm = [];
  // cold: a fresh context each time (empty HTTP cache); warm: reload in the same context
  await page.goto(`${PARTY}/party/x/${fw}/?s=R`); await page.locator('body[data-ready="1"]').waitFor();
  const inv = await inventory([...new Set(urls)]);
  const out = { ...inv };
  if (engine === 'chromium') out.heap = await heap(ctx, page);
  for (let i = 0; i < Math.min(RUNS, 10); i++) {
    const c = await joined(browser, engine);
    await c.page.goto(`${PARTY}/party/x/${fw}/?s=R`); await c.page.locator('body[data-ready="1"]').waitFor();
    cold.push(await c.page.evaluate(() => performance.getEntriesByName('console-ready')[0].startTime));
    await c.page.reload(); await c.page.locator('body[data-ready="1"]').waitFor();
    warm.push(await c.page.evaluate(() => performance.getEntriesByName('console-ready')[0].startTime));
    await c.ctx.close();
  }
  out.readyColdMs = median(cold); out.readyWarmMs = median(warm);
  await ctx.close();
  return out;
}

/** M: open drawer, switch tab, Back to Game, all timed inside the layer frame to the next frames. */
async function measureM(browser, engine, fw) {
  const { ctx, page } = await joined(browser, engine);
  await page.goto(`${GAME}/rt.html?fw=${fw}&s=M`); await ready(page);
  await page.waitForFunction(() => document.querySelector('iframe[title="Your Party"]').dataset.avranaPartyLayer === 'button');
  const f = layerFrame(page);
  await f.waitForSelector('#layer-button');
  const open = [], tab = [], back = [];
  for (let i = 0; i < RUNS; i++) {
    open.push(await f.evaluate(() => new Promise((resolve) => {
      const t0 = performance.now(); document.getElementById('layer-button').click();
      (function wait() { const b = document.getElementById('back-to-game'); if (b && b.offsetParent && innerHeight > 200) resolve(performance.now() - t0); else requestAnimationFrame(wait); })();
    })));
    tab.push(await f.evaluate(() => new Promise((resolve) => {
      const t0 = performance.now(); document.getElementById('tab-library').click();
      (function wait() { const l = document.querySelector('#library li'); if (l && l.offsetParent) { requestAnimationFrame(() => resolve(performance.now() - t0)); } else requestAnimationFrame(wait); })();
    })));
    await f.evaluate(() => document.getElementById('tab-home').click());
    back.push(await f.evaluate(() => new Promise((resolve) => {
      const t0 = performance.now(); document.getElementById('back-to-game').click();
      (function wait() { if (innerHeight < 100 && document.getElementById('layer-button')) resolve(performance.now() - t0); else requestAnimationFrame(wait); })();
    })));
  }
  const p = await page.evaluate(() => window.__probe);
  const out = { openMs: median(open), openP90: p90(open), tabMs: median(tab), backMs: median(back), backP90: p90(back), ticksMissed: p.missed, reconnects: p.reconnects, wsOpens: p.wsOpens };
  if (engine === 'chromium') { await f.evaluate(() => document.getElementById('layer-button').click()); await page.waitForTimeout(300); out.heapGameWithLayerOpen = await heap(ctx, page); }
  await ctx.close();
  return out;
}

/** R: game -> Party console page -> Back to Game -> game ready again, wall-clock epoch ms. */
async function measureR(browser, engine, fw) {
  const { ctx, page } = await joined(browser, engine);
  await page.goto(`${GAME}/rt.html?fw=${fw}&s=R`); await ready(page);
  const open = [], back = [], away = [], gap = [];
  for (let i = 0; i < RUNS; i++) {
    await page.waitForFunction(() => document.querySelector('iframe[title="Your Party"]').dataset.avranaPartyLayer === 'button');
    let f = layerFrame(page); await f.waitForSelector('#layer-button');
    const leftTick = await page.evaluate(() => window.__probe.lastTick);
    const t0 = await f.evaluate(() => { const t = Date.now(); document.getElementById('layer-button').click(); return t; });
    await page.waitForURL(/party\.cp\.test/); await page.locator('body[data-ready="1"]').waitFor();
    const t1 = await page.evaluate(() => performance.timeOrigin + performance.getEntriesByName('console-ready')[0].startTime);
    const t2 = await page.evaluate(() => { const t = Date.now(); document.getElementById('back-to-game').click(); return t; });
    await page.waitForURL(/games\.cp\.test/); await ready(page);
    const p = await page.evaluate(() => ({ at: performance.timeOrigin + window.__probe.readyAt, tick: window.__probe.lastTick }));
    open.push(t1 - t0); back.push(p.at - t2); away.push(p.at - t0); gap.push(p.tick - leftTick);
  }
  const out = { openMs: median(open), openP90: p90(open), backMs: median(back), backP90: p90(back), awayMs: median(away), ticksNotReceivedWhileAway: median(gap), wsOpensPerReturn: 1 };
  if (engine === 'chromium') out.heapGamePage = await heap(ctx, page);
  if (engine === 'chromium') { await page.goto(`${PARTY}/party/x/${fw}/?s=R`); await page.locator('body[data-ready="1"]').waitFor(); out.heapConsolePage = await heap(ctx, page); }
  await ctx.close();
  return out;
}

async function measureBaseline(browser) {
  const url = process.env.BASELINE_URL; if (!url) return null;
  const ctx = await browser.newContext({ ...phone });
  const page = await ctx.newPage();
  const urls = [];
  page.on('request', (r) => urls.push(r.url()));
  await page.goto(url, { waitUntil: 'load' }); await page.waitForTimeout(1500);
  const inv = await inventory([...new Set(urls)].filter((u) => !u.includes('/api/')));
  const nav = await page.evaluate(() => { const n = performance.getEntriesByType('navigation')[0]; return { dclMs: Math.round(n.domContentLoadedEventEnd), loadMs: Math.round(n.loadEventEnd) }; });
  const h = await heap(ctx, page);
  const warm = []; const cold = [];
  for (let i = 0; i < 10; i++) {
    const c = await browser.newContext({ ...phone }); const p = await c.newPage();
    await p.goto(url, { waitUntil: 'load' }); cold.push(await p.evaluate(() => performance.getEntriesByType('navigation')[0].loadEventEnd));
    await p.reload({ waitUntil: 'load' }); warm.push(await p.evaluate(() => performance.getEntriesByType('navigation')[0].loadEventEnd));
    await c.close();
  }
  await ctx.close();
  return { url, ...inv, ...nav, loadColdMs: median(cold), loadWarmMs: median(warm), heap: h, note: 'the real Party Home (/party/) on the devserver; ready = load event (no app ready mark)' };
}

const results = { runs: RUNS, at: new Date().toISOString(), phone: '390x844 DPR3 isMobile hasTouch (Chromium: CDP device metrics emulation)', engines: {} };
for (const [engine, e] of Object.entries(engines)) {
  const browser = await e.type.launch(e.launch);
  results.engines[engine] = { version: browser.version() };
  if (engine === 'chromium') results.baseline = await measureBaseline(browser);
  for (const fw of ['vanilla', 'svelte']) {
    await admin('/test/reset');
    results.engines[engine][fw] = { load: await measureLoad(browser, engine, fw), M: await measureM(browser, engine, fw), R: await measureR(browser, engine, fw) };
    console.log(engine, fw, JSON.stringify(results.engines[engine][fw]));
  }
  await browser.close();
}
mkdirSync(new URL('../results/', import.meta.url), { recursive: true });
writeFileSync(new URL('../results/measure.json', import.meta.url), JSON.stringify(results, null, 2) + '\n');
console.log('wrote results/measure.json');
