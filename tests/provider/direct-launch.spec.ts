import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
// The LAN Games titles Party still routes and offers (ADR 0014, AVR-259): the retiring runtime's
// two Party games. Its other titles have no route through the front door and no tile.
const PARTY_TITLES = ['bluff', 'expo'];
const catalog = { games: JSON.parse(readFileSync('contracts/catalogs/lan-games.json', 'utf8')).games
  .filter((g: { slug: string }) => PARTY_TITLES.includes(g.slug)) };
const shell = JSON.parse(readFileSync('web/party/catalog.json', 'utf8'));
async function seed(page: Page) {
  await page.addInitScript(() => {
    if (!localStorage.getItem('wc-token')) {
      localStorage.setItem('wc-token', 'provider-test-player');
      localStorage.setItem('wc-name', 'Robin'); localStorage.setItem('wc-avatar', 'R');
      localStorage.setItem('lg-favorites', '["bluff","avrana:bluff"]');
      localStorage.setItem('lg-recent', '["bluff","avrana:bluff"]');
    }
  });
}
async function home(page: Page) {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
}

test('every title Party still routes has a mounted direct page and explicit integrated return', async ({ page }) => {
  await seed(page);
  expect(catalog.games.map((g: { slug: string }) => g.slug).sort()).toEqual(PARTY_TITLES);
  const errors: string[] = []; page.on('pageerror', (e) => errors.push(e.message));
  for (const game of catalog.games) {
    const response = await page.goto(game.launch + '?avrana=1');
    expect(response?.status(), game.slug).toBe(200);
    await expect(page.locator('#avrana-navigation a')).toHaveAttribute('href', '/party/');
    await expect(page.locator('#avrana-navigation a')).toBeVisible();
    const geometry = await page.evaluate(() => {
      const nav = document.getElementById('avrana-navigation')!.getBoundingClientRect();
      const room = document.getElementById('avrana-game-room')!.getBoundingClientRect();
      return { navBottom: nav.bottom, roomTop: room.top, roomBottom: room.bottom, height: innerHeight };
    });
    expect(geometry.roomTop).toBeGreaterThanOrEqual(geometry.navBottom);
    expect(geometry.roomBottom).toBeLessThanOrEqual(geometry.height + 1);
    await expect(page.locator('.suite-home[href="/"]')).toHaveCount(0);
    await expect(page.locator('a[href="/"]')).toHaveCount(0);
    expect(await page.evaluate(() => localStorage.getItem('wc-token'))).toBe('provider-test-player');
  }
  expect(errors).toEqual([]);
});

test('no retired LAN Games title is offered by Party Home', async ({ page }) => {
  await seed(page); await home(page);
  expect(shell.games.filter((g: { provider: string }) => g.provider === 'lan-games').map((g: { id: string }) => g.id).sort()).toEqual(PARTY_TITLES);
  await expect(page.locator('[data-id^="lan-"]')).toHaveCount(0);
  for (const id of PARTY_TITLES) await expect(page.locator(`[data-id="${id}"]`)).toHaveCount(1);
});

test('a shell profile edit reaches a game page, and the return to Party survives a refresh', async ({ page }) => {
  await seed(page); await home(page);
  const hellos: any[] = [];
  page.on('websocket', (ws) => ws.on('framesent', ({ payload }) => {
    try { const msg = JSON.parse(String(payload)); if (msg.t === 'hello') hellos.push(msg); } catch {}
  }));
  await page.locator('#player-chip').click();
  await page.locator('#profile-name').fill('Robin Updated');
  await page.getByRole('button', { name: 'Save profile' }).click();
  await page.goto('/games/expo/?avrana=1');
  await expect.poll(() => hellos.some((m) => m.name === 'Robin Updated' && m.token === 'provider-test-player')).toBe(true);
  await page.reload();
  await expect(page.locator('#avrana-navigation a')).toBeVisible();
  await page.locator('#avrana-navigation a').click();
  await expect(page).toHaveURL(/\/party\/$/);
  await expect(page.locator('#player-chip')).toContainText('Robin Updated');
});

test('one real Party Chat history survives a game visit; game opens no global chat connection', async ({ page }) => {
  await seed(page); await home(page);
  let globalSockets = 0;
  page.on('websocket', (ws) => { if (ws.url().endsWith('/chat/ws')) globalSockets++; });
  await page.locator('#chat summary').click();
  await expect(page.locator('#chat-send')).toBeEnabled();
  const message = 'Across the boundary ' + Date.now();
  await page.locator('#chat-text').fill(message); await page.locator('#chat-send').click();
  await expect(page.locator('#chat-messages')).toContainText(message);
  await page.goto('/games/expo/?avrana=1');
  await expect(page.locator('#avrana-navigation a')).toBeVisible();
  await expect(page.locator('#edit-profile-btn')).toBeHidden();
  expect(globalSockets).toBe(1);
  await page.locator('#avrana-navigation a').click();
  await page.locator('#chat summary').click();
  await expect(page.locator('#chat-messages')).toContainText(message);
});

// A standalone game page still ships while that runtime retires; the hub page at / does not.
test('a standalone game page registers the root worker, which leaves the Avrana cache and scope alone', async ({ page }) => {
  await seed(page); await home(page);
  await expect.poll(() => page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).map((r) => new URL(r.scope).pathname))).toContain('/party/');
  await expect.poll(() => page.evaluate(async () => (await caches.keys()).some((k) => k.startsWith('avrana-party-shell-')))).toBe(true);
  const cachesBefore = await page.evaluate(() => caches.keys());
  await page.goto('/games/bluff/');
  await expect(page.locator('#avrana-navigation')).toHaveCount(0);
  await expect.poll(() => page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).map((r) => new URL(r.scope).pathname))).toContain('/');
  await page.evaluate(async () => { const r = await navigator.serviceWorker.getRegistration('/'); if (!r?.active) await navigator.serviceWorker.ready; });
  const after = await page.evaluate(() => caches.keys());
  expect(cachesBefore.filter((k) => k.startsWith('avrana-party-shell-')).length).toBeGreaterThan(0);
  for (const key of cachesBefore.filter((k) => k.startsWith('avrana-party-shell-'))) expect(after).toContain(key);
  expect(await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).map((r) => new URL(r.scope).pathname))).toContain('/party/');
  await page.goto('/games/expo/?avrana=1');
  await expect(page.locator('#avrana-navigation a')).toBeVisible();
  await expect(page.locator('.suite-home[href="/"]')).toHaveCount(0);
  await page.locator('#avrana-navigation a').click();
  await expect(page.locator('#player-chip')).toContainText('Robin');
});
