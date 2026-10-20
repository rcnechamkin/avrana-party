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

async function packageId(request: any) {
  const catalog = await (await request.get(`${LOOPBACK}/party/catalog.json`)).json();
  const rows = catalog.games.filter((g: any) => g.tier === 'community');
  expect(rows).toHaveLength(1);
  return rows[0].id as string;
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

async function table(browser: Browser, request: any, id: string, spectator = false) {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 'Ana'), ben = await phone(browser, 'Ben', 1);
  const cleo = spectator ? await phone(browser, 'Cleo') : null;
  await startForEveryone(ana.page, id);
  for (const p of [ana, ben, ...(cleo ? [cleo] : [])]) {
    await expect(p.page).toHaveURL(`${GAMES}/games/${id}/`);
    await expect.poll(async () => (await redeemed(p.page)).filter((r: any) => r.ok).length).toBeGreaterThan(0);
  }
  return { ana, ben, cleo };
}

test('a package: seats through the bridge, isolated game origin, reload keeps the seat, Host End returns everyone', async ({ browser, request }) => {
  const id = await packageId(request);
  const { ana, ben, cleo } = await table(browser, request, id, true);
  try {
    expect((await redeemed(ana.page)).at(-1).role).toBe('player');
    expect((await redeemed(ben.page)).at(-1).role).toBe('player');
    expect((await redeemed(cleo!.page)).at(-1).role).toBe('spectator');
    for (const p of [ana, ben, cleo!]) {
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
    for (const p of [ana, ben, cleo!]) await expect(p.page).toHaveURL(`${PARTY}/party/`);
    // The game's authority is gone with the session, whatever the phones do.
    expect((await request.post(`${LOOPBACK}/games/${id}/api/poll`, {
      headers: { Host: new URL(GAMES).host }, data: { token: oldToken, since: -1 },
    })).status()).toBe(403);
    for (const p of [ana, ben, cleo!]) expect(p.errors).toEqual([]);
  } finally { await close(ana, ben, cleo); }
});

test('a package played to its end by its driver: the Party accepts the signed result', async ({ browser, request }) => {
  test.skip(!DRIVER, 'AVRANA_NATIVE_DRIVER names the game developer\'s driver module');
  const driver = await import(pathToFileURL(DRIVER!).href);
  const id = await packageId(request);
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
