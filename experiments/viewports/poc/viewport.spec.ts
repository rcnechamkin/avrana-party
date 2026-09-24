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

test('four clients: same source, four different crops (pixel check)', async ({ browser }) => {
  test.setTimeout(120_000);                         // 4 live pages + 8 screenshot decodes
  const pages = [];
  for (let i = 0; i < 4; i++) pages.push(await openSeat(await browser.newContext(), '4'));
  const seats = await Promise.all(pages.map(seatOf));
  expect(new Set(seats).size).toBe(4);
  for (const page of pages) {
    const seat = await seatOf(page), img = await viewportImage(page);
    const want = SEAT_RGB[seat - 1];
    // The crop shows ONLY this seat's quadrant: centre and all four edges are its colour
    // (the 2-px inset trims the white dividers and neighbour bleed).
    for (const [fx, fy] of [[0.5, 0.25], [0.03, 0.5], [0.97, 0.5], [0.5, 0.03], [0.5, 0.97]]) {
      const got = img.px(img.width * fx, img.height * fy);
      // allow for the moving white ball / black text: sample a small neighbourhood
      const ok = [0, 3, -3].some(d => near(img.px(img.width * fx + d, img.height * fy + d), want));
      expect(ok, `seat ${seat} at ${fx},${fy} got ${got}`).toBeTruthy();
    }
    // Full view on the same client shows all four quadrants of the identical source frame.
    await page.click('#full');
    await page.waitForTimeout(150);
    const full = await viewportImage(page);
    SEAT_RGB.forEach((rgb, i) => {
      // several points per quadrant; the moving ball or text can cover one of them
      const ox = (i % 2) * 0.5, oy = Math.floor(i / 2) * 0.5;
      const pts = [[0.30, 0.10], [0.70, 0.10], [0.85, 0.50], [0.70, 0.60], [0.45, 0.35]];
      const hits = pts.filter(([u, v]) => near(full.px(full.width * (ox + u / 2), full.height * (oy + v / 2)), rgb)).length;
      expect(hits, `full view quadrant ${i + 1}`).toBeGreaterThanOrEqual(3);
    });
  }
  for (const p of pages) await done(p);
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

test('orientation: a wide 8:3 crop fits by width in landscape and warns in portrait', async ({ browser }) => {
  for (const [w, h, expectHint] of [[844, 390, false], [390, 844, true]] as const) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    const page = await openSeat(ctx, '2h');
    const seat = await seatOf(page);
    if (seat === 1) {                                 // seat 1 of 2h is the top half: aspect 8:3
      const box = (await page.locator('#vp').boundingBox())!;
      expect(box.width / box.height).toBeGreaterThan(2.5);
      expect(box.width / box.height).toBeLessThan(2.8);
      const stage = (await page.locator('#stage').boundingBox())!;
      expect(box.width).toBeLessThanOrEqual(stage.width + 1);   // contain: never overflows
      expect(box.height).toBeLessThanOrEqual(stage.height + 1);
      expect(await page.locator('#hint').isVisible()).toBe(expectHint);
    }
    await done(page);
  }
});

test('crop mode does no per-frame work: the crop is static CSS on the video element', async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await openSeat(ctx, '2v');
  const src = page.locator('#vp > video, #vp > canvas').first();
  const style = await src.getAttribute('style');
  await page.waitForTimeout(500);
  expect(await src.getAttribute('style')).toBe(style);                      // unchanged across frames
  expect(style).toMatch(/width: 2\d\d(\.\d+)?%/);                          // scaled ~2x for a half
  await done(page);
});
