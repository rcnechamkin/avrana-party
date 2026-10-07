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
