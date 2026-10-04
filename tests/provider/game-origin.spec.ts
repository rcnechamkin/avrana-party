import { test, expect as baseExpect, devices, type Browser, type BrowserContext, type Page } from '@playwright/test';

/**
 * ADR 0013 / AVR-226 (Tier 2): a real game on the game origin. The real BLUFF page and hubnet.js
 * from the games checkout are served at games.avrana.test, the real Party Core and shell at
 * party.avrana.test (two host names of one site, like games.avrana.net and party.avrana.net).
 * The game page holds no Party identity: its tickets, its view of the party and the host's End
 * reach it only through the Party's bridge frame and the shim the games repository vendors.
 * Harness: tests/provider/server.py --party-session --game-origin.
 *
 * What this cannot show: Safari on a real iPhone, HTTPS, the `__Host-` cookie and nginx's own
 * routing and headers. Those are Tier 3 and the owner's (docs/design/BROWSER-ORIGINS.md §4).
 */
const PORT = 8184;
const PARTY = `http://party.avrana.test:${PORT}`;
const GAMES = `http://games.avrana.test:${PORT}`;
const LOOPBACK = `http://127.0.0.1:${PORT}`;
test.beforeEach(({}, info) => test.skip(info.project.name !== 'android-size', 'runs once, with both phone sizes'));
test.setTimeout(120_000);
const expect = baseExpect.configure({ timeout: 15_000 });

type Frame = { i: number; m: any };
type Log = { rx: Frame[]; tx: Frame[] };

// What the page's own code sends and receives on every WebSocket (hubnet.js).
function record() {
  const Native = window.WebSocket;
  const log = { rx: [] as any[], tx: [] as any[], sockets: [] as WebSocket[] };
  (window as any).__avr = log;
  class Recorded extends Native {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      const i = log.sockets.push(this) - 1;
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
type Phone = { context: BrowserContext; page: Page; direct: string[] };

async function phone(browser: Browser, n = 0): Promise<Phone> {
  const { defaultBrowserType, ...device } = PHONES[n % PHONES.length] as any;
  const context = await browser.newContext({ ...device, serviceWorkers: 'block' });
  const page = await context.newPage();
  await page.addInitScript(record);
  // Every request the game PAGE itself (not the Party's frame inside it) sends to the Party API.
  const direct: string[] = [];
  page.on('request', (r) => {
    if (r.frame() === page.mainFrame() && page.url().startsWith(GAMES) && r.url().includes('/party/api/')) direct.push(r.url());
  });
  return { context, page, direct };
}
const log = (page: Page): Promise<Log> => page.evaluate(() => { const l = (window as any).__avr; return { rx: l.rx, tx: l.tx }; });
const states = (l: Log) => l.rx.map((f) => f.m).filter((m) => m.type === 'state');
const welcomes = (l: Log) => l.rx.map((f) => f.m).filter((m) => m.type === 'welcome');
const hellos = (l: Log) => l.tx.map((f) => f.m).filter((m) => m.t === 'hello');
const latest = async (page: Page) => states(await log(page)).at(-1);

async function api(page: Page, path: string, body?: unknown) {
  return page.evaluate(async ([p, b]) => {
    const res = await fetch('/party/api/' + p, b === undefined ? { cache: 'no-store' } : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
    return { status: res.status, body: await res.json().catch(() => null) };
  }, [path, body] as const);
}
/** Join on the Party origin, from a Party document with no script of its own. */
async function join(page: Page, name: string) {
  await page.goto(`${PARTY}/party/api/state`);
  const joined = await api(page, 'join', { name });
  expect(joined.status).toBe(200);
  return joined.body;
}
async function openBluff(page: Page) {
  await page.goto(`${GAMES}/games/bluff/?avrana=1`);
  await page.evaluate(() => { try { localStorage.setItem('bluff-briefed', '1'); } catch { /* private */ } });
  await expect.poll(async () => welcomes(await log(page)).length).toBeGreaterThan(0);
  return welcomes(await log(page)).at(-1);
}
async function playing(page: Page) {
  await expect.poll(async () => (await latest(page))?.game?.me?.cards?.length ?? 0).toBe(2);
  return (await latest(page)).game;
}

/** Ana (host) and Ben join the party, Ana starts BLUFF, and both open it on the game origin. */
async function table(browser: Browser, request: any) {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 0), ben = await phone(browser, 1);
  await join(ana.page, 'Ana');
  const view = await join(ben.page, 'Ben');
  const launched = await api(ana.page, 'session/launch', { game: 'bluff', if_version: view.version });
  expect(launched.status).toBe(200);
  const wa = await openBluff(ana.page), wb = await openBluff(ben.page);
  const ga = await playing(ana.page), gb = await playing(ben.page);
  return { ana, ben, pa: wa.pid as string, pb: wb.pid as string, ga, gb };
}
const close = async (...phones: Phone[]) => { for (const p of phones) await p.context.close(); };

test('BLUFF on the game origin seats both players with tickets from the bridge and holds no Party identity', async ({ browser, request }) => {
  const { ana, ben, pa, pb, ga, gb } = await table(browser, request);
  expect(pa).not.toBe(pb);
  expect(ga.me.pid).toBe(pa);
  expect(gb.me.pid).toBe(pb);
  for (const p of [ana, ben]) {
    const l = await log(p.page);
    expect(hellos(l)).toHaveLength(1);
    expect(hellos(l)[0].ticket).toMatch(/^aps0\./);                // seated by a Party ticket
    expect(hellos(l)[0].token).toBeUndefined();
    expect(welcomes(l)[0].watch).toBeUndefined();
    // The Party is in the page only as its own invisible, sandboxed frame.
    const frame = p.page.locator('iframe[title="Avrana Party"]');
    await expect(frame).toHaveAttribute('src', `${PARTY}/party/bridge.html`);
    await expect(frame).toHaveAttribute('sandbox', 'allow-scripts allow-same-origin');
    await expect(frame).toBeHidden();
    // The game origin holds no cookie and nothing of the Party's profile or identity.
    expect(await p.page.evaluate(() => document.cookie)).toBe('');
    const stored = await p.page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
    for (const bad of ['member-', 'device-', 'participant-', 'avrana_device', 'avrana-profile']) expect(stored).not.toContain(bad);
    expect(p.direct).toEqual([]);                                  // the page never called the Party API
  }
  await close(ana, ben);
});

test('the game page cannot use the Party as itself: the game origin serves no Party and Party Core answers it nothing', async ({ browser, request }) => {
  const { ana, ben } = await table(browser, request);
  const tried = await ana.page.evaluate(async (party) => {
    const out: Record<string, string> = {};
    const post = { method: 'POST', credentials: 'include' as const, headers: { 'Content-Type': 'application/json' }, body: '{"game":"bluff"}' };
    for (const [name, url, init] of [
      ['own-origin ticket', '/party/api/session/ticket', post],
      ['own-origin state', '/party/api/state', { credentials: 'include' as const }],
      ['party ticket', `${party}/party/api/session/ticket`, post],
      ['party state', `${party}/party/api/state`, { credentials: 'include' as const }],
    ] as const) {
      try { out[name] = `answered ${(await fetch(url, init)).status}`; } catch { out[name] = 'blocked'; }
    }
    return out;
  }, PARTY);
  expect(tried).toEqual({ 'own-origin ticket': 'answered 404', 'own-origin state': 'answered 404',
    'party ticket': 'blocked', 'party state': 'blocked' });
  // and those attempts changed nothing: Ana still holds her seat
  expect((await latest(ana.page)).game.me.cards).toHaveLength(2);
  await close(ana, ben);
});

test('a reload on the game origin returns the same seat and hand with a fresh ticket from the bridge', async ({ browser, request }) => {
  const { ana, ben, pa, ga } = await table(browser, request);
  const first = hellos(await log(ana.page))[0].ticket;
  await ana.page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });   // nothing here identifies Ana
  await ana.page.reload();
  await expect.poll(async () => welcomes(await log(ana.page)).length).toBeGreaterThan(0);
  const l = await log(ana.page);
  expect(welcomes(l).at(-1).pid).toBe(pa);
  expect(hellos(l)[0].ticket).toMatch(/^aps0\./);
  expect(hellos(l)[0].ticket).not.toBe(first);
  const back = await playing(ana.page);
  expect(back.me.pid).toBe(pa);
  expect(back.me.cards).toEqual(ga.me.cards);
  expect(ana.direct).toEqual([]);
  await close(ana, ben);
});

test('a dropped socket on the game origin reconnects with a fresh ticket and never as a watcher', async ({ browser, request }) => {
  const { ana, ben, pa, ga } = await table(browser, request);
  const before = await log(ana.page);
  await ana.page.evaluate(() => (window as any).__avr.sockets.forEach((s: WebSocket) => s.close()));
  await expect.poll(async () => welcomes(await log(ana.page)).length).toBeGreaterThan(welcomes(before).length);
  const after = await log(ana.page);
  expect(welcomes(after).at(-1)).toEqual({ type: 'welcome', pid: pa });
  expect(hellos(after).at(-1).ticket).toMatch(/^aps0\./);
  expect(hellos(after).at(-1).ticket).not.toBe(hellos(before)[0].ticket);
  await expect.poll(async () => (await latest(ana.page))?.game?.me?.cards).toEqual(ga.me.cards);
  await close(ana, ben);
});

test('only the host has End in the table, and ending takes every phone to Party Home on the Party origin', async ({ browser, request }) => {
  const { ana, ben } = await table(browser, request);
  await expect(ana.page.locator('#party-end')).toBeVisible();
  await expect(ben.page.locator('#party-end')).toBeHidden();
  // The guest's page cannot end it: the bridge passes the verb on and Party Core refuses.
  const refused = await ben.page.evaluate(() => (window as any).AvranaParty.end());
  expect(refused.ok).toBe(false);
  expect((await latest(ana.page)).game.me.cards).toHaveLength(2);
  await ana.page.locator('#party-end').click();
  await ana.page.locator('#confirm-yes').click();
  await ana.page.waitForURL(`${PARTY}/party/`);
  await ben.page.waitForURL(`${PARTY}/party/`);
  const state = await (await ana.page.goto(`${PARTY}/party/api/state`))!.json();
  expect(state.state).toBe('lobby');
  await close(ana, ben);
});

test('a phone that is not in the party gets no seat on the game origin', async ({ browser, request }) => {
  const { ana, ben } = await table(browser, request);
  const eve = await phone(browser, 0);
  const welcome = await openBluff(eve.page);
  expect(welcome.watch).toBe(true);                                // a watcher: no ticket, no seat
  expect(hellos(await log(eve.page))[0].ticket).toBeUndefined();
  expect((await latest(eve.page))?.game?.me?.cards ?? []).toEqual([]);
  expect(eve.direct).toEqual([]);
  await close(ana, ben, eve);
});

test('the same pages on the Party origin keep the same-origin path: no bridge frame', async ({ browser, request }) => {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 0);
  await join(ana.page, 'Ana');
  await ana.page.goto(`${PARTY}/games/bluff/?avrana=1`);
  await expect.poll(async () => welcomes(await log(ana.page)).length).toBeGreaterThan(0);
  expect(await ana.page.locator('iframe[title="Avrana Party"]').count()).toBe(0);
  expect(await ana.page.evaluate(() => (window as any).AvranaIntegration.home)).toBe('/party/');
  await close(ana);
});
