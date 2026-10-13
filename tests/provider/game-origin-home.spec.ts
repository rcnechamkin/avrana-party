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
  await page.locator('#nav a[data-go="party"]').click();
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

/**
 * AVR-339: a navigation to the game origin that never completes (seen once in about 13 WebKit runs in CI,
 * ~22 s of silence and then a browser error). The going screen tries once more and then gives the phone a way on
 * and a way back. Simulated here by a game origin that accepts the request and never answers; the waits are
 * real (8 s each, lib/going-watchdog.js). Whether the hang is a WebKit or a runner fault is not settled by this.
 */
// The waits are real: 2 x 8 s of visible time before the way out, so the expectations below allow 45 s
// (a loaded runner); the page's own timers are left alone because Party polling runs on them.
async function hangGameOrigin(p: Phone) {
  const seen = { requests: 0, hang: true };
  await p.context.route((url) => url.origin === GAMES && url.pathname.startsWith('/games/bluff/'), (route) => {
    seen.requests += 1;
    if (!seen.hang) return route.continue();
    // neither fulfilled, continued nor aborted: the request is simply never answered
  });
  return seen;
}

// While a top-level navigation is pending Playwright holds every selector-based call ("waiting for <url>
// navigation to finish"): locators, expect(locator) and locator.click() cannot look at the old page until it
// commits, which a hung navigation never does. So the page is read and pressed with page.evaluate, which runs
// in the document that is still there; this is also what a person's eyes and thumb are doing.
const going = (page: Page) => page.evaluate(() => {
  const el = (id: string) => document.getElementById(id) as HTMLElement;
  return { screen: document.documentElement.dataset.screen, visible: document.visibilityState,
    stuck: !el('going-stuck').hidden, text: el('going-text').textContent };
});
const press = (page: Page, id: string) => page.evaluate((i) => (document.getElementById(i) as HTMLElement).click(), id);
/** TEMPORARY diagnostics (AVR-339 CI iteration): the going screen once a second, in the job log. */
function timeline(p: Phone, game: { requests: number }, label: string) {
  const t0 = Date.now();
  const timer = setInterval(async () => {
    const s = await going(p.page).catch((e) => `evaluate failed: ${String(e).slice(0, 80)}`);
    console.log(`TL ${label} +${Math.round((Date.now() - t0) / 1000)}s requests=${game.requests} ${JSON.stringify(s)}`);
  }, 2000);
  return () => clearInterval(timer);
}

test('a game page that never answers: the going screen retries once, then offers Try again and Back to Party; Try again gets there', async ({ browser, request }) => {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 0);
  await joinParty(ana.page, 'Ana');
  const game = await hangGameOrigin(ana);
  const stop = timeline(ana, game, 'try-again');
  await startForEveryone(ana.page, 'bluff');
  await expect.poll(() => going(ana.page).then((s) => s.screen)).toBe('going');
  expect((await going(ana.page)).stuck).toBe(false);                       // not at once: the wait is bounded, not nervous
  await expect.poll(() => going(ana.page).then((s) => s.stuck), { timeout: 45_000 }).toBe(true);
  stop();
  expect(game.requests).toBeGreaterThanOrEqual(2);                           // the first navigation and its retry
  expect((await going(ana.page)).text).toContain('Can’t reach');
  game.hang = false;                                                       // the game origin answers again
  await press(ana.page, 'going-retry');
  await expect(ana.page).toHaveURL(IN_GAME);
  await ana.context.close();
});

test('a game page that never answers: Back to Party stops the pending navigation and stays on Party Home', async ({ browser, request }) => {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 1);
  await joinParty(ana.page, 'Ana');
  const game = await hangGameOrigin(ana);
  const stop = timeline(ana, game, 'back');
  await startForEveryone(ana.page, 'bluff');
  await expect.poll(() => going(ana.page).then((s) => s.stuck), { timeout: 45_000 }).toBe(true);
  stop();
  await press(ana.page, 'going-back');
  await expect.poll(() => going(ana.page).then((s) => s.screen)).toBe('main');
  expect((await going(ana.page)).stuck).toBe(false);
  const requests = game.requests;
  game.hang = false;                                                       // even if the game origin answers now, the stopped navigation does not come back
  await ana.page.waitForTimeout(3000);
  expect(game.requests).toBe(requests);
  await expect(ana.page).toHaveURL(AT_HOME);
  await ana.context.close();
});
