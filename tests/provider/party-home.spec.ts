import { test, expect as baseExpect, devices, type Browser, type BrowserContext, type Page } from '@playwright/test';

/**
 * AVR-20 + AVR-127: Party Home on Party Core. The host starts a party game once; Party Core
 * validates it and commits one session; every joined phone's Party Home observes that on its long
 * poll and goes into the same game with its Party identity (the existing ticket path). Reopened,
 * stale and returning phones resolve to the party's current game; the host role can move mid-game
 * without ending it. Real Party service, real games server, real BLUFF page, real /party/ shell
 * (tests/provider/server.py --party-session). Laptop only: TESTED here, not a phone measurement.
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

async function joinParty(page: Page, name: string) {
  await home(page);
  await page.locator('#party-name').fill(name);
  await page.getByRole('button', { name: 'Join the party', exact: true }).click();
  await expect(page.locator('#party-members')).toContainText(`${name} (you)`);
}

const tile = (page: Page, id: string) => page.locator(`[data-id="${id}"]`);
const IN_BLUFF = /\/games\/bluff\/\?avrana=1$/;
const partyState = (page: Page) => page.evaluate(async () => (await fetch('/party/api/state', { cache: 'no-store' })).json());
const store = (page: Page, key: string) => page.evaluate((k) => sessionStorage.getItem(k), key);
const api = (page: Page, path: string, body: any) => page.evaluate(async ({ path, body }) => {
  const r = await fetch('/party/api/' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json() };
}, { path, body });

/** Every /party/api/state answer a page received (the long poll included). */
function watchViews(page: Page) {
  const views: any[] = [];
  page.on('response', async (r) => {
    if (new URL(r.url()).pathname !== '/party/api/state') return;
    try { views.push(await r.json()); } catch { /* the page moved on */ }
  });
  return views;
}

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
  await tile(phones[0].page, 'bluff').getByRole('button', { name: 'Start for everyone' }).click();
  for (const p of phones) await expect(p.page).toHaveURL(IN_BLUFF);
  const pids: string[] = [];
  for (const p of phones) pids.push((await welcome(p.page)).pid);
  if (dealt) await play(phones);
  return { phones, pids };
}

test('the host starts BLUFF once and every joined phone follows into the same game', async ({ browser, request }) => {
  await reset(request);
  const ana = await phone(browser, 0), ben = await phone(browser, 1), cleo = await phone(browser, 0);
  await joinParty(ana.page, 'Ana');
  await joinParty(ben.page, 'Ben');
  await joinParty(cleo.page, 'Cleo');
  const seen = watchViews(ben.page);
  await expect(ana.page.locator('#party-host')).toContainText('You’re the host');
  await expect(ben.page.locator('#party-host')).toContainText('Ana is the host');

  // Not the host: the page does not offer a party-wide start, and Party Core refuses one.
  for (const id of ['bluff', 'lan-chess']) {
    await expect(tile(ben.page, id)).toHaveAttribute('data-party', 'wait');
    await expect(tile(ben.page, id).getByRole('button', { name: 'The host starts it' })).toBeDisabled();
    await expect(tile(ben.page, id).getByRole('link')).toHaveCount(0);
  }
  const v = await partyState(ben.page);
  expect(v.games).toEqual(['bluff', 'chess']);
  const refused = await api(ben.page, 'session/launch', { game: 'bluff', if_version: v.version });
  expect(refused).toMatchObject({ status: 403, body: { error: 'not_host' } });
  // A standalone title is exactly what it was: its own Play link, for anyone.
  await expect(tile(ben.page, 'lan-wordclash').getByRole('link', { name: 'Play' })).toHaveAttribute('href', '/games/wordclash/?avrana=1');

  await tile(ana.page, 'bluff').getByRole('button', { name: 'Start for everyone' }).click();
  await expect(ben.page.locator('#party-live')).toContainText('The host started BLUFF');
  for (const p of [ana, ben, cleo]) await expect(p.page).toHaveURL(IN_BLUFF);
  const welcomes = [await welcome(ana.page), await welcome(ben.page), await welcome(cleo.page)];
  for (const w of welcomes) { expect(w.pid).toBeTruthy(); expect(w.watch).toBeUndefined(); }   // seated players
  expect(new Set(welcomes.map((w) => w.pid)).size).toBe(3);

  // One session, the same for every phone; the Party still has all three, now playing.
  const sid = await store(ana.page, 'avrana-party-session:bluff');
  expect(sid).toMatch(/^session-/);
  for (const p of [ben, cleo]) {
    expect(await store(p.page, 'avrana-party-session:bluff')).toBe(sid);
    expect(await store(p.page, 'avrana-party-entered')).toBe(sid);
  }
  const after = await partyState(cleo.page);
  expect(after.state).toBe('active');
  expect(after.session).toMatchObject({ id: sid, game: 'bluff', players: 3, my_role: 'player' });
  expect(after.members.map((m: any) => m.presence)).toEqual(['playing', 'playing', 'playing']);
  expect(new Set(seen.filter((x) => x.session).map((x) => x.session.id))).toEqual(new Set([sid]));
  // The host's start was one transition: Ben saw it start and go live, and nothing else.
  expect(seen.filter((x) => x.session).map((x) => x.state).filter((s, i, a) => s !== a[i - 1]))
    .toEqual(expect.arrayContaining(['active']));
  // No device or member id reached a game page.
  const text = await ben.page.evaluate(() => JSON.stringify((window as any).__avr.rx));
  expect(text).not.toContain('member-');
  expect(text).not.toContain('device-');
  for (const p of [ana, ben, cleo]) await p.context.close();
});

test('Back to Party offers Rejoin without bouncing; reopened and stale tabs resolve to the game', async ({ browser, request }) => {
  const { phones: [ana, ben], pids: [, pb] } = await startTogether(browser, request, ['Ana', 'Ben'], true);
  // The fixed return stays: Ben goes back to Party Home and is not sent straight back.
  await ben.page.locator('#avrana-navigation a').first().click();
  await expect(ben.page).toHaveURL(/\/party\/$/);
  await expect(ben.page.locator('#party-now')).toContainText('Your party is playing BLUFF');
  await ben.page.waitForTimeout(2_500);
  await expect(ben.page).toHaveURL(/\/party\/$/);
  await expect(tile(ben.page, 'bluff')).toHaveAttribute('data-party', 'rejoin');
  // Another party game cannot be entered while BLUFF is on, by anyone.
  await expect(tile(ben.page, 'lan-chess').getByRole('button', { name: 'Party is playing BLUFF' })).toBeDisabled();
  await ben.page.getByRole('link', { name: 'Rejoin BLUFF' }).click();
  await expect(ben.page).toHaveURL(IN_BLUFF);
  expect((await welcome(ben.page)).pid).toBe(pb);

  // Reopening Party Home in a new tab (a reconnect, a phone that slept) resolves to the game.
  const again = await ben.context.newPage();
  await again.addInitScript(record);
  await again.goto('/party/');
  await expect(again).toHaveURL(IN_BLUFF);
  expect((await welcome(again)).pid).toBe(pb);
  await again.close();

  // A tab holding stale memory (an old session it entered, an old game session) converges.
  const stale = await ben.context.newPage();
  await stale.addInitScript(record);
  await stale.addInitScript(() => {
    if (location.pathname === '/party/' && !sessionStorage.getItem('test-stale')) {
      sessionStorage.setItem('test-stale', '1');
      sessionStorage.setItem('avrana-party-entered', 'session-' + '0'.repeat(32));
      sessionStorage.setItem('avrana-party-session:bluff', 'session-' + '0'.repeat(32));
    }
  });
  await stale.goto('/party/');
  await expect(stale).toHaveURL(IN_BLUFF);
  const w = await welcome(stale);
  expect(w.pid).toBe(pb);
  expect(await store(stale, 'avrana-party-session:bluff')).toBe(await store(ana.page, 'avrana-party-session:bluff'));
  await ana.context.close(); await ben.context.close();
});

test('a start from a stale view is re-checked and happens once; followers still follow', async ({ browser, request }) => {
  await reset(request);
  const ana = await phone(browser, 0), ben = await phone(browser, 1);
  // Ana's page never hears about changes (its long poll hangs): it knows only its own Join.
  await ana.page.route((url) => url.pathname === '/party/api/state' && url.searchParams.has('since'), () => {});
  await joinParty(ana.page, 'Ana');
  await joinParty(ben.page, 'Ben');
  await expect(ana.page.locator('#party-members')).not.toContainText('Ben');   // a stale view
  const before = (await partyState(ana.page)).version;
  expect((await api(ben.page, 'rename', { name: 'Benji' })).status).toBe(200);
  const starts: string[] = [];
  ana.page.on('request', (r) => { if (r.url().endsWith('/party/api/session/launch')) starts.push(r.postData() || ''); });
  await tile(ana.page, 'bluff').getByRole('button', { name: 'Start for everyone' }).click();
  await expect(ana.page).toHaveURL(IN_BLUFF);
  await expect(ben.page).toHaveURL(IN_BLUFF);
  expect(starts.length).toBe(2);                                  // stale once, then the fresh start
  expect(JSON.parse(starts[0]).if_version).toBeLessThanOrEqual(before);
  const sid = await store(ana.page, 'avrana-party-session:bluff');
  expect(await store(ben.page, 'avrana-party-session:bluff')).toBe(sid);
  expect((await welcome(ben.page)).watch).toBeUndefined();
  await ana.context.close(); await ben.context.close();
});

test('the host leaving mid-game hands the party to a player; the game and the seats stay', async ({ browser, request }) => {
  const { phones: [ana, ben], pids: [, pb] } = await startTogether(browser, request, ['Ana', 'Ben'], true);
  const sid = await store(ben.page, 'avrana-party-session:bluff');
  await ana.page.locator('#avrana-navigation a').first().click();
  await expect(ana.page.locator('#party-end')).toBeVisible();
  await ana.page.getByRole('button', { name: 'Leave the party' }).click();
  await expect(ana.page.locator('#party-join')).toBeVisible();
  await expect(tile(ana.page, 'bluff')).toHaveAttribute('data-party', 'join');

  const v = await partyState(ben.page);                           // from Ben's game page
  expect(v).toMatchObject({ state: 'active', me: { host: true }, session: { id: sid, my_role: 'player' } });
  await ben.page.reload();                                        // still his seat, by Party identity
  expect((await welcome(ben.page)).pid).toBe(pb);
  // The new host has real authority: back on Party Home he can end it for everyone.
  await ben.page.locator('#avrana-navigation a').first().click();
  await expect(ben.page.locator('#party-host')).toContainText('You’re the host');
  await ben.page.getByRole('button', { name: 'End the game for everyone' }).click();
  await expect(ben.page.locator('#party-now')).toBeHidden();
  await expect(tile(ben.page, 'bluff').getByRole('button', { name: 'Start for everyone' })).toBeEnabled();
  expect((await partyState(ben.page)).state).toBe('lobby');
  await ana.context.close(); await ben.context.close();
});

test('a failed start says why and stays in the lobby; a second party game cannot start over the first', async ({ browser, request }) => {
  await reset(request);
  const ana = await phone(browser, 0), ben = await phone(browser, 1);
  await joinParty(ana.page, 'Ana');
  await joinParty(ben.page, 'Ben');
  // The harness's second party game has no game side here: the start fails readably, nobody moves.
  await tile(ana.page, 'lan-chess').getByRole('button', { name: 'Start for everyone' }).click();
  await expect(ana.page.locator('#party-note')).toContainText('CHESS didn’t start');
  await ben.page.waitForTimeout(1_500);
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(/\/party\/$/);
  expect((await partyState(ben.page)).state).toBe('lobby');

  await tile(ana.page, 'bluff').getByRole('button', { name: 'Start for everyone' }).click();
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(IN_BLUFF);
  const v = await partyState(ana.page);
  const busy = await api(ana.page, 'session/launch', { game: 'chess', if_version: v.version });
  expect(busy).toMatchObject({ status: 409, body: { error: 'busy' } });
  await ana.page.locator('#avrana-navigation a').first().click();
  // The host is offered a switch (Party Core ends BLUFF first; AVR-128), never a second game.
  await expect(tile(ana.page, 'lan-chess').getByRole('button', { name: /Switch everyone from BLUFF to CHESS/ })).toBeEnabled();
  await expect(tile(ana.page, 'bluff').getByRole('link', { name: 'Rejoin' })).toBeVisible();
  expect((await partyState(ana.page)).session.game).toBe('bluff');
  await ana.context.close(); await ben.context.close();
});

test('AVR-128: the host ends BLUFF from inside it and every player inside it goes back to Party Home', async ({ browser, request }) => {
  const { phones: [ana, ben] } = await startTogether(browser, request, ['Ana', 'Ben'], true);
  // Only the host's game page offers End for everyone; Party Core refuses anyone else anyway.
  await expect(ana.page.getByRole('button', { name: 'End for everyone' })).toBeVisible();
  await expect(ben.page.locator('#avrana-party-end')).toBeHidden();
  const v = await partyState(ben.page);
  expect(await api(ben.page, 'session/end', { if_version: v.version })).toMatchObject({ status: 403, body: { error: 'not_host' } });
  await ana.page.getByRole('button', { name: 'End for everyone' }).click();
  const again = ana.page.getByRole('button', { name: 'Tap again to end it for everyone' });
  await expect(again).toBeVisible();
  expect((await partyState(ana.page)).state).toBe('active');       // one tap never ends it
  await again.click();
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(/\/party\/$/);
  expect(await partyState(ben.page)).toMatchObject({ state: 'lobby', nav: { to: 'home', from: 'bluff' },
    session: { outcome: 'ended_by_host' } });
  await ana.context.close(); await ben.context.close();
});

test('AVR-128: a host switch ends BLUFF before the next game; players inside BLUFF follow the committed move', async ({ browser, request }) => {
  const { phones: [ana, ben] } = await startTogether(browser, request, ['Ana', 'Ben'], true);
  const first = await store(ben.page, 'avrana-party-session:bluff');
  // A fresh round of the same game: Party Core ends the old session, then launches the new one;
  // Ben's BLUFF page stays and joins the new session through its own ticket path.
  const v = await partyState(ana.page);
  const round = await api(ana.page, 'session/switch', { game: 'bluff', if_version: v.version });
  expect(round).toMatchObject({ status: 200, body: { state: 'active', session: { game: 'bluff' } } });
  expect(round.body.session.id).not.toBe(first);
  await expect.poll(() => store(ben.page, 'avrana-party-session:bluff'), { timeout: 30_000 }).toBe(round.body.session.id);
  await expect(ben.page).toHaveURL(IN_BLUFF);
  // A switch to a game whose server cannot start (the harness's chess has no game side): BLUFF
  // still ends first, nothing runs on top of it, and the players inside BLUFF go home.
  await ana.page.locator('#avrana-navigation a').first().click();
  await tile(ana.page, 'lan-chess').getByRole('button', { name: /Switch everyone/ }).click();
  await expect(ben.page).toHaveURL(/\/party\/$/);
  expect(await partyState(ben.page)).toMatchObject({ state: 'lobby', nav: { to: 'home', from: 'bluff' },
    session: { game: 'chess', outcome: 'launch_failed' } });
  await expect(ana.page.locator('#party-note')).toContainText('CHESS didn’t start');
  await ana.context.close(); await ben.context.close();
});

test('without Party Core, Party Home is the catalog it always was', async ({ page }) => {
  await page.goto(NO_PARTY + '/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('html')).toHaveAttribute('data-party', 'off');
  await expect(page.locator('#party')).toBeHidden();
  await expect(tile(page, 'bluff').getByRole('link', { name: 'Play' })).toHaveAttribute('href', '/games/bluff/?avrana=1');
  await expect(tile(page, 'bluff')).not.toHaveAttribute('data-party', /.*/);
});
