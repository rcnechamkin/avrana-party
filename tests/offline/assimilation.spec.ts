import { test, expect, type Page } from '@playwright/test';
import { openGame, place } from '../lib/frame';

async function open(page: Page) {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
}
async function legacyProfile(page: Page) {
  await page.addInitScript(() => {
    if (!localStorage.getItem('wc-token')) {
      localStorage.setItem('wc-token', 'existing-player-01');
      localStorage.setItem('wc-name', 'Robin');
      localStorage.setItem('wc-avatar', '🐸');
      localStorage.setItem('lg-favorites', '["expo"]');
      localStorage.setItem('lg-recent', '["expo"]');
      localStorage.setItem('lg-play-total', '3');
    }
  });
}
test('legacy profile, favorites and history appear in the canonical shell', async ({ page }) => {
  await legacyProfile(page); await open(page);
  await expect(page.locator('#player-chip')).toContainText('Robin');
  // The legacy 🐸 character reads as the Gaze avatar at its position (docs/UI-DESIGN-SYSTEM.md).
  await expect(page.locator('#player-chip img')).toHaveAttribute('src', /\/party\/avatars\/gaze-02\.svg$/);
  await expect(page.locator('#game-count')).toHaveText('6 games'); // BLUFF, Checkers, EXPO, the arcade and two PS1 titles; no retired LAN Games title
  // Home leads with what this phone played last, from the same list the games have always written.
  await expect(page.locator('#home-lead [data-game="expo"]')).toContainText('You played this last.');
  await expect(page.locator('#home-recent-sec')).toBeHidden();              // one title played: it leads, and is not listed twice
  await place(page, 'library');
  const shelf = page.locator('#games [data-game]');
  await expect(shelf).toHaveCount(6);
  await expect(page.locator('#games [data-game="bluff"]')).toContainText('BLUFF');
  await expect(page.locator('#games [data-game="lan-games"]')).toHaveCount(0);
  await expect(page.locator('#games [data-game="expo"]')).toContainText('EXPO');
  await expect(page.locator('#games [data-game="ps1-worms"]')).toContainText('Worms Armageddon');
  await expect(page.locator('#games [data-game="ps1-worms"]')).toContainText('Not installed');
  await expect(await openGame(page, 'ps1-worms')).toContainText('Experimental');
  await expect((await openGame(page, 'ps1-bomberman')).locator('button', { hasText: 'Not installed' })).toBeDisabled();
  await place(page, 'library');
  await page.getByRole('button', { name: 'Favorites', exact: true }).click();
  await expect(shelf).toHaveCount(1);
  await expect(page.locator('#games')).toContainText('EXPO');
  await page.getByRole('button', { name: 'Recent', exact: true }).click();
  await expect(page.locator('#games')).toContainText('EXPO');
  await expect(shelf).toHaveCount(1);
});
test('profile edits and a direct legacy game visit share the same backing identity', async ({ page }) => {
  await legacyProfile(page); await open(page);
  await place(page, 'party');
  await page.locator('#player-chip').click();
  await page.locator('#profile-name').fill('Robin Two');
  const choice = page.locator('#avatar-choices [data-avatar="gaze-17"]');
  await choice.click();
  await expect(choice).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Save profile' }).click();
  await expect(page.locator('#player-chip')).toContainText('Robin Two');
  const snapshot = await page.evaluate(() => ({ token: localStorage.getItem('wc-token'),
    name: localStorage.getItem('wc-name'), avatar: localStorage.getItem('wc-avatar') }));
  expect(snapshot).toEqual({ token: 'existing-player-01', name: 'Robin Two', avatar: 'gaze-17' });
  await page.route('**/games/expo/?avrana=1', (route) => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><title>Legacy game stub</title><h1>Expo</h1>' }));
  await place(page, 'library');
  await (await openGame(page, 'expo')).getByRole('link', { name: 'Play', exact: true }).click();
  await expect(page).toHaveURL(/\/games\/expo\/\?avrana=1$/);
  // These are the exact getters in the inspected legacy Hub.identity implementation.
  expect(await page.evaluate(() => [localStorage.getItem('wc-token'), localStorage.getItem('wc-name'),
    localStorage.getItem('wc-avatar'), JSON.parse(localStorage.getItem('lg-recent') || '[]')[0],
    localStorage.getItem('lg-play-total')])).toEqual(['existing-player-01','Robin Two','gaze-17','avrana:expo','4']);
});
test('search, group size and cross-provider favorites work together', async ({ page }) => {
  await open(page);
  await place(page, 'library');
  await page.locator('#game-search').fill('worms');
  await expect(page.locator('#games [data-game]')).toHaveCount(1);
  const heart = (await openGame(page, 'ps1-worms')).getByRole('button', { name: /favorites/ });
  await heart.click();
  await expect(heart).toHaveAttribute('aria-pressed', 'true');
  await expect(heart).toBeFocused();                                       // the toggle keeps focus through the redraw
  await place(page, 'library');
  await page.locator('#game-search').fill('');
  await page.getByRole('button', { name: 'Favorites', exact: true }).click();
  await expect(page.locator('#games')).toContainText('Worms Armageddon');
  await page.getByRole('button', { name: 'All', exact: true }).click();
  await page.locator('#game-search').fill('gauntlet');
  const players = async (n: number) => {
    await page.locator('#lib-filter').click();
    await page.locator(`#filter-players [data-players="${n}"]`).click();
    await page.locator('#filters-show').click();
  };
  await players(5);
  await expect(page.locator('#games')).toContainText('No games match these filters');
  await players(4);
  await expect(page.locator('#games')).toContainText('Gauntlet II');
});
test('without a Party there is no chat: the old socket is never opened, nothing reconnects (AVR-54)', async ({ page }) => {
  await legacyProfile(page);
  let sockets = 0;
  page.on('websocket', (ws) => { if (ws.url().endsWith('/chat/ws')) sockets++; });
  await open(page);
  // Chat is the Party room, Party Core's own. With no Party Core here the catalog has no chat at
  // all: no chat mark, no Party chat row, and no connection to the retiring runtime's chat.
  await expect(page.locator('#hud')).toBeHidden();
  await place(page, 'party');
  await expect(page.locator('#party-chat-row')).toBeHidden();
  await page.waitForTimeout(500);
  expect(sockets).toBe(0);
});

test('missing donor service disables its titles without disabling the arcade or losing the profile', async ({ page }) => {
  await legacyProfile(page);
  await page.route('**/api/games', (route) => route.fulfill({ status: 502, body: 'down' }));
  let sockets = 0;
  page.on('websocket', (ws) => { if (ws.url().endsWith('/chat/ws')) sockets++; });
  await open(page);
  // Today's chat is served by that same runtime (ADR 0014 retires it): with it gone the shell
  // offers no chat at all, rather than a chat that reconnects for ever.
  await expect(page.locator('#hud')).toBeHidden();
  await place(page, 'party');
  await expect(page.locator('#party-chat-row')).toBeHidden();
  expect(sockets).toBe(0);
  await place(page, 'library');
  await expect(page.locator('#games [data-game="expo"]')).toContainText('Off for now');
  await expect(page.locator('#games [data-game="arcade-gauntlet2"]')).not.toContainText('Off for now');
  const expo = await openGame(page, 'expo');
  await expect(expo).toContainText('Not running right now');
  await expect(expo.getByRole('button', { name: 'Play', exact: true })).toBeDisabled();
  await expect((await openGame(page, 'arcade-gauntlet2')).getByRole('link')).toBeVisible();
  await expect(page.locator('#player-chip')).toContainText('Robin');
});
test('photo framing uses the shared avatar endpoint and removal handles failures honestly', async ({ page }) => {
  await legacyProfile(page);
  const uploads: string[] = [];
  let failDelete = true;
  await page.route('**/api/avatar', (route) => {
    uploads.push(route.request().headers()['x-wc-token']);
    if (route.request().method() === 'DELETE' && failDelete)
      return route.fulfill({ status: 503, body: 'offline' });
    return route.fulfill({ json: { url: '/avatars/0123456789abcdef0123.webp?v=12' } });
  });
  await open(page); await place(page, 'party'); await page.locator('#player-chip').click();
  const image = await page.evaluate(() => {
    const c = document.createElement('canvas'); c.width = 10; c.height = 20;
    const ctx = c.getContext('2d')!; ctx.fillStyle = 'red'; ctx.fillRect(0,0,10,20);
    return c.toDataURL('image/png').split(',')[1];
  });
  await page.locator('#profile-photo').setInputFiles({
    name: 'photo.png', mimeType: 'image/png', buffer: Buffer.from(image, 'base64') });
  await expect(page.locator('#photo-crop')).toBeVisible();
  await page.locator('#photo-zoom').fill('2');
  await page.locator('#photo-x').fill('75');
  await page.getByRole('button', { name: 'Use photo' }).click();
  await expect(page.locator('#player-chip img')).toHaveAttribute('src', '/avatars/0123456789abcdef0123.webp?v=12');
  await page.getByRole('button', { name: 'Remove photo' }).click();
  await expect(page.locator('#profile-note')).toContainText('Could not remove');
  await expect(page.locator('#player-chip img')).toHaveCount(1);
  failDelete = false;
  await page.getByRole('button', { name: 'Remove photo' }).click();
  // Without a photo the chip falls back to the player's Gaze avatar (was: an emoji character).
  await expect(page.locator('#player-chip img')).toHaveAttribute('src', /\/party\/avatars\/gaze-02\.svg$/);
  expect(uploads).toEqual(['existing-player-01','existing-player-01','existing-player-01']);
});

test('old donor fails honestly instead of entering a second global shell', async ({ page }) => {
  await page.route('**/api/games', (route) => route.fulfill({ json: { games: [{ slug: 'expo' }], external: [] } }));
  await open(page);
  await place(page, 'library');
  await expect(page.locator('#games [data-game="expo"]')).toContainText('Off for now');
  const expo = await openGame(page, 'expo');
  await expect(expo).toContainText('Games update needed');
  await expect(expo.getByRole('link', { name: 'Play' })).toHaveCount(0);
});
