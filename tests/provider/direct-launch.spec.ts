import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
const catalog = JSON.parse(readFileSync('contracts/catalogs/lan-games.json', 'utf8'));
async function seed(page: Page) {
  await page.addInitScript(() => {
    if (!localStorage.getItem('wc-token')) {
      localStorage.setItem('wc-token', 'provider-test-player');
      localStorage.setItem('wc-name', 'Robin'); localStorage.setItem('wc-avatar', 'R');
      localStorage.setItem('lg-favorites', '["chess","avrana:lan-chess"]');
      localStorage.setItem('lg-recent', '["chess","avrana:lan-chess"]');
    }
  });
}
async function home(page: Page) {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
}

test('every authoritative title has a mounted direct page and explicit integrated return', async ({ page }) => {
  await seed(page);
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

test('shell edits reach an actual chess join, library stays canonical, return survives refresh', async ({ page }) => {
  await seed(page); await home(page);
  const hellos: any[] = [];
  page.on('websocket', (ws) => ws.on('framesent', ({ payload }) => {
    try { const msg = JSON.parse(String(payload)); if (msg.t === 'hello') hellos.push(msg); } catch {}
  }));
  await page.locator('#player-chip').click();
  await page.locator('#profile-name').fill('Robin Updated');
  await page.getByRole('button', { name: 'Save profile' }).click();
  await page.locator('[data-id="lan-chess"]').getByRole('link', { name: 'Play', exact: true }).click();
  await expect(page).toHaveURL(/\/games\/chess\/\?avrana=1$/);
  await expect(page.locator('#scr-lobby')).toBeVisible();
  await expect.poll(() => hellos.some((m) => m.name === 'Robin Updated' && m.token === 'provider-test-player')).toBe(true);
  await expect(page.locator('#pfp-btn2')).toBeHidden();
  await page.reload();
  await expect(page.locator('#avrana-navigation a')).toBeVisible();
  await page.locator('#avrana-navigation a').click();
  await expect(page).toHaveURL(/\/party\/$/);
  await expect(page.locator('#player-chip')).toContainText('Robin Updated');
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('lg-recent') || '[]'))).toEqual(['avrana:lan-chess']);
  await page.getByRole('button', { name: 'Favorites', exact: true }).click();
  await expect(page.locator('#games > li')).toHaveCount(1);
  await page.locator('[data-id="lan-chess"]').getByRole('button', { name: /from favorites/ }).click();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('lg-favorites') || '[]'))).toEqual([]);
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
  await page.locator('[data-id="lan-wordclash"]').getByRole('link', { name: 'Play', exact: true }).click();
  await expect(page.locator('#avrana-navigation a')).toBeVisible();
  await expect(page.locator('#edit-profile-btn')).toBeHidden();
  expect(globalSockets).toBe(1);
  await page.locator('#avrana-navigation a').click();
  await page.locator('#chat summary').click();
  await expect(page.locator('#chat-messages')).toContainText(message);
});

test('standalone remains usable and its root worker preserves Avrana cache and scope', async ({ page }) => {
  await seed(page); await home(page);
  await expect.poll(() => page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).map((r) => new URL(r.scope).pathname))).toContain('/party/');
  const cachesBefore = await page.evaluate(() => caches.keys());
  await page.goto('/games/chess/');
  await expect(page.locator('#avrana-navigation')).toHaveCount(0);
  await expect(page.locator('#scr-lobby')).toBeVisible();
  await expect(page.locator('#scr-lobby a[href="/"]')).toBeVisible();
  await expect.poll(() => page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).map((r) => new URL(r.scope).pathname))).toContain('/');
  await page.evaluate(async () => { const r = await navigator.serviceWorker.getRegistration('/'); if (!r?.active) await navigator.serviceWorker.ready; });
  const after = await page.evaluate(() => caches.keys());
  for (const key of cachesBefore.filter((k) => k.startsWith('avrana-party-shell-'))) expect(after).toContain(key);
  await page.goto('/games/chess/?avrana=1');
  await expect(page.locator('#avrana-navigation a')).toBeVisible();
  await expect(page.locator('.suite-home[href="/"]')).toHaveCount(0);
  await page.locator('#avrana-navigation a').click();
  await expect(page.locator('#player-chip')).toContainText('Robin');
});

test('standalone hub reads canonical favorites without creating duplicate IDs', async ({ page }) => {
  await seed(page); await home(page);
  await page.locator('[data-id="lan-chess"]').getByRole('button', { name: /from favorites/ }).click();
  await page.locator('[data-id="lan-chess"]').getByRole('button', { name: /to favorites/ }).click();
  await page.goto('/');
  const favorite = page.locator('#rails .tile[data-slug="chess"] .tile-fav');
  await expect(favorite).toHaveAttribute('aria-label', 'remove from favorites');
  await favorite.click();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('lg-favorites') || '[]'))).toEqual([]);
  await favorite.click();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('lg-favorites') || '[]'))).toEqual(['avrana:lan-chess']);
  await home(page);
  await page.getByRole('button', { name: 'Favorites', exact: true }).click();
  await expect(page.locator('#games > li')).toHaveCount(1);
});

test('game TV links and QR handoff preserve the explicit Party launch context', async ({ page }) => {
  await seed(page);
  await page.goto('/games/fifthsignal/?avrana=1');
  await expect(page.locator('[data-avrana-game-link]').first()).toHaveAttribute('href', '/games/fifthsignal/tv.html?avrana=1');
  await page.route('**/shared/qr.js', (route) => route.fulfill({ contentType: 'text/javascript',
    body: 'function renderQR(el, url) { el.dataset.testJoin = url; }' }));
  await page.goto('/games/orbitriot/tv.html?avrana=1');
  await expect(page.locator('#tv-qr')).toHaveAttribute('data-test-join', 'http://127.0.0.1:8182/games/orbitriot/?avrana=1');
  await expect(page.locator('#avrana-navigation a')).toBeVisible();
});
