// The join card (AVR-76) as Chromium draws it: each QR code is rasterized by the browser and decoded
// in the page with jsQR, and the card fits a phone screen without sideways scrolling. Synthetic only: whether
// a real iPhone or Android camera reads a printed card is the owner's check (docs/runbooks/join-card.md).
import { test, expect } from '@playwright/test';
import { join } from 'node:path';
import { renderCard } from '../../tools/join-card/card.mjs';
import { FULL_MODE_URL, wifiPayload } from '../../tools/join-card/payloads.mjs';

const JSQR = join(__dirname, '../../node_modules/jsqr/dist/jsQR.js');
const WIFI = { ssid: 'Avrana Party', password: 'test-only;pass:word' };

test('the browser-drawn card decodes to the Wi-Fi string and the Party link, with no request', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', (r) => requests.push(r.url()));
  await page.setContent(renderCard({ ...WIFI, generatedOn: '2026-10-19' }));
  await page.addScriptTag({ path: JSQR });          // inlined from node_modules; not a request
  const decoded = await page.locator('.qr svg').evaluateAll(async (svgs) => Promise.all(svgs.map(async (svg) => {
    const img = new Image();
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg.outerHTML);
    await img.decode();
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 300;
    const ctx = canvas.getContext('2d')!;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(img, 0, 0, 300, 300);
    return (window as any).jsQR(ctx.getImageData(0, 0, 300, 300).data, 300, 300)?.data;
  })));
  expect(decoded).toEqual([wifiPayload(WIFI), FULL_MODE_URL]);
  expect(requests).toEqual([]);

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  for (const box of [await page.locator('.qr').first().boundingBox(), await page.locator('.qr').last().boundingBox()]) {
    expect(box!.width).toBeGreaterThanOrEqual(150);
  }
});
