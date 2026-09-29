import { test, expect as baseExpect, devices, type Browser, type BrowserContext, type Page } from '@playwright/test';

/**
 * AVR-23: BLUFF reconnect and private-state restoration in a Party session, end to end on one
 * origin: the real Party service (/party/api/, cookie, tickets), the real games server
 * (/games/bluff/, its launch route and sockets) and the real BLUFF page with hubnet.js.
 * Harness: tests/provider/server.py --party-session (party_harness.py). Laptop only: this is
 * TESTED, not a phone measurement (docs/runbooks/bluff-party-reconnect.md is the phone check).
 */
const BASE = 'http://127.0.0.1:8183';
test.use({ baseURL: BASE });
// One run is enough: every test builds its own phones (a Pixel-sized one and an iPhone-sized one).
test.beforeEach(({}, info) => test.skip(info.project.name !== 'android-size', 'runs once, with both phone sizes'));
test.setTimeout(120_000);
// Real servers on a shared laptop: allow for load (another suite running) without hiding a hang.
const expect = baseExpect.configure({ timeout: 15_000 });

type Frame = { i: number; m: any };
type Log = { rx: Frame[]; tx: Frame[]; opened: number };

// Records what the page's own code sends and receives on every WebSocket (hubnet.js), so each
// assertion reads exactly what that phone was told. The log restarts with every page load.
function record() {
  const Native = window.WebSocket;
  const log = { rx: [] as any[], tx: [] as any[], opened: 0, sockets: [] as WebSocket[] };
  (window as any).__avr = log;
  (window as any).__NativeWebSocket = Native;          // for the test's own probe sockets
  class Recorded extends Native {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      const i = log.sockets.push(this) - 1;
      this.addEventListener('open', () => { log.opened++; });
      this.addEventListener('message', (e) => { try { log.rx.push({ i, m: JSON.parse(e.data) }); } catch {} });
    }
    send(data: any) {
      try { log.tx.push({ i: log.sockets.indexOf(this), m: JSON.parse(data) }); } catch {}
      super.send(data);
    }
  }
  (window as any).WebSocket = Recorded;
}

const PHONES = [devices['Pixel 7'], devices['iPhone 13']];

async function phone(browser: Browser, n = 0): Promise<{ context: BrowserContext; page: Page }> {
  const { defaultBrowserType, ...device } = PHONES[n % PHONES.length] as any;
  const context = await browser.newContext({ ...device, baseURL: BASE, serviceWorkers: 'block' });
  // These phones have already read BLUFF's first-play briefing (AVR-90; games/bluff/web/briefing.js
  // KEY/VERSION), so it doesn't cover the lobby; the briefing has its own tests in the games repo.
  await context.addInitScript(() => { try { localStorage.setItem('bluff-briefed', '1'); } catch { /* private */ } });
  const page = await context.newPage();
  await page.addInitScript(record);
  return { context, page };
}

async function log(page: Page): Promise<Log> {
  return page.evaluate(() => { const l = (window as any).__avr; return { rx: l.rx, tx: l.tx, opened: l.opened }; });
}
const states = (l: Log) => l.rx.map((f) => f.m).filter((m) => m.type === 'state');
const welcomes = (l: Log) => l.rx.map((f) => f.m).filter((m) => m.type === 'welcome');
const hellos = (l: Log) => l.tx.map((f) => f.m).filter((m) => m.t === 'hello');
const latest = async (page: Page) => states(await log(page)).at(-1);

// The harness's bare Join / Launch page (the Party shell has no Join UI yet).
async function join(page: Page, name: string) {
  await page.goto('/__harness__/party-lab');
  await page.locator('#name').fill(name);
  await page.getByRole('button', { name: 'Join', exact: true }).click();
  await expect(page.locator('#out')).toContainText(`me: ${name}`);
}
// A host action carries if_version from the lab's last view. If a presence change moved the version
// in between, the Party answers 409 "The party changed": wait for the fresh view, then try again.
async function hostAction(host: Page, button: string, done: string) {
  const out = host.locator('#out');
  for (let i = 0; i < 5; i++) {
    // Click only once the lab page has its view: a click on a page still showing "Loading..." carries
    // no if_version, the Party answers 409, and the lab's next poll overwrites that message at once.
    await expect(out).toContainText('me: ');
    await host.getByRole('button', { name: button }).click();
    await expect(out).toContainText(new RegExp(`${done}|The party changed`), { timeout: 15_000 });
    if ((await out.textContent())!.includes(done)) return;
    await expect(out).toContainText('me: ');
  }
  throw new Error(`${button}: the party kept changing`);
}
const launch = (host: Page) => hostAction(host, 'Launch BLUFF (host)', 'game: bluff active, you are a player');
async function openBluff(page: Page) {
  await page.goto('/games/bluff/?avrana=1');
  await expect.poll(async () => welcomes(await log(page)).length).toBeGreaterThan(0);
  return welcomes(await log(page)).at(-1);
}
async function playing(page: Page) {
  await expect.poll(async () => (await latest(page))?.game?.me?.cards?.length ?? 0, { timeout: 15_000 }).toBe(2);
  return (await latest(page)).game;
}
const presenceOf = async (page: Page, pid: string) =>
  (await latest(page))?.game?.seats?.find((s: any) => s.pid === pid)?.presence;

/** Two members join, the host launches BLUFF, both open it with tickets and start a game. */
async function table(browser: Browser, request: any) {
  expect((await request.post('/__harness__/party/reset')).ok()).toBe(true);
  const ana = await phone(browser, 0), ben = await phone(browser, 1);
  await join(ana.page, 'Ana'); await join(ben.page, 'Ben');
  await launch(ana.page);
  const wa = await openBluff(ana.page), wb = await openBluff(ben.page);
  for (const p of [ana.page, ben.page]) {
    await p.getByRole('button', { name: /I'M READY/ }).click();
  }
  await ana.page.getByRole('button', { name: /START GAME/ }).click();
  const ga = await playing(ana.page), gb = await playing(ben.page);
  return { ana, ben, pa: wa.pid as string, pb: wb.pid as string, ga, gb };
}

test('reload returns the same participant to the same seat and hand, by Party identity only', async ({ browser, request }) => {
  const { ana, ben, pa, pb, ga } = await table(browser, request);
  expect(pa).not.toBe(pb);
  expect(ga.me.pid).toBe(pa);
  const first = await log(ana.page);
  // the hello carried a ticket and no browser token; the welcome gave no token back
  expect(hellos(first)).toHaveLength(1);
  expect(hellos(first)[0].ticket).toMatch(/^aps0\./);
  expect(hellos(first)[0].token).toBeUndefined();
  expect(welcomes(first)[0].token).toBeUndefined();

  // The browser's own wc-token is not what brings Ana back: point it at someone else's.
  await ana.page.evaluate(() => localStorage.setItem('wc-token', 'someone-elses-token-123'));
  await ana.page.reload();
  const again = await openBluffAfterReload(ana.page);
  expect(again.pid).toBe(pa);
  const back = await playing(ana.page);
  expect(back.me.pid).toBe(pa);
  expect(back.me.cards).toEqual(ga.me.cards);
  expect(back.seats.map((s: any) => s.pid)).toEqual(ga.seats.map((s: any) => s.pid));
  const second = await log(ana.page);
  expect(hellos(second)[0].ticket).toMatch(/^aps0\./);
  expect(hellos(second)[0].ticket).not.toBe(hellos(first)[0].ticket);     // a fresh ticket
  expect(hellos(second)[0].token).toBeUndefined();
  await expect.poll(() => presenceOf(ben.page, pa)).toBe('here');
  expect(await ana.page.evaluate(() => localStorage.getItem('wc-token'))).toBe('someone-elses-token-123');

  // Nothing in the browser's storage identifies Ana: clear it all and reload.
  await ana.page.evaluate(() => localStorage.clear());
  await ana.page.reload();
  expect((await openBluffAfterReload(ana.page)).pid).toBe(pa);
  expect((await playing(ana.page)).me.cards).toEqual(ga.me.cards);
  await ana.context.close(); await ben.context.close();
});

async function openBluffAfterReload(page: Page) {
  await expect.poll(async () => welcomes(await log(page)).length).toBeGreaterThan(0);
  return welcomes(await log(page)).at(-1);
}

test('sleep and wake within the grace return the same seat and hand', async ({ browser, request }) => {
  const { ana, ben, pa, ga } = await table(browser, request);
  // Sleep: the network goes away and the socket drops; the other phones see "reconnecting".
  const awake = await log(ana.page);
  await ana.context.setOffline(true);
  await ana.page.evaluate(() => (window as any).__avr.sockets.forEach((s: WebSocket) => s.close()));
  await expect.poll(() => presenceOf(ben.page, pa)).toBe('reconnecting');
  await ben.page.waitForTimeout(8_000);                  // well inside BLUFF's AWAY_GRACE (30 s)
  expect(await presenceOf(ben.page, pa)).toBe('reconnecting');
  const asleep = await log(ana.page);
  expect(asleep.opened).toBe(awake.opened);              // no socket got through while asleep
  expect(welcomes(asleep)).toEqual(welcomes(awake));
  // Wake: the network is back; hubnet reconnects with a fresh ticket.
  await ana.context.setOffline(false);
  await ana.page.evaluate(() => { dispatchEvent(new Event('online')); document.dispatchEvent(new Event('visibilitychange')); });
  await expect.poll(async () => welcomes(await log(ana.page)).length, { timeout: 15_000 }).toBeGreaterThan(welcomes(asleep).length);
  const woke = await log(ana.page);
  expect(welcomes(woke).at(-1)).toEqual({ type: 'welcome', pid: pa });
  expect(welcomes(woke).some((w) => w.watch)).toBe(false);          // never demoted to a watcher
  expect(hellos(woke).every((h) => typeof h.ticket === 'string' && h.token === undefined)).toBe(true);
  const back = states(woke).at(-1).game;
  expect(back.me.pid).toBe(pa);
  expect(back.me.cards).toEqual(ga.me.cards);
  await expect.poll(() => presenceOf(ben.page, pa)).toBe('here');
  await ana.context.close(); await ben.context.close();
});

test('waking while the first ticket request fails still returns the player, not a watcher', async ({ browser, request }) => {
  // A phone waking up often loses its first request (a stale keep-alive connection, Wi-Fi still
  // rejoining) while a brand-new socket connects. That lost request must not demote the player.
  const { ana, ben, pa, ga } = await table(browser, request);
  let failures = 1;
  await ana.page.route('**/party/api/session/ticket', (route) =>
    failures-- > 0 ? route.abort('internetdisconnected') : route.continue());
  const before = await log(ana.page);
  await ana.page.evaluate(() => (window as any).__avr.sockets.forEach((s: WebSocket) => s.close()));
  await expect.poll(async () => welcomes(await log(ana.page)).length, { timeout: 15_000 }).toBeGreaterThan(welcomes(before).length);
  const woke = await log(ana.page);
  expect(welcomes(woke).slice(welcomes(before).length)).toEqual([{ type: 'welcome', pid: pa }]);
  await expect.poll(async () => (await latest(ana.page))?.game?.me?.pid).toBe(pa);
  expect(hellos(woke).slice(hellos(before).length).every((h) => typeof h.ticket === 'string')).toBe(true);
  expect((await latest(ana.page)).game.me.cards).toEqual(ga.me.cards);
  await expect.poll(() => presenceOf(ben.page, pa)).toBe('here');
  await ana.context.close(); await ben.context.close();
});

test('nobody else can take a seat or see a hand: another member, a forged or stale ticket, a wc-token, a stranger', async ({ browser, request }) => {
  const { ana, ben, pa, pb, ga, gb } = await table(browser, request);
  const anaTicket = hellos(await log(ana.page))[0].ticket as string;

  // Ben asks the Party for a ticket and says hello on a second socket: he is Ben, never Ana.
  const own = await ben.page.evaluate(async () => {
    const r = await fetch('/party/api/session/ticket', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    return (await r.json()).ticket;
  });
  const hello = (page: Page, msg: any) => page.evaluate((msg) => new Promise<any[]>((resolve) => {
    const ws: WebSocket = new (window as any).__NativeWebSocket(`ws://${location.host}/games/bluff/ws`);
    const got: any[] = [];
    ws.onopen = () => ws.send(JSON.stringify(msg));
    ws.onmessage = (e: MessageEvent) => { got.push(JSON.parse(e.data)); if (got.some((m) => m.type === 'state')) { ws.close(); resolve(got); } };
    ws.onclose = () => resolve(got);
  }), msg);
  const asBen = await hello(ben.page, { t: 'hello', ticket: own });
  expect(asBen[0]).toEqual({ type: 'welcome', pid: pb });
  expect(asBen.find((m) => m.type === 'state').game.me.pid).toBe(pb);

  // A forged ticket (Ben's, re-addressed to another participant) is refused and never seated.
  const [pfx, body, sig] = own.split('.');
  const payload = JSON.parse(Buffer.from(body, 'base64url').toString());
  payload.pid = 'participant-' + '0'.repeat(32);
  const forged = [pfx, Buffer.from(JSON.stringify(payload)).toString('base64url'), sig].join('.');
  const refused = await hello(ben.page, { t: 'hello', ticket: forged });
  expect(refused.map((m) => m.type)).toEqual(['fx']);
  expect(refused[0].msg).toMatch(/ticket refused/i);

  // The browser-minted wc-token (even Ana's own, with her name) only watches.
  const anaWc = await ana.page.evaluate(() => localStorage.getItem('wc-token'));
  const wc = await hello(ben.page, { t: 'hello', token: anaWc || 'ana-wc-token-1234', name: 'Ana' });
  expect(wc[0]).toEqual({ type: 'welcome', watch: true });
  expect(wc.find((m) => m.type === 'state').game.me).toBeNull();

  // A stranger who never joined the Party gets no ticket and only watches the table.
  const stranger = await phone(browser, 0);
  const ws = await openBluff(stranger.page);
  expect(ws).toEqual({ type: 'welcome', watch: true });
  const view = await latest(stranger.page);
  expect(view.game.me).toBeNull();
  expect(view.game.seats.map((s: any) => s.pid)).toEqual(ga.seats.map((s: any) => s.pid));
  expect(JSON.stringify(view)).not.toContain('"cards"');

  // Ben's phone never received anyone's hand but his own.
  const benStates = states(await log(ben.page));
  expect(benStates.length).toBeGreaterThan(0);
  for (const st of benStates) {
    if (st.game) expect(st.game.me.pid).toBe(pb);
    for (const seat of st.game?.seats ?? []) expect(Object.keys(seat)).not.toContain('cards');
  }
  expect(gb.me.cards).toHaveLength(2);

  // A seat is still Ana's after all of that.
  expect((await latest(ana.page)).game.me).toMatchObject({ pid: pa, cards: ga.me.cards });

  // Stale: the host ends the Party's session and launches a new one. Ana's old ticket (for the
  // old session) is refused by the game from then on.
  await ana.page.goto('/__harness__/party-lab');
  await hostAction(ana.page, 'End game (host)', 'game: bluff ended');
  await launch(ana.page);
  const stale = await hello(ben.page, { t: 'hello', ticket: anaTicket });
  expect(stale.map((m) => m.type)).toEqual(['fx']);
  expect(stale[0].msg).toMatch(/ticket refused/i);
  await ana.context.close(); await ben.context.close(); await stranger.context.close();
});

// ---- Party state is authoritative across ends and launches (integration of AVR-22/23/24) ----------

const partySession = (page: Page) => page.evaluate(() => sessionStorage.getItem('avrana-party-session:bluff'));
const ended = (page: Page) => page.locator('#party-ended');

test('a ticket timeout and repeated network failures never demote a player', async ({ browser, request }) => {
  const { ana, ben, pa, ga } = await table(browser, request);
  let n = 0;
  await ana.page.route('**/party/api/session/ticket', async (route) => {
    n++;
    if (n === 1) { await new Promise((r) => setTimeout(r, 7_000)); return route.abort('timedout').catch(() => {}); }
    if (n <= 3) return route.abort('internetdisconnected');
    return route.continue();
  });
  const before = await log(ana.page);
  await ana.page.evaluate(() => (window as any).__avr.sockets.forEach((s: WebSocket) => s.close()));
  await expect.poll(async () => welcomes(await log(ana.page)).length, { timeout: 30_000 }).toBeGreaterThan(welcomes(before).length);
  const after = await log(ana.page);
  expect(n).toBeGreaterThanOrEqual(4);                               // timed out, failed twice, then a ticket
  expect(welcomes(after).slice(welcomes(before).length)).toEqual([{ type: 'welcome', pid: pa }]);
  expect(hellos(after).slice(hellos(before).length).every((h) => typeof h.ticket === 'string' && h.token === undefined)).toBe(true);
  expect(after.opened - before.opened).toBe(1);                      // no ticketless socket in between
  await expect.poll(async () => (await latest(ana.page))?.game?.me?.cards).toEqual(ga.me.cards);
  await ana.context.close(); await ben.context.close();
});

test('asleep through the host\'s end: the page follows the Party home, never a standalone seat, then joins the rematch as a new session', async ({ browser, request }) => {
  const { ana, ben, pb } = await table(browser, request);
  const first = await partySession(ben.page);
  expect(first).toMatch(/^session-/);
  // Ben's phone sleeps; meanwhile the host ends the game for everyone.
  await ben.context.setOffline(true);
  await ben.page.evaluate(() => (window as any).__avr.sockets.forEach((s: WebSocket) => s.close()));
  const asleep = await log(ben.page);
  await ana.page.goto('/__harness__/party-lab');
  await hostAction(ana.page, 'End game (host)', 'game: bluff ended');
  // Ben wakes. The host's end is a committed Party move (AVR-128, ADR 0008), so his BLUFF page
  // follows it back to Party Home rather than rejoining the room (standalone or as a watcher).
  // The games-side ended state without a Party follower is pinned in the games repository
  // (tests/hubnet_party_ticket_test.mjs).
  expect(welcomes(asleep).length).toBeGreaterThan(0);
  await ben.context.setOffline(false);
  await ben.page.evaluate(() => { dispatchEvent(new Event('online')); document.dispatchEvent(new Event('visibilitychange')); });
  await expect(ben.page).toHaveURL(/\/party\/$/, { timeout: 30_000 });
  await expect(ben.page.locator('#avrana-game-room')).toHaveCount(0);
  // The host starts a rematch: a new Party session. Party Home takes Ben into it (ADR 0007).
  await launch(ana.page);
  await expect(ben.page).toHaveURL(/\/games\/bluff\/\?avrana=1$/);
  await expect.poll(async () => welcomes(await log(ben.page)).length, { timeout: 20_000 }).toBeGreaterThan(0);
  const rejoined = welcomes(await log(ben.page)).at(-1);
  expect(rejoined.watch).toBeUndefined();
  expect(rejoined.pid).toBeTruthy();
  const second = await partySession(ben.page);
  expect(second).toMatch(/^session-/);
  expect(second).not.toBe(first);                                    // one session per play-through
  await expect(ended(ben.page)).toHaveCount(0);
  await expect(ben.page.locator('#avrana-game-room')).toBeVisible();
  const fresh = await latest(ben.page);
  expect(fresh.phase).toBe('lobby');                                 // a fresh table, no old hands
  expect(fresh.you?.pid).toBe(rejoined.pid);
  void pb;
  await ana.context.close(); await ben.context.close();
});

test('a watcher becomes a player at the next launch that includes them, without a reload', async ({ browser, request }) => {
  const { ana, ben } = await table(browser, request);
  // Cleo joins after the launch: the Party admits her as a spectator, so she watches.
  const cleo = await phone(browser, 1);
  await join(cleo.page, 'Cleo');
  const watching = await openBluff(cleo.page);
  expect(watching).toEqual({ type: 'welcome', watch: true });
  expect((await latest(cleo.page)).game.me).toBeNull();
  const before = await log(cleo.page);
  // The host ends the game and launches again; Cleo is here, so she is on the roster now.
  await ana.page.goto('/__harness__/party-lab');
  await hostAction(ana.page, 'End game (host)', 'game: bluff ended');
  await launch(ana.page);
  await expect.poll(async () => welcomes(await log(cleo.page)).filter((w) => w.pid).length, { timeout: 20_000 }).toBe(1);
  const now = await log(cleo.page);
  const promoted = welcomes(now).slice(welcomes(before).length).find((w) => w.pid);
  expect(promoted.watch).toBeUndefined();
  await expect.poll(async () => (await latest(cleo.page))?.you?.pid).toBe(promoted.pid);
  expect(hellos(now).slice(hellos(before).length).every((h) => typeof h.ticket === 'string')).toBe(true);
  await ana.context.close(); await ben.context.close(); await cleo.context.close();
});
