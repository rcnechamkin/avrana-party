import { test, expect as baseExpect, devices, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { openGame, place, startForEveryone } from '../lib/frame';

/**
 * Party Home on Party Core, the console model (ADR 0011; AVR-20/127/128 before it), with a game
 * that launches directly (the harness's BLUFF has no pregame here; party-pregame.spec.ts runs the
 * production setup). One party, one place: a phone with a profile is in it, the Party Host moves
 * everyone, and a member's page is always where the party is, however it was opened. Real Party
 * service, real games server, real BLUFF page, real /party/ shell (tests/provider/server.py
 * --party-session). Laptop only: TESTED here, not a phone measurement.
 */
const BASE = 'http://127.0.0.1:8183';
const NO_PARTY = 'http://127.0.0.1:8182';          // the same shell with no Party Core behind it
test.use({ baseURL: BASE });
test.beforeEach(({}, info) => test.skip(info.project.name !== 'android-size', 'runs once, with both phone sizes'));
test.setTimeout(150_000);
const expect = baseExpect.configure({ timeout: 20_000 });

const PHONES = [devices['Pixel 7'], devices['iPhone 13']];
type Phone = { context: BrowserContext; page: Page };

// What the page's own code receives on its WebSockets (hubnet.js): welcomes carry the pid.
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

async function phone(browser: Browser, n = 0): Promise<Phone> {
  const { defaultBrowserType, ...device } = PHONES[n % PHONES.length] as any;
  const context = await browser.newContext({ ...device, baseURL: BASE, serviceWorkers: 'block' });
  // These phones have already read BLUFF's first-play briefing (AVR-90; games/bluff/web/briefing.js
  // KEY/VERSION), so it doesn't cover the lobby; the briefing has its own tests in the games repo.
  await context.addInitScript(() => { try { localStorage.setItem('bluff-briefed', '1'); } catch { /* private */ } });
  const page = await context.newPage();
  await page.addInitScript(record);
  return { context, page };
}

async function welcome(page: Page) {
  await expect.poll(() => page.evaluate(() => (window as any).__avr?.rx.filter((m: any) => m.type === 'welcome').length ?? 0))
    .toBeGreaterThan(0);
  return page.evaluate(() => (window as any).__avr.rx.filter((m: any) => m.type === 'welcome').at(-1));
}

async function home(page: Page) {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('html')).toHaveAttribute('data-party', 'on');
}

/** The only gate is a profile: saving it is being in the party (there is no Join). */
async function joinParty(page: Page, name: string) {
  await home(page);
  await place(page, 'party');
  await page.locator('#player-chip').click();
  await page.locator('#profile-name').fill(name);
  await page.getByRole('button', { name: 'Save profile' }).click();
  await expect(page.locator('#party-members')).toContainText(`${name} (you)`);
}

const IN_BLUFF = /\/games\/bluff\/\?avrana=1$/;
const AT_HOME = /\/party\/(#(home|party|library|system|game\/[a-z0-9-]+))?$/;   // the shell: one of its places, or a game's page
const partyState = (page: Page) => page.evaluate(async () => (await fetch('/party/api/state', { cache: 'no-store' })).json());
const store = (page: Page, key: string) => page.evaluate((k) => sessionStorage.getItem(k), key);
// For expect.poll: the page under watch may be mid-navigation (the move being waited for), which
// destroys the evaluate context; that is "not yet", not a failure.
const storeDuringMoves = (page: Page, key: string) => store(page, key).catch(() => null);
const api = (page: Page, path: string, body: any) => page.evaluate(async ({ path, body }) => {
  const r = await fetch('/party/api/' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json() };
}, { path, body });

async function reset(request: any) {
  expect((await request.post('/__harness__/party/reset')).ok()).toBe(true);
}

const latestState = (page: Page) => page.evaluate(() => (window as any).__avr.rx.filter((m: any) => m.type === 'state').at(-1));
/** A Party round (AVR-129): no ready/start in BLUFF; it deals once every seat's phone is here. */
async function play(phones: Phone[]) {
  for (const p of phones) {
    await expect.poll(async () => (await latestState(p.page))?.game?.me?.cards?.length ?? 0).toBe(2);
  }
}

/** Ana (host) and the others join on Party Home; Ana starts BLUFF; everyone ends up in it. With
 * `dealt`, they also start a hand, so every player holds a seat the game keeps for them (in
 * BLUFF's own pre-game lobby a player who walks away is not held a place). */
async function startTogether(browser: Browser, request: any, names = ['Ana', 'Ben'], dealt = false) {
  await reset(request);
  const phones: Phone[] = [];
  for (const [i, name] of names.entries()) {
    const p = await phone(browser, i);
    await joinParty(p.page, name);
    phones.push(p);
  }
  await startForEveryone(phones[0].page, 'bluff');
  for (const p of phones) await expect(p.page).toHaveURL(IN_BLUFF);
  const pids: string[] = [];
  for (const p of phones) pids.push((await welcome(p.page)).pid);
  if (dealt) await play(phones);
  return { phones, pids };
}

test('the host starts BLUFF once and every phone is in the same game, with no Join anywhere', async ({ browser, request }) => {
  await reset(request);
  const ana = await phone(browser, 0), ben = await phone(browser, 1), cleo = await phone(browser, 0);
  await joinParty(ana.page, 'Ana');
  await joinParty(ben.page, 'Ben');
  await joinParty(cleo.page, 'Cleo');
  for (const p of [ana, ben, cleo]) await expect(p.page.getByRole('button', { name: /Join the party|Leave the party/ })).toHaveCount(0);
  await expect(ana.page.locator('#party-host')).toContainText('You’re the host');
  await expect(ben.page.locator('#party-host')).toContainText('Ana is the host');
  await place(ben.page, 'library');
  for (const id of ['bluff', 'expo']) {
    const card = await openGame(ben.page, id);
    await expect(card.locator('[data-wait]')).toHaveText('The host starts it. Ana chooses what the Party plays.');
    await expect(card.getByRole('button', { name: /start/i })).toHaveCount(0);   // a guest has nothing to press that moves the Party
  }
  // BLUFF's own page, from the real game: its premise and its rules, read without moving anyone
  const bluff = await openGame(ben.page, 'bluff');
  await expect(bluff.locator('.avrana-about')).toContainText('secret roles');
  await expect(bluff.locator('.avrana-game-facts')).toContainText('2–6 players');
  await expect(bluff.locator('[data-suits="true"]')).toHaveText('Room for all three of you.');
  await bluff.getByRole('button', { name: 'How to play' }).click();
  await expect(ben.page.locator('#rules')).toBeVisible();
  await expect(ben.page.locator('#rules-body section')).toHaveCount(5);
  await ben.page.keyboard.press('Escape');
  await expect(bluff.getByRole('button', { name: 'How to play' })).toBeFocused();
  expect((await partyState(ben.page)).location.at).toBe('home');
  const v = await partyState(ben.page);
  expect(await api(ben.page, 'session/launch', { game: 'bluff', if_version: v.version })).toMatchObject({ status: 403, body: { error: 'not_host' } });
  await startForEveryone(ana.page, 'bluff');
  for (const p of [ana, ben, cleo]) await expect(p.page).toHaveURL(IN_BLUFF);
  const welcomes = [await welcome(ana.page), await welcome(ben.page), await welcome(cleo.page)];
  for (const w of welcomes) { expect(w.pid).toBeTruthy(); expect(w.watch).toBeUndefined(); }
  expect(new Set(welcomes.map((w) => w.pid)).size).toBe(3);
  const after = await partyState(cleo.page);
  expect(after.location).toMatchObject({ at: 'game', game: 'bluff' });
  expect(after.members.map((m: any) => m.presence)).toEqual(['playing', 'playing', 'playing']);
  const text = await ben.page.evaluate(() => JSON.stringify((window as any).__avr.rx));
  expect(text).not.toContain('member-');
  expect(text).not.toContain('device-');
  for (const p of [ana, ben, cleo]) await p.context.close();
});

test('during a round Party Home and other games are not places a follower can be: they lead back into it', async ({ browser, request }) => {
  const { phones: [ana, ben], pids: [, pb] } = await startTogether(browser, request, ['Ana', 'Ben'], true);
  await expect(ben.page.locator('#avrana-navigation')).toBeHidden();           // no Back to Party
  for (const url of ['/party/', '/games/expo/?avrana=1']) {
    await ben.page.goto(url);
    await expect(ben.page).toHaveURL(IN_BLUFF);
  }
  expect((await welcome(ben.page)).pid).toBe(pb);                               // the same seat
  // a new tab, and a tab holding stale memory, land in the round too
  const again = await ben.context.newPage();
  await again.addInitScript(record);
  await again.addInitScript(() => { try { sessionStorage.setItem('avrana-party-entered', 'session-' + '0'.repeat(32)); } catch { /* private */ } });
  await again.goto('/party/');
  await expect(again).toHaveURL(IN_BLUFF);
  expect((await welcome(again)).pid).toBe(pb);
  await ana.context.close(); await ben.context.close();
});

test('a start from a stale view is re-checked and happens once; everyone still goes', async ({ browser, request }) => {
  await reset(request);
  const ana = await phone(browser, 0), ben = await phone(browser, 1);
  await ana.page.route((url) => url.pathname === '/party/api/state' && url.searchParams.has('since'), () => {});
  await joinParty(ana.page, 'Ana');
  await joinParty(ben.page, 'Ben');
  const before = (await partyState(ana.page)).version;
  expect((await api(ben.page, 'rename', { name: 'Benji' })).status).toBe(200);
  const starts: string[] = [];
  ana.page.on('request', (r) => { if (r.url().endsWith('/party/api/session/launch')) starts.push(r.postData() || ''); });
  await startForEveryone(ana.page, 'bluff');
  await expect(ana.page).toHaveURL(IN_BLUFF);
  await expect(ben.page).toHaveURL(IN_BLUFF);
  expect(starts.length).toBe(2);
  expect(JSON.parse(starts[0]).if_version).toBeLessThanOrEqual(before);
  await ana.context.close(); await ben.context.close();
});

test('the host leaving mid-game hands the party to a player, who then has the in-game End', async ({ browser, request }) => {
  const { phones: [ana, ben], pids: [, pb] } = await startTogether(browser, request, ['Ana', 'Ben'], true);
  await expect(ana.page.locator('#party-end')).toBeVisible();
  await expect(ben.page.locator('#party-end')).toBeHidden();
  expect((await api(ana.page, 'leave', {})).status).toBe(200);                 // the host's phone left
  await expect(ben.page.locator('#party-end')).toBeVisible();                   // Ben hosts now, in the table
  await ben.page.reload();
  expect((await welcome(ben.page)).pid).toBe(pb);
  await ben.page.locator('#party-end').click();
  await ben.page.locator('#confirm-yes').click();
  await expect(ben.page).toHaveURL(AT_HOME);
  expect((await partyState(ben.page)).location.at).toBe('home');
  await ana.context.close(); await ben.context.close();
});

test('a failed start says why and stays home; a second party game cannot start over the first', async ({ browser, request }) => {
  await reset(request);
  const ana = await phone(browser, 0), ben = await phone(browser, 1);
  await joinParty(ana.page, 'Ana');
  await joinParty(ben.page, 'Ben');
  await startForEveryone(ana.page, 'expo');
  await expect(ana.page.locator('#party-note')).toContainText('EXPO didn’t start');
  await expect(ana.page.locator('#party-note')).toBeInViewport();              // the reason is in sight, on the game's page
  await ben.page.waitForTimeout(1_500);
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(AT_HOME);
  await startForEveryone(ana.page, 'bluff');
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(IN_BLUFF);
  const v = await partyState(ana.page);
  expect(await api(ana.page, 'session/launch', { game: 'expo', if_version: v.version })).toMatchObject({ status: 409, body: { error: 'busy' } });
  expect((await partyState(ana.page)).session.game).toBe('bluff');
  await ana.context.close(); await ben.context.close();
});

test('the host ends BLUFF from the table and every phone goes home together', async ({ browser, request }) => {
  const { phones: [ana, ben] } = await startTogether(browser, request, ['Ana', 'Ben'], true);
  const v = await partyState(ben.page);
  expect(await api(ben.page, 'session/end', { if_version: v.version })).toMatchObject({ status: 403, body: { error: 'not_host' } });
  await ana.page.locator('#party-end').click();
  await expect(ana.page.locator('#confirm')).toBeVisible();
  expect((await partyState(ana.page)).state).toBe('active');                    // asking is not ending
  await ana.page.locator('#confirm-yes').click();
  for (const p of [ana, ben]) {
    await expect(p.page).toHaveURL(AT_HOME);
    await expect(p.page.locator('#nav')).toBeVisible();
  }
  expect(await partyState(ben.page)).toMatchObject({ state: 'lobby', location: { at: 'home' } });
  await ana.context.close(); await ben.context.close();
});

test('a host switch ends BLUFF before the next game; the phones in BLUFF go where the party goes', async ({ browser, request }) => {
  const { phones: [ana, ben] } = await startTogether(browser, request, ['Ana', 'Ben'], true);
  const first = await store(ben.page, 'avrana-party-session:bluff');
  let v = await partyState(ana.page);
  const round = await api(ana.page, 'session/switch', { game: 'bluff', if_version: v.version });
  expect(round).toMatchObject({ status: 200, body: { state: 'active', session: { game: 'bluff' } } });
  expect(round.body.session.id).not.toBe(first);
  await expect.poll(() => storeDuringMoves(ben.page, 'avrana-party-session:bluff'), { timeout: 30_000 }).toBe(round.body.session.id);
  await expect(ben.page).toHaveURL(IN_BLUFF);
  v = await partyState(ana.page);
  await api(ana.page, 'session/switch', { game: 'expo', if_version: v.version });   // cannot start here
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(AT_HOME);
  expect(await partyState(ben.page)).toMatchObject({ state: 'lobby', location: { at: 'home' }, session: { game: 'expo', outcome: 'launch_failed' } });
  await ana.context.close(); await ben.context.close();
});

test('without Party Core, Party Home is the catalog it always was', async ({ page }) => {
  await page.goto(NO_PARTY + '/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('html')).toHaveAttribute('data-party', 'off');
  await expect(page.locator('#party')).toBeHidden();
  await place(page, 'library');
  const bluff = await openGame(page, 'bluff');
  await expect(bluff.getByRole('link', { name: 'Play' })).toHaveAttribute('href', '/games/bluff/?avrana=1');
  await expect(bluff).not.toHaveAttribute('data-party', /.*/);
});

test('standalone BLUFF (no Party Core) keeps its own lobby and its Back link', async ({ page }) => {
  await page.goto(NO_PARTY + '/games/bluff/?avrana=1');
  await expect(page.locator('#avrana-navigation a')).toBeVisible();
  await expect(page.getByRole('button', { name: /READY/ })).toBeVisible();
});
