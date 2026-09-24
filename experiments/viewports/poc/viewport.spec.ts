/**
 * Personal Viewports PoC — browser tests (laptop only; Chromium + WebKit headless).
 * Proves on real rendered pixels that every client gets the same source frame but shows only
 * its own seat's crop, that a reload keeps the seat, and how the crop fits both orientations.
 *
 *   npx playwright test -c experiments/viewports/poc/playwright.config.ts
 */
import { test, expect, Page, BrowserContext } from '@playwright/test';
import * as zlib from 'zlib';

// Seat colours drawn by the synthetic source (index.html COLORS), as RGB.
const SEAT_RGB = [[0xe6, 0x19, 0x4b], [0x3c, 0xb4, 0x4b], [0x43, 0x63, 0xd8], [0xf5, 0x82, 0x31]];

/** Minimal PNG decoder (8-bit RGB/RGBA, non-interlaced) — enough for Playwright screenshots. */
function decodePng(buf: Buffer) {
  let pos = 8, width = 0, height = 0, channels = 0;
  const idat: Buffer[] = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos), type = buf.toString('ascii', pos + 4, pos + 8);
    const data = buf.subarray(pos + 8, pos + 8 + len);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0); height = data.readUInt32BE(4);
      channels = ({ 2: 3, 6: 4 } as Record<number, number>)[data[9]];
      if (data[8] !== 8 || !channels || data[12] !== 0) throw new Error('unsupported PNG');
    } else if (type === 'IDAT') idat.push(data);
    pos += 12 + len;
  }
  const raw = zlib.inflateSync(Buffer.concat(idat)), stride = width * channels;
  const out = Buffer.alloc(height * stride);
  for (let y = 0; y < height; y++) {
    const f = raw[y * (stride + 1)], line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let x = 0; x < stride; x++) {
      const a = x >= channels ? out[y * stride + x - channels] : 0;
      const b = y > 0 ? out[(y - 1) * stride + x] : 0;
      const c = x >= channels && y > 0 ? out[(y - 1) * stride + x - channels] : 0;
      const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
      const pred = [0, a, b, (a + b) >> 1, pa <= pb && pa <= pc ? a : pb <= pc ? b : c][f];
      out[y * stride + x] = (line[x] + pred) & 0xff;
    }
  }
  return { width, height, px: (x: number, y: number) => {
    const i = Math.floor(y) * stride + Math.floor(x) * channels;
    return [out[i], out[i + 1], out[i + 2]];
  } };
}

const near = (a: number[], b: number[], tol = 40) => a.every((v, i) => Math.abs(v - b[i]) <= tol);

async function openSeat(context: BrowserContext, layout = '4') {
  const page = await context.newPage();
  await page.goto(`/?layout=${layout}`);
  await page.waitForFunction(() => (window as any).__poc?.ready && (window as any).__poc?.seat !== undefined
                                     && document.body.dataset.seat !== undefined);
  await page.waitForTimeout(300);                     // let a few frames render
  return page;
}

async function viewportImage(page: Page) {
  const shot = await page.locator('#vp').screenshot();
  return decodePng(shot);
}

async function seatOf(page: Page) { return Number(await page.evaluate(() => document.body.dataset.seat)); }

/** Give the seat back and close — the PoC server is shared by both browser projects. */
async function done(page: Page) {
  await page.evaluate(() => fetch('/release', { method: 'POST',
    body: JSON.stringify({ client: (window as any).__poc.client }) }));
  await page.context().close();
}

/** Every pixel on the rings 1 and 2 px inside the crop edges must be the seat's colour:
 *  that is where divider lines or a neighbour's pixels would bleed in. */
/** The ring is measured in CSS pixels: at devicePixelRatio 2 an element screenshot rounds its
 *  box outward by up to a device pixel or two, which shows the page's black background. */
function ringIsClean(img: ReturnType<typeof decodePng>, want: number[], dpr = 1) {
  let bad = 0, total = 0;
  const edges: Record<string, number> = { top: 0, bottom: 0, left: 0, right: 0 };
  let sample: number[] | null = null;
  const check = (x: number, y: number, edge: string) => {
    total++;
    const c = img.px(x, y);
    if (!near(c, want, 60)) { bad++; edges[edge]++; sample = sample || c; }
  };
  for (const css of [1, 2]) {
    const d = Math.ceil(css * dpr) + (dpr > 1 ? 1 : 0);
    for (let x = d; x < img.width - d; x += 2) { check(x, d, 'top'); check(x, img.height - 1 - d, 'bottom'); }
    for (let y = d; y < img.height - d; y += 2) { check(d, y, 'left'); check(img.width - 1 - d, y, 'right'); }
  }
  return { bad, total, edges, sample };
}

async function setPaused(pages: Page[], active: Page | null) {
  for (const p of pages) await p.evaluate(v => { (window as any).__poc.paused = v; }, p !== active);
}

test('each seat shows only its own region; the full view shows every region', async ({ browser }) => {
  test.setTimeout(180_000);
  for (const layout of ['4', '2h', '2v', '3']) {
    const n = layout === '4' ? 4 : layout === '3' ? 3 : 2;
    const pages: Page[] = [];
    for (let i = 0; i < n; i++) pages.push(await openSeat(await browser.newContext(), layout));
    expect(new Set(await Promise.all(pages.map(seatOf))).size).toBe(n);
    for (const page of pages) {
      await setPaused(pages, page);                   // one live page at a time (WebKit is slow)
      await page.waitForTimeout(100);
      const seat = await seatOf(page), img = await viewportImage(page);
      const want = SEAT_RGB[seat - 1];
      expect(near(img.px(img.width * 0.5, img.height * 0.25), want) ||
             near(img.px(img.width * 0.75, img.height * 0.25), want), `layout ${layout} seat ${seat} centre`).toBeTruthy();
      const box = (await page.locator('#vp').boundingBox())!;
      const ring = ringIsClean(img, want, img.width / box.width);
      expect(ring.bad / ring.total, `layout ${layout} seat ${seat} edge ring ${ring.bad}/${ring.total} ${JSON.stringify(ring.edges)} e.g. ${ring.sample} img ${img.width}x${img.height}`).toBeLessThan(0.02);
    }
    if (layout === '4') {                             // full view: the whole shared frame
      const page = pages[0];
      await setPaused(pages, page);
      await page.click('#full');
      await page.waitForTimeout(150);
      const full = await viewportImage(page);
      SEAT_RGB.forEach((rgb, i) => {
        const ox = (i % 2) * 0.5, oy = Math.floor(i / 2) * 0.5;
        const pts = [[0.30, 0.10], [0.70, 0.10], [0.85, 0.50], [0.70, 0.60], [0.45, 0.35]];
        const hits = pts.filter(([u, v]) => near(full.px(full.width * (ox + u / 2), full.height * (oy + v / 2)), rgb)).length;
        expect(hits, `full view region ${i + 1}`).toBeGreaterThanOrEqual(3);
      });
    }
    for (const p of pages) await done(p);
  }
});

test('Leave button frees the seat for a spectator, who then gets a crop', async ({ browser }) => {
  const pages: Page[] = [];
  for (let i = 0; i < 2; i++) pages.push(await openSeat(await browser.newContext(), '2v'));
  const spectator = await openSeat(await browser.newContext(), '2v');
  expect(await seatOf(spectator)).toBe(0);                    // all seats taken
  expect(await spectator.locator('#who').textContent()).toContain('Spectator');
  const leaver = pages[0], freed = await seatOf(leaver);
  await leaver.click('#leave');
  await expect(leaver.locator('#who')).toHaveText(/Left/);
  await spectator.reload();
  await spectator.waitForFunction(() => document.body.dataset.seat !== undefined && (window as any).__poc?.ready);
  expect(await seatOf(spectator)).toBe(freed);
  for (const p of [...pages, spectator]) await done(p);
});

test('a reload (reconnect) keeps the same seat and crop', async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await openSeat(ctx, '3');
  const seat = await seatOf(page);
  const geom = await page.locator('#geom').textContent();
  await page.reload();
  await page.waitForFunction(() => (window as any).__poc?.ready);
  await page.waitForFunction(() => document.body.dataset.seat !== undefined);
  expect(await seatOf(page)).toBe(seat);
  expect(await page.locator('#geom').textContent()).toBe(geom);
  await done(page);
});

test('orientation: an 8:3 crop fits by width in landscape and hints in portrait', async ({ browser }) => {
  for (const [w, h, expectHint] of [[844, 390, false], [390, 844, true]] as const) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    const page = await openSeat(ctx, '2h');          // both 2h seats are 8:3 halves
    const box = (await page.locator('#vp').boundingBox())!;
    expect(box.width / box.height).toBeGreaterThan(2.5);
    expect(box.width / box.height).toBeLessThan(2.8);
    const stage = (await page.locator('#stage').boundingBox())!;
    expect(box.width).toBeLessThanOrEqual(stage.width + 1);   // contain: never overflows
    expect(box.height).toBeLessThanOrEqual(stage.height + 1);
    expect(await page.locator('#hint').isVisible()).toBe(expectHint);
    await done(page);
  }
});

test('a 4:3 quadrant in portrait does not nag to rotate', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await openSeat(ctx, '4');
  expect(await page.locator('#hint').isVisible()).toBe(false);
  await done(page);
});

test('crop is static CSS; frame gaps recorded for crop vs full view (not asserted)', async ({ browser, browserName }) => {
  const ctx = await browser.newContext();
  const page = await openSeat(ctx, '2v');
  const src = page.locator('#vp > video, #vp > canvas').first();
  const style = await src.getAttribute('style');
  await page.waitForTimeout(500);
  expect(await src.getAttribute('style')).toBe(style);                      // unchanged across frames
  expect(style).toMatch(/width: 2\d\d(\.\d+)?%/);                          // scaled ~2x for a half
  const sample = async () => {
    await page.evaluate(() => { (window as any).__poc.gaps.length = 0; });
    await page.waitForTimeout(2000);
    const g: number[] = await page.evaluate(() => [...(window as any).__poc.gaps]);
    g.sort((a, b) => a - b);
    return g.length ? { n: g.length, p50: g[g.length >> 1], p95: g[Math.floor(g.length * 0.95)] } : null;
  };
  const crop = await sample();
  await page.click('#full');
  const full = await sample();
  // Headless timing is too noisy to gate on; the numbers are printed as evidence.
  console.log(`[${browserName}] frame gaps ms — crop: ${JSON.stringify(crop)} full: ${JSON.stringify(full)}`);
  await done(page);
});

test('shared WebRTC source: one source page streams to four viewers, each crops its own seat', async ({ browser, browserName }) => {
  test.skip(browserName !== 'chromium', 'Playwright WebKit on Windows has no usable WebRTC; real iPhones test this by hand');
  test.setTimeout(90_000);
  const src = await (await browser.newContext()).newPage();
  await src.goto('/?role=source&layout=4');
  await src.waitForFunction(() => (window as any).__poc?.ready);
  const viewers: Page[] = [];
  for (let i = 0; i < 4; i++) {
    const p = await (await browser.newContext({ viewport: { width: 480, height: 400 } })).newPage();
    await p.goto('/?layout=4&source=rtc');
    viewers.push(p);
  }
  for (const p of viewers) {
    await p.waitForFunction(() => (window as any).__poc?.ready && (window as any).__poc.latency.length >= 30,
                            null, { timeout: 45_000 });
  }
  const report: string[] = [];
  const seats = new Set<number>();
  for (const p of viewers) {
    const seat = await seatOf(p);
    seats.add(seat);
    const img = await viewportImage(p);
    const want = SEAT_RGB[seat - 1];
    let bad = 0, total = 0;                       // the inner 60 %: the seat's colour through a real codec
    for (let fx = 0.2; fx <= 0.8; fx += 0.05) for (let fy = 0.2; fy <= 0.6; fy += 0.05) {
      total++; if (!near(img.px(img.width * fx, img.height * fy), want, 60)) bad++;
    }
    const ring = ringIsClean(img, want, img.width / (await p.locator('#vp').boundingBox())!.width);
    const lat: number[] = await p.evaluate(() => [...(window as any).__poc.latency].sort((a: number, b: number) => a - b));
    report.push(`seat ${seat}: centre off-colour ${bad}/${total}, edge ring off-colour ${ring.bad}/${ring.total} ` +
                `(${JSON.stringify(ring.edges)}), latency p50 ${lat[lat.length >> 1]} p95 ${lat[Math.floor(lat.length * 0.95)]} ms`);
    expect(bad / total).toBeLessThan(0.1);        // balls/labels move through the centre: allow a little
    expect(lat[lat.length >> 1]).toBeLessThan(1000);
  }
  console.log('[webrtc] ' + report.join('\n[webrtc] '));
  expect([...seats].sort()).toEqual([1, 2, 3, 4]);
  for (const p of viewers) await done(p);
  await src.context().close();
});
