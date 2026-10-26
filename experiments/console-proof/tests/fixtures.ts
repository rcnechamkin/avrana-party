// Helpers shared by the proof's specs: phones, the game page, and the console in either strategy.
import { test as base, expect, type Browser, type BrowserContext, type Page, type FrameLocator, type Locator } from '@playwright/test';

export const PARTY = 'http://party.cp.test:8370';
export const GAME = 'http://games.cp.test:8371';
export const ADMIN = 'http://127.0.0.1:8370';          // test controls, reached directly (no browser name mapping)

export type Fw = 'vanilla' | 'svelte';
export type Strategy = 'M' | 'R';

export const test = base.extend<{ fw: Fw; strategy: Strategy }>({
  fw: ['vanilla', { option: true }],
  strategy: ['M', { option: true }],
});
export { expect };

export async function admin(page: Page | BrowserContext, path: string, body: object = {}) {
  const req = 'request' in page ? page.request : (page as Page).context().request;
  const res = await req.post(ADMIN + path, { headers: { 'x-cp-test': '1' }, data: body });
  return res.json();
}

export type Phone = { ctx: BrowserContext; page: Page; frames: string[]; sent: string[] };

/** A phone that joined the Party; `seat` seats it in a game. Records every WebSocket frame. */
export async function phone(browser: Browser, name: string, seat: 'rt' | 'turn' | 'none', options: object = {}): Promise<Phone> {
  const u = test.info().project.use as Record<string, unknown>;
  const pick = Object.fromEntries(['viewport', 'deviceScaleFactor', 'isMobile', 'hasTouch', 'proxy', 'userAgent'].filter((k) => k in u).map((k) => [k, u[k]]));
  const ctx = await browser.newContext({ ...pick, serviceWorkers: 'block', ...options } as never);
  const page = await ctx.newPage();
  const frames: string[] = [], sent: string[] = [];
  page.on('websocket', (ws) => { ws.on('framereceived', (f) => frames.push(String(f.payload))); ws.on('framesent', (f) => sent.push(String(f.payload))); });
  await page.goto(`${PARTY}/api/dev-join?name=${name}&seat=${seat}`);
  return { ctx, page, frames, sent };
}

export async function openGame(p: Phone, game: 'rt' | 'turn', fw: Fw, strategy: Strategy) {
  await p.page.goto(`${GAME}/${game}.html?fw=${fw}&s=${strategy}`);
  await waitReady(p.page);
}
export async function waitReady(page: Page) {
  await page.waitForFunction(() => (window as any).__probe && (window as any).__probe.ready && (window as any).__probe.role, null, { timeout: 10_000 });
}
export const probe = (page: Page) => page.evaluate(() => JSON.parse(JSON.stringify((window as any).__probe)));

export const layerFrame = (page: Page): FrameLocator => page.frameLocator('iframe[title="Your Party"]');

/** Where the console's elements are: in the layer frame (M) or the top-level Party page (R). */
export function consoleRoot(page: Page, strategy: Strategy): { locator(sel: string): Locator } {
  return strategy === 'M' ? layerFrame(page) : page;
}

/** Open the console from the game page. M: the drawer over the game. R: the Party console page. */
export async function openConsole(page: Page, strategy: Strategy) {
  await layerFrame(page).locator('#layer-button').click();
  if (strategy === 'R') {
    await page.waitForURL(/party\.cp\.test:8370\/party\/x\/\w+\/\?s=R/);
    await page.locator('body[data-ready="1"]').waitFor();
  }
  await consoleRoot(page, strategy).locator('#back-to-game').waitFor();
}

/** Back to Game. M: the drawer closes over the still-running game. R: the game page loads again. */
export async function backToGame(page: Page, strategy: Strategy) {
  await consoleRoot(page, strategy).locator('#back-to-game').click();
  if (strategy === 'M') await expect(page.locator('iframe[title="Your Party"]')).toHaveAttribute('data-avrana-party-layer', 'button');
  else { await page.waitForURL(/(games\.cp\.test:8371|\/g)\/(rt|turn)\.html/); await waitReady(page); }
}

export const stats = (p: Page) => admin(p, '/test/stats');
