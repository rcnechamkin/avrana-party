import { test, expect, type Page } from '@playwright/test';
import { place } from '../lib/frame';

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
  await expect(page.locator('#game-count')).toHaveText('5 games'); // BLUFF, EXPO, the arcade and two PS1 titles; no retired LAN Games title
  await expect(page.locator('[data-id="bluff"]')).toContainText('BLUFF');
  await expect(page.locator('[data-id="lan-games"]')).toHaveCount(0);
  await expect(page.locator('[data-id="expo"]')).toContainText('EXPO');
  await expect(page.locator('[data-id="ps1-worms"]')).toContainText('Worms Armageddon');
  await expect(page.locator('[data-id="ps1-worms"]')).toContainText('Experimental');
  await expect(page.locator('[data-id="ps1-bomberman"] button', { hasText: 'Not installed' })).toBeDisabled();
  await place(page, 'library');
  await page.getByRole('button', { name: 'Favorites', exact: true }).click();
  await expect(page.locator('#games > li')).toHaveCount(1);
  await expect(page.locator('#games')).toContainText('EXPO');
  await page.getByRole('button', { name: 'Recently opened', exact: true }).click();
  await expect(page.locator('#games')).toContainText('EXPO');
  await expect(page.locator('#games > li')).toHaveCount(1);
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
  await page.locator('[data-id="expo"]').getByRole('link', { name: 'Play', exact: true }).click();
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
  await expect(page.locator('#games > li')).toHaveCount(1);
  await page.locator('[data-id="ps1-worms"]').getByRole('button', { name: /to favorites/ }).click();
  await page.locator('#game-search').fill('');
  await page.getByRole('button', { name: 'Favorites', exact: true }).click();
  await expect(page.locator('#games')).toContainText('Worms Armageddon');
  await page.getByRole('button', { name: 'All games', exact: true }).click();
  await page.locator('#game-search').fill('gauntlet');
  await page.locator('#game-players').selectOption('4');
  await expect(page.locator('#games')).toContainText('No games match');
  await page.locator('#game-players').selectOption('2');
  await expect(page.locator('#games')).toContainText('Gauntlet II');
});
test('Party Chat, in the drawer, uses the same hello and server echo, then reconnects after a profile edit', async ({ page }) => {
  await legacyProfile(page);
  const hellos: any[] = [];
  await page.routeWebSocket('**/chat/ws', (ws) => {
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (msg.t === 'hello') {
        hellos.push(msg);
        ws.send(JSON.stringify({ type: 'welcome', you: 'hashed-uid' }));
        ws.send(JSON.stringify({ type: 'history', messages: [
          { id: 1, by: 'other-uid', name: 'Casey', avatar: '🦊', pfp: null,
            text: 'Hello from the games', ts: 1234 }] }));
        ws.send(JSON.stringify({ type: 'presence', online: 2 }));
      } else if (msg.t === 'msg') ws.send(JSON.stringify({ type: 'msg', id: 2,
        by: 'hashed-uid', name: hellos.at(-1).name, avatar: hellos.at(-1).avatar,
        text: msg.text, pfp: null, ts: 2345 }));
    });
  });
  await open(page);
  // No Party here, only the old chat: the Party control is a chat mark and opens straight to it.
  await expect(page.locator('#hud')).toHaveAccessibleName('Party chat');
  expect(hellos).toHaveLength(0);                                        // connected only while it is on screen
  await page.locator('#hud').click();
  await expect(page.locator('#social')).toBeVisible();
  await expect(page.locator('#social-tabs')).toBeHidden();               // nobody to list: no People side
  await expect(page.locator('#chat-status')).toHaveText('2 in chat');
  await expect(page.locator('#chat-messages')).toContainText('Hello from the games');
  expect(hellos[0]).toEqual({ t: 'hello', token: 'existing-player-01', name: 'Robin', avatar: 'gaze-02' });
  await page.locator('#chat-text').fill('<b>Hello Party</b>');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.locator('#chat-messages')).toContainText('<b>Hello Party</b>');
  await expect(page.locator('#chat-messages b')).toHaveCount(0);
  await expect(page.locator('#chat-messages li')).toHaveCount(2);
  // Escape closes the drawer, gives focus back to the control that opened it, and ends the connection.
  await page.keyboard.press('Escape');
  await expect(page.locator('#social')).toBeHidden();
  await expect(page.locator('#hud')).toBeFocused();
  await expect(page.locator('#chat-send')).toBeDisabled();
  await place(page, 'party');
  await page.locator('#player-chip').click();
  await page.locator('#profile-name').fill('Robin Two');
  await page.getByRole('button', { name: 'Save profile' }).click();
  // The Party page's own row opens the same chat, under the new name and the same identity.
  await page.locator('#party-chat').click();
  await expect.poll(() => hellos.at(-1)?.name).toBe('Robin Two');
  expect(hellos.at(-1).token).toBe(hellos[0].token);
  await page.locator('#social-close').click();
  await expect(page.locator('#social')).toBeHidden();
  await expect(page.locator('#chat-send')).toBeDisabled();
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
  await expect(page.locator('[data-id="expo"]')).toContainText('Not running right now');
  await expect(page.locator('[data-id="expo"]').getByRole('button', { name: 'Play', exact: true })).toBeDisabled();
  await expect(page.locator('[data-id="arcade-gauntlet2"]').getByRole('link')).toBeVisible();
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
  await expect(page.locator('[data-id="expo"]')).toContainText('Games update needed');
  await expect(page.locator('[data-id="expo"]').getByRole('link', { name: 'Play' })).toHaveCount(0);
});
