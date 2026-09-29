import { test, expect as baseExpect, devices, type Browser, type BrowserContext, type Page } from '@playwright/test';

/**
 * AVR-129: BLUFF's pregame is the Party's. The Party Host picks BLUFF and every joined phone goes
 * to BLUFF's setup screen; each member chooses Play or Watch in the Party's panel; only the host
 * can start, and only once everyone here has chosen and two players are in. Players are then
 * dealt their own cards; a spectator sees every hand; players never do.
 * Real Party service, real games server, real BLUFF page, real /party/ shell, BLUFF configured as
 * in production (tests/provider/server.py --party-session; reset with ?pregame=1). Laptop only:
 * TESTED here, not a phone measurement.
 */
const BASE = 'http://127.0.0.1:8183';
test.use({ baseURL: BASE });
test.beforeEach(({}, info) => test.skip(info.project.name !== 'android-size', 'runs once, with both phone sizes'));
test.setTimeout(150_000);
const expect = baseExpect.configure({ timeout: 20_000 });

const PHONES = [devices['Pixel 7'], devices['iPhone 13']];
type Phone = { context: BrowserContext; page: Page };
const IN_BLUFF = /\/games\/bluff\/\?avrana=1$/;

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

async function phone(browser: Browser, n = 0, briefed = true): Promise<Phone> {
  const { defaultBrowserType, ...device } = PHONES[n % PHONES.length] as any;
  const context = await browser.newContext({ ...device, baseURL: BASE, serviceWorkers: 'block' });
  if (briefed) await context.addInitScript(() => { try { localStorage.setItem('bluff-briefed', '1'); } catch { /* private */ } });
  const page = await context.newPage();
  await page.addInitScript(record);
  return { context, page };
}

async function joinParty(page: Page, name: string) {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-party', 'on');
  await page.locator('#party-name').fill(name);
  await page.getByRole('button', { name: 'Join the party', exact: true }).click();
  await expect(page.locator('#party-members')).toContainText(`${name} (you)`);
}

const rx = (page: Page) => page.evaluate(() => (window as any).__avr?.rx ?? []);
const welcomeOf = async (page: Page) => (await rx(page)).filter((m: any) => m.type === 'welcome').at(-1);
const lastGame = async (page: Page) => (await rx(page)).filter((m: any) => m.type === 'state' && m.game).at(-1)?.game;
const partyState = (page: Page) => page.evaluate(async () => (await fetch('/party/api/state', { cache: 'no-store' })).json());
const api = (page: Page, path: string, body: any) => page.evaluate(async ({ path, body }) => {
  const r = await fetch('/party/api/' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json() };
}, { path, body });
const panel = (page: Page) => page.locator('#avrana-party-setup');

async function setupTable(browser: Browser, request: any, names: string[]) {
  expect((await request.post('/__harness__/party/reset?pregame=1')).ok()).toBe(true);
  const phones: Phone[] = [];
  for (const [i, name] of names.entries()) {
    const p = await phone(browser, i);
    await joinParty(p.page, name);
    phones.push(p);
  }
  await phones[0].page.locator('[data-id="bluff"]').getByRole('button', { name: 'Start for everyone' }).click();
  for (const p of phones) {
    await expect(p.page).toHaveURL(IN_BLUFF);
    await expect(panel(p.page)).toBeVisible();
  }
  return phones;
}

test('the host picks BLUFF: everyone chooses Play or Watch, only the host starts, spectators see every hand', async ({ browser, request }) => {
  const [ana, ben, cy] = await setupTable(browser, request, ['Ana', 'Ben', 'Cy']);
  // the setup screen, not a table: no socket to the game yet, rules one tap away
  for (const p of [ana, ben, cy]) {
    await expect(p.page.locator('#caption')).toContainText('Round setup');
    await expect(p.page.locator('#play').getByRole('button', { name: 'How to play' })).toBeVisible();
    expect(await welcomeOf(p.page)).toBeUndefined();
  }
  // only the host has Start, and it waits for everyone
  await expect(ben.page.locator('#avrana-party-start')).toHaveCount(0);
  await expect(ben.page.locator('#avrana-party-blocker')).toContainText('Waiting for');
  const start = ana.page.locator('#avrana-party-start');
  await expect(start).toBeDisabled();
  let v = await partyState(ben.page);
  expect(await api(ben.page, 'session/start', { if_version: v.version })).toMatchObject({ status: 403, body: { error: 'not_host' } });

  await ana.page.getByRole('button', { name: 'Play this round' }).click();
  await ben.page.getByRole('button', { name: 'Play this round' }).click();
  v = await partyState(ana.page);
  expect(await api(ana.page, 'session/start', { if_version: v.version })).toMatchObject({ status: 409, body: { error: 'unresolved' } });
  await expect(start).toBeDisabled();
  await expect(ana.page.locator('#avrana-party-blocker')).toContainText('Cy');
  await cy.page.getByRole('button', { name: 'Watch this round' }).click();
  await expect(cy.page.getByRole('button', { name: 'Watch this round' })).toHaveAttribute('aria-pressed', 'true');
  await expect(start).toBeEnabled();
  await start.click();

  // the round: players are dealt, the spectator watches every hand
  await expect.poll(async () => (await lastGame(ana.page))?.me?.cards?.length ?? 0, { timeout: 30_000 }).toBe(2);
  await expect.poll(async () => (await lastGame(ben.page))?.me?.cards?.length ?? 0).toBe(2);
  expect((await welcomeOf(cy.page))).toMatchObject({ watch: true, spectator: true });
  await expect.poll(async () => (await lastGame(cy.page))?.omniscient ?? false).toBe(true);
  const spectatorView = await lastGame(cy.page);
  const anaCards = (await lastGame(ana.page)).me.cards, benCards = (await lastGame(ben.page)).me.cards;
  expect(spectatorView.seats.map((s: any) => s.cards)).toEqual([anaCards, benCards]);
  await expect(cy.page.locator('#bar')).toContainText('you see every hand');
  // players never received anyone else's cards, in any frame
  for (const p of [ana, ben]) {
    for (const m of (await rx(p.page)).filter((x: any) => x.type === 'state' && x.game)) {
      expect(m.game.seats.every((s: any) => !('cards' in s))).toBe(true);
      expect(m.game.omniscient).toBeUndefined();
    }
  }
  await expect(panel(ana.page)).toBeHidden();                     // the setup is over
  // roles change only between rounds
  expect(await api(cy.page, 'session/choice', { choice: 'player' })).toMatchObject({ status: 409, body: { error: 'round_on' } });
  for (const p of [ana, ben, cy]) await p.context.close();
});

test('too few players keeps Start disabled with the reason', async ({ browser, request }) => {
  const [ana, ben] = await setupTable(browser, request, ['Ana', 'Ben']);
  await ana.page.getByRole('button', { name: 'Play this round' }).click();
  await ben.page.getByRole('button', { name: 'Watch this round' }).click();
  await expect(ana.page.locator('#avrana-party-blocker')).toContainText('2 players needed');
  await expect(ana.page.locator('#avrana-party-start')).toBeDisabled();
  const v = await partyState(ana.page);
  expect(await api(ana.page, 'session/start', { if_version: v.version })).toMatchObject({ status: 409, body: { error: 'player_count' } });
  // a change of mind during setup is fine
  await ben.page.getByRole('button', { name: 'Play this round' }).click();
  await expect(ana.page.locator('#avrana-party-start')).toBeEnabled();
  await ana.context.close(); await ben.context.close();
});

test('a first-time player sees the briefing before their Play counts', async ({ browser, request }) => {
  expect((await request.post('/__harness__/party/reset?pregame=1')).ok()).toBe(true);
  const ana = await phone(browser, 0), ben = await phone(browser, 1, false);   // Ben never read it
  await joinParty(ana.page, 'Ana');
  await joinParty(ben.page, 'Ben');
  await ana.page.locator('[data-id="bluff"]').getByRole('button', { name: 'Start for everyone' }).click();
  await expect(ben.page).toHaveURL(IN_BLUFF);
  await expect(ben.page.locator('#briefing')).toBeVisible();          // opened once, on arrival
  await ben.page.keyboard.press('Escape');
  await ben.page.locator('#briefing').evaluate((d: HTMLDialogElement) => d.open && d.close());
  await ben.page.getByRole('button', { name: 'Play this round' }).click();
  await expect(ben.page.locator('#briefing')).toBeVisible();          // Play asks for it first
  expect((await partyState(ben.page)).session.setup.mine).toBeNull();
  await ana.context.close(); await ben.context.close();
});

test('the host can cancel the setup: everyone goes back to Party Home', async ({ browser, request }) => {
  const [ana, ben] = await setupTable(browser, request, ['Ana', 'Ben']);
  const end = ana.page.getByRole('button', { name: 'End for everyone' });
  await end.click();
  await ana.page.getByRole('button', { name: 'Tap again to end it for everyone' }).click();
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(/\/party\/$/);
  expect((await partyState(ben.page)).state).toBe('lobby');
  await ana.context.close(); await ben.context.close();
});
