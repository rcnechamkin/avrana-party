import { test, expect as baseExpect, devices, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { startForEveryone } from '../lib/frame';

/**
 * ADR 0013 / AVR-303 (Tier 2): Party Home takes every member's phone to the game origin for the
 * round, and the end of the round brings every phone back. Party Core registers the game origin
 * (tests/provider/server.py --party-session --game-origin: game_origins); the shell learns it from
 * GET /party/api/bridge and from nothing else. Same harness and honest limits as
 * game-origin.spec.ts: plain HTTP on two host names of one site, TESTED on a laptop; HTTPS, the
 * `__Host-` cookie, nginx and a real iPhone are Tier 3 and the owner's.
 */
const PORT = 8184;
const PARTY = `http://party.avrana.test:${PORT}`;
const GAMES = `http://games.avrana.test:${PORT}`;
const LOOPBACK = `http://127.0.0.1:${PORT}`;
test.beforeEach(({}, info) => test.skip(info.project.name !== 'android-size', 'runs once, with both phone sizes'));
test.setTimeout(150_000);
const expect = baseExpect.configure({ timeout: 20_000 });

const PHONES = [devices['Pixel 7'], devices['iPhone 13']];
type Phone = { context: BrowserContext; page: Page };
const IN_GAME = `${GAMES}/games/bluff/?avrana=1`;
const AT_HOME = new RegExp(`^${PARTY.replace(/[.]/g, '\\.')}/party/(#[a-z0-9/-]*)?$`);

async function phone(browser: Browser, n: number): Promise<Phone> {
  const { defaultBrowserType, ...device } = PHONES[n % PHONES.length] as any;
  const context = await browser.newContext({ ...device, baseURL: PARTY, serviceWorkers: 'block' });
  // These phones have read BLUFF's first-play briefing: it is another suite's business.
  await context.addInitScript(() => { try { localStorage.setItem('bluff-briefed', '1'); } catch { /* private */ } });
  return { context, page: await context.newPage() };
}

async function joinParty(page: Page, name: string) {
  await page.goto(`${PARTY}/party/`);
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('html')).toHaveAttribute('data-party', 'on');
  await page.locator('#nav a[data-go="me"]').click();
  await page.locator('#player-chip').click();
  await page.locator('#profile-name').fill(name);
  await page.getByRole('button', { name: 'Save profile' }).click();
  await expect(page.locator('#party-members')).toContainText(`${name} (you)`);
}

test('the host starts a round: two phones on Party Home go to the game origin; a phone opening Party Home mid-round follows; the end brings everyone back', async ({ browser, request }) => {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 0), ben = await phone(browser, 1);
  await joinParty(ana.page, 'Ana');
  await joinParty(ben.page, 'Ben');

  await startForEveryone(ana.page, 'bluff');
  for (const p of [ana, ben]) {
    await expect(p.page).toHaveURL(IN_GAME);                      // the registered origin + the entry path
    await expect(p.page.locator('iframe[title="Avrana Party"]')).toHaveAttribute('src', `${PARTY}/party/bridge.html`);
  }

  // A member who opens Party Home during the round is taken to the same address.
  const again = await ben.context.newPage();
  await again.goto(`${PARTY}/party/`);
  await expect(again).toHaveURL(IN_GAME);
  await again.close();

  // The host ends it from the game; both phones return to Party Home on the Party origin, and stay.
  await ana.page.locator('#party-end').click();
  await ana.page.locator('#confirm-yes').click();
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(AT_HOME);
  await ana.page.waitForTimeout(1500);                            // no loop back out
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(AT_HOME);
  const state = await (await ana.page.goto(`${PARTY}/party/api/state`))!.json();
  expect(state.location.at).toBe('home');
  await ana.context.close(); await ben.context.close();
});

// The Host's way out, Party Core's own (POST /party/api/lobby): the Host's phone, back on Party Home
// for a round it was already taken to (a new tab, a reload: the game page may be broken), is not
// sent straight back. It may return to the game, or bring everyone back to the Party.
test('the Host, back on Party Home mid-round, can return to the game or bring everyone back, and a reload keeps the choice', async ({ browser, request }) => {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 0), ben = await phone(browser, 1);
  await joinParty(ana.page, 'Ana');
  await joinParty(ben.page, 'Ben');
  await startForEveryone(ana.page, 'bluff');
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(IN_GAME);

  const home = await ana.context.newPage();                      // the Host opens Party Home again
  await home.goto(`${PARTY}/party/`);
  await expect(home.locator('#going-host')).toBeVisible();
  await expect(home.locator('#going-text')).toHaveText('BLUFF is on.');
  await expect(home.locator('#going-back')).toBeHidden();         // this phone's own way back is not the Host's choice
  await home.reload();                                            // and a reload (Safari's refresh) keeps it
  await expect(home.locator('#going-host')).toBeVisible();
  await expect(home).toHaveURL(AT_HOME);

  await home.getByRole('button', { name: 'Return to BLUFF' }).click();
  await expect(home).toHaveURL(IN_GAME);
  await home.goto(`${PARTY}/party/`);
  await home.getByRole('button', { name: 'Bring everyone back to the Party' }).click();
  await expect(home.locator('#going-confirm')).toBeVisible();     // a round is on: it ends for everyone
  await home.getByRole('button', { name: 'Keep playing' }).click();
  await expect(home.locator('#going-choices')).toBeVisible();
  expect((await home.evaluate(() => fetch('/party/api/state').then((r) => r.json()))).location.at).toBe('game');
  await home.getByRole('button', { name: 'Bring everyone back to the Party' }).click();
  await home.getByRole('button', { name: 'End the round' }).click();
  for (const p of [ana.page, ben.page, home]) await expect(p).toHaveURL(AT_HOME);
  await expect(home.locator('#going')).toBeHidden();
  await home.waitForTimeout(1500);                                // nobody is taken back out
  for (const p of [ana.page, ben.page, home]) await expect(p).toHaveURL(AT_HOME);
  expect((await home.evaluate(() => fetch('/party/api/state').then((r) => r.json()))).location.at).toBe('home');

  // the next round is a new one: the Host's phone follows it like everyone's
  await startForEveryone(home, 'bluff');
  for (const p of [ben.page, home]) await expect(p).toHaveURL(IN_GAME);
  await ana.context.close(); await ben.context.close();
});

/**
 * AVR-339: a navigation to the game origin that never completes (seen once in about 13 WebKit runs in CI,
 * ~22 s of silence and then a browser error). The going screen tries once more and then gives the phone a way on
 * and a way back. Simulated here by the harness's own game origin (tests/provider/server.py
 * /__harness__/hang-game), which accepts the connection for BLUFF's page and holds it. The waits are real (8 s
 * each, lib/going-watchdog.js); the page's own timers are left alone because Party polling runs on them.
 * Whether the hang seen on WebKit is a WebKit or a runner fault is not settled by this. Both projects below are
 * Chromium (`iphone-size` is Chromium at an iPhone's size, and these tests run on `android-size` only): there is no
 * WebKit and no iPhone evidence in this file.
 */
async function hangGameOrigin(p: Phone) {
  const hang = `${LOOPBACK}/__harness__/hang-game`;
  expect((await p.page.request.post(`${hang}?on=1`)).ok()).toBe(true);
  return {
    seen: async (): Promise<number> => (await (await p.page.request.get(hang)).json()).seen,
    /** held requests whose client gave up: the browser cancelled that navigation */
    dropped: async (): Promise<number> => (await (await p.page.request.get(hang)).json()).dropped,
    release: async () => { expect((await p.page.request.post(`${hang}?on=0`)).ok()).toBe(true); },
  };
}

// While a top-level navigation is pending, the page that is still on screen cannot be read from the test:
// Playwright holds every locator and page.evaluate call ("waiting for <url> navigation to finish"), and so did
// Runtime.evaluate over the DevTools protocol (CI runs 38338301123, 38339151420 and 38340019296: reads queued
// during the hang came back only at the instant the page's own retry replaced the navigation, and not after).
// What a hung navigation looks like from OUTSIDE is the server's count of requests, which is therefore what the
// first half of each test asserts (one retry about 8 s after the first request, then nothing more). The page is
// read only after the person's "Stop" (Page.stopLoading cancels the pending navigation and leaves the document
// as it is), through the DevTools protocol. Chromium only, like the rest of this suite.
type Spot = { x: number; y: number; w: number; h: number };
async function eyes(p: Phone) {
  const cdp = await p.context.newCDPSession(p.page);
  const run = async (expression: string) => {
    const { result, exceptionDetails } = await cdp.send('Runtime.evaluate', { expression, returnByValue: true });
    if (exceptionDetails) throw new Error(exceptionDetails.text);
    return result.value;
  };
  return {
    stop: () => cdp.send('Page.stopLoading'),
    /** Where the going screen's two buttons are, measured BEFORE the hang (the page cannot be read during it): the
     * screen is shown for a moment exactly as it is when the way out is offered, then put back as it was. */
    layout: () => run(`(() => {
      const el = (id) => document.getElementById(id), root = document.documentElement;
      const ids = ['main', 'going', 'going-stuck', 'going-wait'], was = ids.map((id) => el(id).hidden);
      const text = el('going-text').textContent, screen = root.dataset.screen;
      el('main').hidden = true; el('going').hidden = false; el('going-stuck').hidden = false; el('going-wait').hidden = true;
      el('going-text').textContent = 'Can’t reach BLUFF.'; root.dataset.screen = 'going';
      const at = (id) => { const r = el(id).getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height }; };
      const out = { retry: at('going-retry'), back: at('going-back') };
      ids.forEach((id, i) => { el(id).hidden = was[i]; });
      el('going-text').textContent = text; root.dataset.screen = screen;
      return out;
    })()`) as Promise<{ retry: Spot; back: Spot }>,
    /** A thumb: real input at a point, which the page receives without anyone reading it. */
    tap: async ({ x, y }: Spot) => {
      await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
      await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
      await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
    },
    going: () => run(`(() => { const el = (id) => document.getElementById(id);
      return { screen: document.documentElement.dataset.screen, stuck: !el('going-stuck').hidden, text: el('going-text').textContent }; })()`) as Promise<{ screen: string; stuck: boolean; text: string }>,
    press: (id: string) => run(`document.getElementById(${JSON.stringify(id)}).click()`),
  };
}

/** Start BLUFF for the party against a game origin that never answers, and wait past the way out (16 s) with the
 * navigation still pending. Where the buttons are is measured first, while the page can still be read. */
async function hungWait(p: Phone) {
  const game = await hangGameOrigin(p);
  const see = await eyes(p);
  const spots = await see.layout();
  expect(spots.retry.w, 'the buttons were measured on a laid-out screen').toBeGreaterThan(40);
  expect(spots.back.y).toBeGreaterThan(spots.retry.y);
  await startForEveryone(p.page, 'bluff');
  await expect.poll(game.seen, { timeout: 15_000, intervals: [250] }).toBeGreaterThanOrEqual(1);
  const first = Date.now();
  await expect.poll(game.seen, { timeout: 20_000, intervals: [250] }).toBeGreaterThanOrEqual(2);
  const gap = Date.now() - first;
  expect(gap, 'the retry comes after a bounded wait, not at once and not never').toBeGreaterThan(6000);
  expect(gap).toBeLessThan(14_000);
  await p.page.waitForTimeout(Math.max(0, 24_000 - (Date.now() - first)));       // past the way out (16 s), with room
  expect(await game.seen(), 'one retry and nothing more: it cannot loop').toBe(2);
  return { game, see, spots };
}

/** The same, then the person presses Stop: the pending navigation is cancelled and the page is the old one. */
async function hungStart(p: Phone) {
  const { game, see, spots } = await hungWait(p);
  await see.stop();
  await expect.poll(() => see.going().then((s) => s.stuck), { timeout: 10_000 }).toBe(true);
  expect((await see.going()).text).toContain('Can’t reach');
  return { game, see, spots };
}

// never leave the shared game origin hanging, whatever the test did (its page may be closed by now)
test.afterEach(async ({ request }) => { await request.post(`${LOOPBACK}/__harness__/hang-game?on=0`).catch(() => {}); });

test('a game page that never answers: one retry, then Try again and Back to Party are offered; Try again gets there', async ({ browser, request }) => {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 0);
  await joinParty(ana.page, 'Ana');
  const { game, see } = await hungStart(ana);
  await game.release();                                                    // the game origin answers again
  await see.press('going-retry');
  await expect(ana.page).toHaveURL(IN_GAME);
  await ana.context.close();
});

test('a game page that never answers: Back to Party stays on Party Home, with no further navigation', async ({ browser, request }) => {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 1);
  await joinParty(ana.page, 'Ana');
  const { game, see } = await hungStart(ana);
  await see.press('going-back');
  await expect.poll(() => see.going().then((s) => s.screen), { timeout: 10_000 }).toBe('main');
  expect((await see.going()).stuck).toBe(false);
  const requests = await game.seen();
  await game.release();                                                       // even if the game origin answers now, nothing goes back out
  await ana.page.waitForTimeout(3000);
  expect(await game.seen()).toBe(requests);
  await expect(ana.page).toHaveURL(AT_HOME);
  await ana.context.close();
});

// Input does not wait for the page: a thumb on the buttons while the navigation is STILL pending (nothing stops it).
test('a game page that never answers: Try again, tapped while the navigation is still pending, goes again at once and gets there', async ({ browser, request }) => {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 0);
  await joinParty(ana.page, 'Ana');
  const { game, see, spots } = await hungWait(ana);
  await see.tap(spots.retry);
  // the automatic retry is limited to one and has happened: a third request now is the person's own
  await expect.poll(game.seen, { timeout: 5000, intervals: [100] }).toBe(3);
  await game.release();                                                    // the game origin answers; the held request is served
  await expect(ana.page).toHaveURL(IN_GAME);
  await ana.context.close();
});

test('a game page that never answers: Back to Party, tapped while the navigation is still pending, cancels it for good', async ({ browser, request }) => {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 1);
  await joinParty(ana.page, 'Ana');
  const { game, see, spots } = await hungWait(ana);
  const before = await game.dropped();                                     // the first request, cancelled by the retry
  await see.tap(spots.back);
  // window.stop(): the pending navigation is cancelled, so its connection is closed, while the game origin still hangs
  await expect.poll(game.dropped, { timeout: 5000, intervals: [100] }).toBe(before + 1);
  await game.release();                                                    // a navigation that was still pending would be answered now, and arrive
  await ana.page.waitForTimeout(3000);
  expect(await game.seen(), 'no further request for the game').toBe(2);
  await expect(ana.page).toHaveURL(AT_HOME);
  await expect.poll(() => see.going().then((s) => s.screen), { timeout: 10_000 }).toBe('main');
  expect((await see.going()).stuck).toBe(false);
  await ana.context.close();
});
