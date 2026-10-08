import { test, expect as baseExpect, devices, type Browser, type Page } from '@playwright/test';
import { place, startForEveryone } from '../lib/frame';

// Real Party + real Unix-socket child, two isolated origins and the real bridge frame.
// Chromium phone sizes are Tier 2 automation, not Safari/Android hardware acceptance.
const PARTY = 'http://party.avrana.test:8185', GAMES = 'http://games.avrana.test:8185';
const LOOPBACK = 'http://127.0.0.1:8185';
test.beforeEach(({}, info) => test.skip(process.platform === 'win32' || info.project.name !== 'android-size',
  'native Unix processes on Linux, once with both phone sizes'));
test.setTimeout(240_000);
const expect = baseExpect.configure({ timeout: 15_000 });

async function phone(browser: Browser, name: string, n = 0) {
  const { defaultBrowserType, ...device } = [devices['Pixel 7'], devices['iPhone 13']][n % 2] as any;
  const context = await browser.newContext({ ...device, serviceWorkers: 'block' });
  const page = await context.newPage();
  const direct: string[] = [];
  page.on('request', r => {
    if (r.frame() === page.mainFrame() && page.url().startsWith(GAMES) && r.url().includes('/party/api/')) direct.push(r.url());
  });
  await page.addInitScript(() => {
    const original = window.fetch;
    (window as any).__native = { views: [], tokens: [], tickets: [], polls: 0 };
    window.fetch = async (...args) => {
      const response = await original(...args);
      const url = String(args[0]);
      if (url.includes('api/')) {
        try {
          const body = await response.clone().json();
          if (url.includes('api/poll') && response.ok) (window as any).__native.polls++;
          if (body.view) (window as any).__native.views.push(body.view);
          if (body.token) (window as any).__native.tokens.push(body.token);
          if (url.includes('api/redeem')) (window as any).__native.tickets.push(JSON.parse(String(args[1]?.body)).ticket);
        } catch { /* non-JSON or refused reply */ }
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
  return { page, context, direct };
}
const latest = (page: Page) => page.evaluate(() => (window as any).__native?.views.at(-1));
const token = (page: Page) => page.evaluate(() => (window as any).__native.tokens.at(-1));
async function table(browser: Browser, request: any, spectator = false) {
  expect((await request.post(`${LOOPBACK}/__harness__/party/reset`)).ok()).toBe(true);
  const ana = await phone(browser, 'Ana'), ben = await phone(browser, 'Ben', 1);
  const cleo = spectator ? await phone(browser, 'Cleo') : null;
  await startForEveryone(ana.page, 'checkers');
  for (const p of [ana, ben, ...(cleo ? [cleo] : [])]) {
    await expect(p.page).toHaveURL(`${GAMES}/games/checkers/?avrana=1`);
    await expect.poll(() => latest(p.page)).toBeTruthy();
  }
  return { ana, ben, cleo };
}
async function gamePost(page: Page, path: string, body: any) {
  return page.evaluate(async ({ path, body }) => {
    const r = await fetch('api/' + path, { method: 'POST', credentials: 'omit', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    return { status: r.status, body: await r.json() };
  }, { path, body });
}
async function move(page: Page, path: number[], before: number) {
  await page.locator(`[data-sq="${path[0]}"][data-movable]`).click();
  // The page may offer a full jump destination or require intermediate choices for branches.
  for (let i = 1; i < path.length; i++) {
    const final = page.locator(`[data-sq="${path.at(-1)}"][data-target]`);
    if (await final.count()) { await final.click(); break; }
    const next = page.locator(`[data-sq="${path[i]}"][data-target]`);
    // A branch choice can uniquely select the entire multi-jump before its final landing.
    if (!(await next.count())) break;
    await next.click();
  }
  await expect.poll(async () => (await latest(page))?.v).toBeGreaterThan(before);
}
async function close(...phones: any[]) { for (const p of phones) if (p) await p.context.close(); }

test('native Checkers: seats, controls, spectator, illegal input, reload, reconnect and Host End through bridge', async ({ browser, request }) => {
  const { ana, ben, cleo } = await table(browser, request, true);
  try {
    expect((await latest(ana.page)).seat).toBe('w');
    expect((await latest(ben.page)).seat).toBe('b');
    expect((await latest(ben.page)).moves).toEqual([]);
    expect((await latest(cleo!.page)).seat).toBeNull();
    expect((await latest(cleo!.page)).moves).toEqual([]);
    for (const p of [ana, ben, cleo!]) {
      expect(await p.page.evaluate(() => document.cookie)).toBe('');
      // Browser storage sees HttpOnly cookies too; document.cookie alone cannot prove this.
      expect(await p.context.cookies(GAMES)).toEqual([]);
      await expect(p.page.locator('iframe[title="Avrana Party"]')).toHaveAttribute('src', `${PARTY}/party/bridge.html`);
      expect(p.direct).toEqual([]);
    }
    const first = await latest(ana.page), oldToken = await token(ana.page);
    const illegal = await gamePost(ana.page, 'move', { token: oldToken, v: first.v, move: [0, 1] });
    expect(illegal.status).toBe(409);
    expect(illegal.body.view.board).toEqual(first.board);
    expect((await gamePost(cleo!.page, 'move', { token: await token(cleo!.page), v: first.v, move: first.moves[0] })).status).toBe(403);
    await move(ana.page, first.moves[0], first.v);
    await expect.poll(async () => (await latest(ben.page))?.v).toBe(first.v + 1);
    const board = (await latest(ben.page)).board;
    await ana.page.reload();
    await expect.poll(async () => (await latest(ana.page))?.board).toEqual(board);
    expect(await token(ana.page)).toBe(oldToken);
    const beforeReconnect = await ben.page.evaluate(() => (window as any).__native.polls);
    await ben.context.setOffline(true);
    // Wake while disconnected, forcing the existing long poll to fail and retry.
    await ben.page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await expect(ben.page.locator('#status')).toContainText('Reconnecting');
    await ben.context.setOffline(false);
    await ben.page.evaluate(() => window.dispatchEvent(new Event('online')));
    await expect.poll(() => ben.page.evaluate(() => (window as any).__native.polls)).toBeGreaterThan(beforeReconnect);
    await expect.poll(async () => (await latest(ben.page))?.board).toEqual(board);
    await expect(ben.page.locator('#status')).not.toContainText('Reconnecting');
    const recovered = await latest(ben.page);
    await move(ben.page, recovered.moves[0], recovered.v);
    await expect.poll(async () => (await latest(ana.page))?.v).toBe(recovered.v + 1);
    await ana.page.locator('#end').click();
    await ana.page.locator('#confirm-yes').click();
    for (const p of [ana, ben, cleo!]) await expect(p.page).toHaveURL(`${PARTY}/party/`);
    // Old game authority was torn down, independently of phone navigation.
    expect((await request.post(`${GAMES}/games/checkers/api/poll`, { data: { token: oldToken, since: -1 } })).status()).toBe(403);
  } finally { await close(ana, ben, cleo); }
});

test('a complete legal match reports signed results to Party and both phones return home; stale admission cannot start another match', async ({ browser, request }) => {
  const { ana, ben } = await table(browser, request);
  try {
    const staleTicket = await ana.page.evaluate(() => (window as any).__native.tickets[0]);
    const oldToken = await token(ana.page);
    let seed = 7;
    for (let ply = 0; ply < 500; ply++) {
      const view = await latest(ana.page);
      if (view.result) break;
      const actor = view.turn === 'w' ? ana.page : ben.page;
      await expect.poll(async () => (await latest(actor))?.v).toBe(view.v);
      const own = await latest(actor);
      expect(own.moves.length).toBeGreaterThan(0);
      seed = (seed * 1664525 + 1013904223) >>> 0;
      await move(actor, own.moves[seed % own.moves.length], own.v);
      await expect.poll(async () => (await latest(ana.page))?.v).toBeGreaterThan(own.v);
    }
    expect((await latest(ana.page)).result).toBeTruthy();
    await expect(ana.page.locator('#home')).toBeVisible();
    await ana.page.locator('#home').click();
    for (const p of [ana, ben]) await expect(p.page).toHaveURL(`${PARTY}/party/`);
    const state = await ana.page.evaluate(async () => (await fetch('/party/api/state')).json());
    expect(state.session.outcome).toBe('completed');
    expect(state.session.result_summary.players).toHaveLength(2);
    // Party's public result display is checked, not only its JSON record.
    await expect(ana.page.locator('#party-result')).toContainText(/Checkers:.*(won|draw)/);
    await startForEveryone(ana.page, 'checkers');
    await expect(ana.page).toHaveURL(`${GAMES}/games/checkers/?avrana=1`);
    expect((await gamePost(ana.page, 'redeem', { ticket: staleTicket })).status).toBe(403);
    expect((await gamePost(ana.page, 'poll', { token: oldToken, since: -1 })).status).toBe(403);
  } finally { await close(ana, ben); }
});
