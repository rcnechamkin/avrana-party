import { test, expect, type Page } from '@playwright/test';

/**
 * The Full Mode Party page (/party/) against the simulated Party (Tier 2).
 * Capabilities that depend on the browser build (H.264 in WebRTC) are pinned with an init script
 * so each state is tested on purpose, not by accident of the CI browser.
 */
const JARGON = /\b(seat|session|runtime|server|websocket|presence|manifest|launch(ing)?|backend|token|slot|capabilit(y|ies)|webrtc|h\.?264)\b/i;

async function h264(page: Page, supported: boolean) {
  await page.addInitScript((ok) => {
    const orig = RTCRtpReceiver.getCapabilities.bind(RTCRtpReceiver);
    RTCRtpReceiver.getCapabilities = (kind: string) => {
      const caps = orig(kind) || { codecs: [], headerExtensions: [] };
      if (kind !== 'video') return caps;
      const others = caps.codecs.filter((c: { mimeType: string }) => !/h264/i.test(c.mimeType));
      return { ...caps, codecs: ok ? [...others, { mimeType: 'video/H264', clockRate: 90000 }] : others };
    };
  }, supported);
}

async function arcade(page: Page, mode: 'up' | 'down' | 'full') {
  const res = await page.request.post(`/__test__/arcade/${mode}`);
  expect(res.status()).toBe(204);
}

async function open(page: Page) {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
}

test.beforeEach(async ({ page }) => arcade(page, 'up'));

test('a capable phone sees ready games and a secure connection', async ({ page }) => {
  await h264(page, true);
  await open(page);
  await expect(page.locator('#status')).toContainText('Connected to the party');
  await expect(page.locator('#secure')).toBeVisible();
  const card = page.locator('[data-id="arcade-gauntlet2"]');
  await expect(card).toContainText('Gauntlet II');
  await expect(card).toContainText('1–2 players');
  await expect(card).toContainText('Works on this phone');
  await expect(card).toContainText('1 of 2 playing');
  await expect(card.getByRole('link', { name: 'Play' })).toHaveAttribute('href', '/arcade/');
  await expect(page.locator('[data-id="lan-games"]').getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/');
  // Games that are not installed on this Party box stay out of the guest view.
  await expect(page.locator('[data-id="bluff"]')).toHaveCount(0);
  await page.locator('#phone summary').click();
  await expect(page.locator('#phone-summary')).toHaveText('All set');
  await expect(page.locator('#phone-list [data-cap="video.h264"]')).toHaveAttribute('data-status', 'yes');
});

test('a phone that cannot play the video is told why, and can still try', async ({ page }) => {
  await h264(page, false);
  await open(page);
  const card = page.locator('[data-id="arcade-gauntlet2"]');
  await expect(card).toHaveAttribute('data-outcome', 'unavailable');
  await expect(card).toContainText('Not on this phone');
  await expect(card).toContainText('This browser can’t play the Party’s video format.');
  await expect(card.getByRole('link', { name: 'Try anyway' })).toHaveAttribute('href', '/arcade/');
  await page.locator('#phone summary').click();
  await expect(page.locator('#phone-summary')).toHaveText('Some things are limited');
});

test('live game state: not running, and full', async ({ page }) => {
  await h264(page, true);
  await arcade(page, 'down');
  await open(page);
  const card = page.locator('[data-id="arcade-gauntlet2"]');
  await expect(card).toContainText('Not running right now');
  await expect(card.getByRole('button', { name: 'Play' })).toBeDisabled();
  await arcade(page, 'full');
  await page.reload();
  await expect(card).toContainText('Full right now');
});

test('guest words only, and basic accessibility', async ({ page }) => {
  await h264(page, false);
  await open(page);
  await page.locator('#phone summary').click();
  const text = await page.locator('main').innerText();
  expect(text).not.toMatch(JARGON);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  const small = await page.$$eval('main a.button, main button, summary', (els) => els
    .filter((el) => el.getClientRects().length > 0 && el.getBoundingClientRect().height < 44)
    .map((el) => el.textContent));
  expect(small).toEqual([]);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test('the offline copy: saved on this phone, and honest when the Pi is out of reach', async ({ page, context }) => {
  await open(page);
  const scope = await page.evaluate(async () => (await navigator.serviceWorker.ready).scope);
  expect(new URL(scope).pathname).toBe('/party/');
  await page.reload();
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
  await expect(page.locator('#phone-list [data-cap="offline_copy"]')).toHaveCount(1);

  await context.setOffline(true);
  await page.reload();
  await expect(page.locator('#away')).toBeVisible();
  await expect(page.locator('#status')).toContainText('Not connected to the party');
  await expect(page.locator('#games-section')).toBeHidden();
  await expect(page.getByRole('link', { name: 'Open the basic version' })).toHaveAttribute('href', 'http://10.42.0.1/');

  // Try again while still away: stays honest.
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.locator('#away')).toBeVisible();

  // Back on the Wi-Fi: the page recovers by itself (the 'online' event), no tap needed.
  await context.setOffline(false);
  await expect(page.locator('#away')).toBeHidden();
  await expect(page.locator('#status')).toContainText('Connected to the party');
  await expect(page.locator('[data-id="arcade-gauntlet2"]')).toBeVisible();
});

test('a refresh keeps keyboard focus on an unchanged card', async ({ page }) => {
  await h264(page, true);
  await open(page);
  const play = page.locator('[data-id="arcade-gauntlet2"]').getByRole('link', { name: 'Play' });
  await play.focus();
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));  // triggers a refresh
  await page.waitForTimeout(500);
  expect(await page.evaluate(() => document.activeElement?.textContent)).toBe('Play');
  await expect(play).toBeFocused();
});

test('the worker never controls the games hub', async ({ page }) => {
  await open(page);
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.goto('/');
  expect(await page.evaluate(() => navigator.serviceWorker.controller)).toBeNull();
});

test('#diag opens the diagnostics page', async ({ page }) => {
  await page.goto('/party/#diag');
  await expect(page).toHaveURL(/\/party\/diag\/$/);
  await expect(page.getByRole('heading', { name: 'Diagnostics' })).toBeVisible();
});
