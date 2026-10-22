import { test, expect as baseExpect, devices, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { place, startForEveryone } from '../lib/frame';

/**
 * The Party layer (AVR-292) over REAL BLUFF: the real Party service, the real games server, the
 * real BLUFF page, which opts in itself (avrana-party-games `AVRANA_GAMES_REPO` at the paired
 * change). The Party suites use stub game pages; this is the check that the two repositories fit.
 *
 * What it covers: the button mounts on a live round and after a reload; the drawer shows people,
 * the Host, and the Party chat (and an unread count while closed); BLUFF stays quiet while the
 * drawer is open and catches up when it closes; BLUFF's own dialogs do not cover the button
 * (their focus and Escape guarantees hold); the Host's End (confirmed) takes everyone home and
 * removes the layer; a lost connection is said and recovers.
 * Laptop Chromium at phone size: TESTED here, not a phone measurement. Safe areas, touch drag,
 * screen readers and Safari are in docs/runbooks/party-layer-device-validation.md (Tier 3).
 */
const BASE = 'http://127.0.0.1:8183';
test.use({ baseURL: BASE });
test.beforeEach(({}, info) => test.skip(info.project.name !== 'android-size', 'runs once, phone-sized'));
test.setTimeout(180_000);
const expect = baseExpect.configure({ timeout: 20_000 });

const PHONE = devices['iPhone 13'];
type Phone = { context: BrowserContext; page: Page };
const IN_BLUFF = /\/games\/bluff\/\?avrana=1$/;
const FRAME = 'iframe[data-avrana-party-layer]';

function record() {
  const Native = window.WebSocket;
  const log = { rx: [] as any[] };
  (window as any).__avr = log;
  class Recorded extends Native {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      this.addEventListener('message', (e) => { try { log.rx.push(JSON.parse(e.data)); } catch {} });
    }
  }
  (window as any).WebSocket = Recorded;
}

async function phone(browser: Browser, base = BASE): Promise<Phone> {
  const { defaultBrowserType, ...device } = PHONE as any;
  const context = await browser.newContext({ ...device, baseURL: base, serviceWorkers: 'block' });
  await context.addInitScript(() => { try { localStorage.setItem('bluff-briefed', '1'); } catch { /* private */ } });
  const page = await context.newPage();
  await page.addInitScript(record);
  return { context, page };
}

async function arrive(page: Page, name: string) {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-party', 'on');
  await place(page, 'me');
  await page.locator('#player-chip').click();
  await page.locator('#profile-name').fill(name);
  await page.getByRole('button', { name: 'Save profile' }).click();
  await expect(page.locator('#party-members')).toContainText(`${name} (you)`);
}

const rx = (page: Page) => page.evaluate(() => (window as any).__avr?.rx ?? []);
const lastGame = async (page: Page) => (await rx(page)).filter((m: any) => m.type === 'state' && m.game).at(-1)?.game;
const layer = (page: Page) => page.frameLocator(FRAME);

async function round(browser: Browser, request: any) {
  expect((await request.post('/__harness__/party/reset?pregame=1')).ok()).toBe(true);
  const ana = await phone(browser), ben = await phone(browser);
  await arrive(ana.page, 'Ana');
  await arrive(ben.page, 'Ben');
  await startForEveryone(ana.page, 'bluff');
  for (const p of [ana, ben]) { await expect(p.page.locator('#scene')).toBeVisible(); await p.page.locator('#choose-play').click(); }
  await ana.page.locator('#scene-start').click();
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(IN_BLUFF, { timeout: 30_000 });
  await expect.poll(async () => (await lastGame(ana.page))?.me?.cards?.length ?? 0, { timeout: 30_000 }).toBe(2);
  for (const p of [ana, ben]) await expect(layer(p.page).locator('#layer-button')).toBeVisible();
  return { ana, ben };
}

async function openDrawer(page: Page) {
  await layer(page).locator('#layer-button').click();
  await expect(layer(page).locator('#layer-sheet')).toBeVisible();
  await expect.poll(() => page.evaluate(() => (window as any).AvranaIntegration.partyLayerOpen)).toBe(true);
}
async function closeDrawer(page: Page) {
  await layer(page).locator('#layer-close').click();
  await expect(layer(page).locator('#layer-sheet')).toBeHidden();
  await expect.poll(() => page.evaluate(() => (window as any).AvranaIntegration.partyLayerOpen)).toBe(false);
}
const live = (page: Page) => page.locator('#live').innerText();

test('the button mounts on a live BLUFF round, survives a reload, and the drawer names the people and the Host', async ({ browser, request }, info) => {
  const { ana, ben } = await round(browser, request);
  await ben.page.screenshot({ path: info.outputPath('bluff-closed-390x844.png') });
  await openDrawer(ben.page);
  const l = layer(ben.page);
  await expect(l.locator('#layer-people-list li')).toHaveCount(2);
  await expect(l.locator('#layer-people-list li', { hasText: 'Ana' })).toContainText('Host');
  await expect(l.locator('#layer-host')).toBeHidden();                       // Ben is not the Host
  await ben.page.screenshot({ path: info.outputPath('bluff-open-390x844.png') });
  await closeDrawer(ben.page);
  await expect(layer(ben.page).locator('#layer-button')).toBeFocused();       // focus goes back to where it was
  await ben.page.reload();
  await expect(ben.page).toHaveURL(IN_BLUFF);
  await expect(layer(ben.page).locator('#layer-button')).toBeVisible();
  await expect.poll(async () => (await lastGame(ben.page))?.me?.cards?.length ?? 0).toBe(2);   // still in their seat
  for (const p of [ana, ben]) await p.context.close();
});

test('chat: sent in the drawer, an unread count on the other phone, read there', async ({ browser, request }) => {
  const { ana, ben } = await round(browser, request);
  await openDrawer(ben.page);
  await layer(ben.page).locator('#layer-tab-chat').click();
  await layer(ben.page).locator('#chat-text').fill('good luck, Ana');
  await layer(ben.page).locator('#chat-form button[type="submit"]').click();
  await expect(layer(ben.page).locator('#chat-messages')).toContainText('good luck, Ana');
  await expect(layer(ana.page).locator('#layer-button')).toHaveAccessibleName(/1 new message/);
  await openDrawer(ana.page);
  await layer(ana.page).locator('#layer-tab-chat').click();
  await expect(layer(ana.page).locator('#chat-messages')).toContainText('good luck, Ana');
  await expect(layer(ana.page).locator('#chat-messages')).toContainText('Ben');
  for (const p of [ana, ben]) await p.context.close();
});

test('BLUFF waits while the Party is open: no announcements, Escape ignored, and it catches up when closed', async ({ browser, request }) => {
  const { ana, ben } = await round(browser, request);
  const income = (p: Phone) => p.page.getByRole('button', { name: /Income/ });
  // whoever has the turn acts; the other phone watches with the Party open
  let mover = ana, watcher = ben;
  await expect.poll(async () => {
    for (const [m, w] of [[ana, ben], [ben, ana]] as const) {
      if (await income(m).isVisible() && await income(m).isEnabled()) { mover = m; watcher = w; return true; }
    }
    return false;
  }, { timeout: 30_000, intervals: [300] }).toBe(true);
  const before = await live(watcher.page);
  const seen = (await rx(watcher.page)).length;
  await openDrawer(watcher.page);
  await income(mover).click();
  await expect.poll(async () => (await rx(watcher.page)).length, { timeout: 20_000 }).toBeGreaterThan(seen);   // the move reached it
  expect(await live(watcher.page)).toBe(before);                          // ...and nothing was said while the Party was open
  await closeDrawer(watcher.page);
  await expect.poll(() => live(watcher.page), { timeout: 10_000 }).not.toBe(before);   // caught up on close
  for (const p of [ana, ben]) await p.context.close();
});

test('BLUFF\'s own dialogs do not cover the Party button, and each keeps its focus and Escape behaviour', async ({ browser, request }) => {
  const { ana, ben } = await round(browser, request);
  const page = ben.page;
  await page.locator('#rules').click();                                    // the rules sheet
  await expect(page.locator('#briefing')).toBeVisible();
  const state = await page.evaluate(() => ({
    onTable: !!document.querySelector('#bar')!.closest('[inert]'),
    atPartyButton: (() => {
      const f = document.querySelector('iframe[data-avrana-party-layer]') as HTMLElement, r = f.getBoundingClientRect();
      return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === f;
    })(),
    modalAria: document.getElementById('briefing')!.hasAttribute('aria-modal'),
  }));
  expect(state).toEqual({ onTable: true, atPartyButton: true, modalAria: false });   // table inert, Party reachable
  await openDrawer(page);                                                   // the Party opens over the open sheet
  await closeDrawer(page);
  await expect(page.locator('#briefing')).toBeVisible();                    // the sheet is as it was
  await expect(page.locator('#briefing').locator(':focus')).toHaveCount(1);   // and focus is back inside it, so its Escape works
  await page.keyboard.press('Escape');                                      // the sheet's own Escape
  await expect(page.locator('#briefing')).toBeHidden();
  await expect(page.locator('#rules')).toBeFocused();
  expect(await page.evaluate(() => !!document.querySelector('#bar')!.closest('[inert]'))).toBe(false);
  for (const p of [ana, ben]) await p.context.close();
});

test('the Host: End is in the drawer and asks first; a follower has none; End takes everyone home and removes the layer', async ({ browser, request }) => {
  const { ana, ben } = await round(browser, request);
  await openDrawer(ana.page);
  const l = layer(ana.page);
  await expect(l.locator('#layer-host')).toBeVisible();
  await l.locator('#layer-actions [data-action="end"]').click();
  await expect(l.locator('#layer-confirm')).toBeVisible();
  await l.locator('#layer-no').click();
  await expect(ana.page).toHaveURL(IN_BLUFF);                               // declined: nothing happened
  await l.locator('#layer-actions [data-action="end"]').click();
  await l.locator('#layer-yes').click();
  for (const p of [ana, ben]) {
    await expect(p.page).toHaveURL(/\/party\/(#.*)?$/, { timeout: 30_000 });
    await expect(p.page.locator(FRAME)).toHaveCount(0);
  }
  for (const p of [ana, ben]) await p.context.close();
});

test('a lost connection is said in the drawer and recovers', async ({ browser, request }) => {
  const { ana, ben } = await round(browser, request);
  await openDrawer(ben.page);
  await ben.context.setOffline(true);
  await expect(layer(ben.page).locator('#layer-link')).not.toBeEmpty({ timeout: 30_000 });
  await ben.context.setOffline(false);
  await expect(layer(ben.page).locator('#layer-link')).toBeEmpty({ timeout: 40_000 });
  await expect(layer(ben.page).locator('#layer-people-list li')).toHaveCount(2);
  for (const p of [ana, ben]) await p.context.close();
});

test('EXPO: the button mounts on the real page, the drawer names the people, a reload keeps it', async ({ browser, playwright }) => {
  const EXPO_BASE = 'http://127.0.0.1:8186';      // the harness instance that runs EXPO as a real Party game
  const api = await playwright.request.newContext({ baseURL: EXPO_BASE });
  expect((await api.post('/__harness__/party/reset?pregame=1')).ok()).toBe(true);
  const ana = await phone(browser, EXPO_BASE), ben = await phone(browser, EXPO_BASE);
  await arrive(ana.page, 'Ana');
  await arrive(ben.page, 'Ben');
  const v = await ana.page.evaluate(async () => (await fetch('/party/api/state', { cache: 'no-store' })).json());
  const launched = await ana.page.evaluate(async (version) => {
    const r = await fetch('/party/api/session/launch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ game: 'expo', if_version: version }) });
    return r.status;
  }, v.version);
  expect(launched).toBe(200);                                              // the Host's launch, as the Library's button does
  const IN_EXPO = /\/games\/expo\/\?avrana=1/;
  for (const p of [ana, ben]) {
    await expect(p.page).toHaveURL(IN_EXPO, { timeout: 30_000 });
    await expect(layer(p.page).locator('#layer-button')).toBeVisible({ timeout: 30_000 });
  }
  const page = ben.page;
  const hit = await page.evaluate(() => {
    const f = document.querySelector('iframe[data-avrana-party-layer]') as HTMLElement, r = f.getBoundingClientRect();
    return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === f;
  });
  expect(hit).toBe(true);                                                  // nothing of EXPO's covers the Party button
  await openDrawer(page);
  await expect(layer(page).locator('#layer-people-list li')).toHaveCount(2);
  await expect(layer(page).locator('#layer-people-list li', { hasText: 'Ana' })).toContainText('Host');
  await closeDrawer(page);
  await page.reload();                                                     // a reload keeps the seat and the button
  await expect(layer(page).locator('#layer-button')).toBeVisible({ timeout: 30_000 });
  for (const p of [ana, ben]) await p.context.close();
});
