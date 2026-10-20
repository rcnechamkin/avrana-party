import { test, expect as baseExpect, devices, type Browser, type Page } from '@playwright/test';
import { pathToFileURL } from 'node:url';
import { place, startForEveryone } from '../lib/frame';

// EXPERIMENTAL (AVR-676): any Python `.avrgame` package against the real Party. The harness
// (server.py --native-package) validates and stages it with the Party's own avrgame and
// install-game code, serves the effective catalog the installer would publish, and runs it as a
// socket-activated child of a real Party Core, on the game origin. Nothing here is title-specific:
//
//   AVRANA_NATIVE_PACKAGE=/path/game.avrgame [AVRANA_NATIVE_GRANTS=party_roster]
//   [AVRANA_NATIVE_DRIVER=/path/driver.mjs]   npx playwright test -c playwright.provider.config.ts native-package
//
// A driver (the game developer's, never committed here) plays the game through its page:
//   export async function step(page): 'done' | 'acted' | 'waiting'
// Without one, the full-game test is skipped. Linux only (Unix sockets). Chromium phone sizes are
// Tier 2 automation, not Safari, Android hardware or appliance acceptance; there is no systemd here.
const PORT = 8188;
const PARTY = `http://party.avrana.test:${PORT}`, GAMES = `http://games.avrana.test:${PORT}`;
const LOOPBACK = `http://127.0.0.1:${PORT}`;
const DRIVER = process.env.AVRANA_NATIVE_DRIVER;
test.beforeEach(({}, info) => test.skip(process.platform === 'win32' || !process.env.AVRANA_NATIVE_PACKAGE
  || info.project.name !== 'android-size', 'a package on Linux, with AVRANA_NATIVE_PACKAGE, once with both phone sizes'));
test.setTimeout(600_000);
const expect = baseExpect.configure({ timeout: 15_000 });

async function packageRow(request: any) {
  const catalog = await (await request.get(`${LOOPBACK}/party/catalog.json`)).json();
  const rows = catalog.games.filter((g: any) => g.tier === 'community');
  expect(rows).toHaveLength(1);
  return rows[0] as { id: string, players: { min: number, max: number } };
}

async function phone(browser: Browser, name: string, n = 0) {
  const { defaultBrowserType, ...device } = [devices['Pixel 7'], devices['iPhone 13']][n % 2] as any;
  const context = await browser.newContext({ ...device, serviceWorkers: 'block' });
  const page = await context.newPage();
  const direct: string[] = [], errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('request', r => {
    if (r.frame() === page.mainFrame() && page.url().startsWith(GAMES) && r.url().includes('/party/api/')) direct.push(r.url());
  });
  await page.addInitScript(() => {
    const original = window.fetch;
    (window as any).__pkg = { redeemed: [], tokens: [] };
    window.fetch = async (...args) => {
      const response = await original(...args);
      const url = String(args[0]);
      if (url.includes('api/redeem')) {
        try {
          const body = await response.clone().json();
          (window as any).__pkg.redeemed.push({ status: response.status, role: body.role, ok: body.ok });
          if (body.token) (window as any).__pkg.tokens.push(body.token);
        } catch { /* not JSON */ }
      }
      return response;
    };
  });
  await page.goto(`${PARTY}/party/`);
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await place(page, 'party');
  await page.locator('#player-chip').click();
  await page.locator('#profile-name').fill(name);
  await page.getByRole('button', { name: 'Save profile' }).click();
  await expect(page.locator('#party-members')).toContainText(`${name} (you)`);
  return { page, context, direct, errors };
}
const redeemed = (page: Page) => page.evaluate(() => (window as any).__pkg?.redeemed ?? []);
const token = (page: Page) => page.evaluate(() => (window as any).__pkg?.tokens.at(-1));
async function close(...phones: any[]) { for (const p of phones) if (p) await p.context.close(); }

// Ana and Ben always play. With `seats`, the game's remaining seats are filled first (Party Core seats
// members as players in join order up to the game's players.max), so that Cleo, the last to join, watches.
async function table(browser: Browser, request: any, id: string, seats = 0) {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 'Ana'), ben = await phone(browser, 'Ben', 1);
  const extra = [];
  for (let i = 2; i < seats; i++) extra.push(await phone(browser, `Seat ${i + 1}`, i));
  const cleo = seats ? await phone(browser, 'Cleo') : null;
  await startForEveryone(ana.page, id);
  // A package with a Party pregame (extensions."net.avrana.party".pregame) opens the Party's setup scene
  // first: everyone answers Play or Watch (a first Play shows the rules), then the Host starts. The catalog
  // row does not say which, so look for the scene. The flow itself is party-pregame.spec.ts's.
  await expect.poll(async () => ana.page.url().startsWith(GAMES) || await ana.page.locator('#scene-start').isVisible()).toBe(true);
  if (!ana.page.url().startsWith(GAMES)) {
    for (const p of [ana, ben, ...extra]) {
      await p.page.locator('#choose-play').click();
      const gotIt = p.page.locator('#rules').getByRole('button', { name: /I.ll play/ });
      await expect(p.page.locator('#choose-play[aria-pressed="true"]').or(gotIt)).toBeVisible();
      if (await gotIt.isVisible()) await gotIt.click();
      await expect(p.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'true');
    }
    if (cleo) {
      await cleo.page.locator('#choose-watch').click();
      await expect(cleo.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    }
    await expect(ana.page.locator('#scene-start')).toBeEnabled();
    await ana.page.locator('#scene-start').click();
  }
  for (const p of [ana, ben, ...extra, ...(cleo ? [cleo] : [])]) {
    await expect(p.page).toHaveURL(`${GAMES}/games/${id}/`);
    await expect.poll(async () => (await redeemed(p.page)).filter((r: any) => r.ok).length).toBeGreaterThan(0);
  }
  return { ana, ben, extra, cleo };
}

test('a package: seats through the bridge, isolated game origin, reload keeps the seat, Host End returns everyone', async ({ browser, request }) => {
  const { id, players } = await packageRow(request);
  const { ana, ben, extra, cleo } = await table(browser, request, id, Math.max(players.max, 2));
  try {
    for (const p of [ana, ben, ...extra]) expect((await redeemed(p.page)).at(-1).role).toBe('player');
    expect((await redeemed(cleo!.page)).at(-1).role).toBe('spectator');
    for (const p of [ana, ben, ...extra, cleo!]) {
      expect(await p.page.evaluate(() => document.cookie)).toBe('');
      expect(await p.context.cookies(GAMES)).toEqual([]);
      await expect(p.page.locator('iframe[title="Avrana Party"]')).toHaveAttribute('src', `${PARTY}/party/bridge.html`);
      expect(p.direct).toEqual([]);
    }
    const oldToken = await token(ana.page);
    await ana.page.reload();
    await expect.poll(async () => (await redeemed(ana.page)).filter((r: any) => r.ok).length).toBeGreaterThan(0);
    expect(await token(ana.page)).toBe(oldToken);                  // the same seat comes back
    // The kit's "End game for everyone" (the Host's; it asks the Party through the bridge).
    ana.page.once('dialog', (d) => d.accept());
    await ana.page.locator('#end').click();
    for (const p of [ana, ben, ...extra, cleo!]) await expect(p.page).toHaveURL(`${PARTY}/party/`);
    // The game's authority is gone with the session, whatever the phones do.
    expect((await request.post(`${LOOPBACK}/games/${id}/api/poll`, {
      headers: { Host: new URL(GAMES).host }, data: { token: oldToken, since: -1 },
    })).status()).toBe(403);
    for (const p of [ana, ben, ...extra, cleo!]) expect(p.errors).toEqual([]);
  } finally { await close(ana, ben, ...extra, cleo); }
});

test('a package played to its end by its driver: the Party accepts the signed result', async ({ browser, request }) => {
  test.skip(!DRIVER, 'AVRANA_NATIVE_DRIVER names the game developer\'s driver module');
  const driver = await import(pathToFileURL(DRIVER!).href);
  const { id } = await packageRow(request);
  const { ana, ben } = await table(browser, request, id);
  try {
    const deadline = Date.now() + 540_000;
    const done = new Set<Page>();
    while (done.size < 2 && Date.now() < deadline) {
      let acted = false;
      for (const p of [ana.page, ben.page]) {
        if (done.has(p)) continue;
        const said = await driver.step(p);
        if (said === 'done') done.add(p);
        if (said === 'acted') acted = true;
      }
      if (!acted) await ana.page.waitForTimeout(150);
    }
    expect(done.size).toBe(2);
    // Back to Party Home by the Host, then the Party's record of the round.
    await expect(ana.page.locator('#home')).toBeVisible();
    await ana.page.locator('#home').click();
    for (const p of [ana, ben]) await expect(p.page).toHaveURL(`${PARTY}/party/`);
    const state = await ana.page.evaluate(async () => (await fetch('/party/api/state')).json());
    expect(state.session.outcome).toBe('completed');
    expect(state.session.result_summary.players).toHaveLength(2);
    for (const p of [ana, ben]) expect(p.errors).toEqual([]);
  } finally { await close(ana, ben); }
});

// Party 1.0: the Party moves every page, never the game (ADR 0011). For any package, through the real Party:
// a late joiner is taken to the round and watches; a non-Host cannot end it; the Host's End (Party Core's own
// endpoint, not a game button) moves every page home, including one that was offline when it happened.
/** Party Core's API as the Party's own page calls it: a script-less Party document in the same browser context. */
async function partyApi(p: any) {
  const page = await p.context.newPage();
  await page.goto(`${PARTY}/party/api/state`);
  return {
    page,
    async post(path: string) {
      return page.evaluate(async (path: string) => {
        const state = await (await fetch('/party/api/state', { cache: 'no-store' })).json();
        const res = await fetch('/party/api/' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ if_version: state.version }) });
        return { status: res.status, body: await res.json().catch(() => null) };
      }, path);
    },
  };
}
test('a package follows the Party: a late joiner watches, only the Host ends, and End moves everyone, offline or not', async ({ browser, request }) => {
  const { id } = await packageRow(request);
  const { ana, ben } = await table(browser, request, id);
  let dana: any = null;
  try {
    dana = await phone(browser, 'Dana', 2);                           // joins Party Home while the round is on
    await expect(dana.page).toHaveURL(`${GAMES}/games/${id}/`);       // taken to the round, nobody pressed Join
    await expect.poll(async () => (await redeemed(dana.page)).filter((r: any) => r.ok).at(-1)?.role).toBe('spectator');
    const benApi = await partyApi(ben), anaApi = await partyApi(ana);
    const refused = await benApi.post('session/end');                 // not the Host: refused, nobody moves
    expect(refused.status).toBe(403);
    expect(refused.body.error).toBe('not_host');
    await benApi.page.close();
    for (const p of [ana, ben, dana]) await expect(p.page).toHaveURL(`${GAMES}/games/${id}/`);
    // Ben's page is offline (well inside away-grace) when the Host ends the round; back online, it follows.
    await ben.context.setOffline(true);
    expect((await anaApi.post('session/end')).status).toBe(200);
    await anaApi.page.close();
    for (const p of [ana, dana]) await expect(p.page).toHaveURL(`${PARTY}/party/`);
    await expect(ben.page).toHaveURL(`${GAMES}/games/${id}/`);        // the control: offline, it cannot have moved
    await ben.context.setOffline(false);
    await expect(ben.page).toHaveURL(`${PARTY}/party/`, { timeout: 60_000 });
    for (const p of [ana, ben, dana]) { expect(p.direct).toEqual([]); expect(p.errors).toEqual([]); }
  } finally { await close(ana, ben, dana); }
});
