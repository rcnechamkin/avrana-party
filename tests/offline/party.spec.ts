import { test, expect, type Page } from '@playwright/test';
import { openGame, place, sideways, smallTargets } from '../lib/frame';

/**
 * The Full Mode Party page (/party/) against the simulated Party (Tier 2). The page is a frame
 * with four places (Home, Party, Library, System); the games are in the Library and "This phone"
 * is in System.
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
  await place(page, 'library');
  await expect(page.locator('#games [data-game]')).toHaveCount(6);
  await expect(page.locator('#games [data-game^="lan-"]')).toHaveCount(0);       // no retired LAN Games title is offered
  await expect(page.locator('#games [data-game="ps1-worms"]')).toContainText('Not installed');
  await expect(page.locator('#games [data-game="arcade-gauntlet2"]')).not.toHaveAttribute('data-note', /.+/);
  const card = await openGame(page, 'arcade-gauntlet2');
  await expect(card).toContainText('Gauntlet II');
  await expect(card).toContainText('1–4 players');
  await expect(card).toContainText('Works on this phone');
  await expect(card).toContainText('1 of 4 playing');
  await expect(card.getByRole('link', { name: 'Play' })).toHaveAttribute('href', '/arcade/');
  await expect((await openGame(page, 'expo')).getByRole('link', { name: 'Play' })).toHaveAttribute('href', '/games/expo/?avrana=1');
  // BLUFF is installed: listed with its own art and launched through the Avrana-integrated path.
  await expect(page.locator('#games [data-game="bluff"] img[src$="art/lan-bluff.svg"]')).toHaveCount(1);
  const bluff = await openGame(page, 'bluff');
  await expect(bluff).toContainText('BLUFF');
  await expect(bluff.locator('img[src$="art/lan-bluff.svg"]')).toHaveCount(1);
  await expect(bluff.getByRole('link', { name: 'Play' })).toHaveAttribute('href', '/games/bluff/?avrana=1');
  await page.keyboard.press('Escape');
  await place(page, 'system');
  await expect(page.locator('#phone-summary')).toHaveText('All set');
  await expect(page.locator('#phone-list [data-cap="video.h264"]')).toHaveAttribute('data-status', 'yes');
});

test('a phone that cannot play the video is told why, and can still try', async ({ page }) => {
  await h264(page, false);
  await open(page);
  await place(page, 'library');
  await expect(page.locator('#games [data-game="arcade-gauntlet2"]')).toContainText('Not on this phone');   // said on the shelf
  const card = await openGame(page, 'arcade-gauntlet2');
  await expect(card).toHaveAttribute('data-outcome', 'unavailable');
  await expect(card).toContainText('Not on this phone');
  await expect(card).toContainText('This browser can’t play the Party’s video format.');
  await expect(card.getByRole('link', { name: 'Try anyway' })).toHaveAttribute('href', '/arcade/');
  await page.keyboard.press('Escape');
  await place(page, 'system');
  await expect(page.locator('#phone-summary')).toHaveText('Some things are limited');
});

test('live game state: not running, and full', async ({ page }) => {
  await h264(page, true);
  await arcade(page, 'down');
  await open(page);
  await place(page, 'library');
  const tile = page.locator('#games [data-game="arcade-gauntlet2"]');
  await expect(tile).toContainText('Off for now');                         // said on the shelf, before anyone opens it
  let card = await openGame(page, 'arcade-gauntlet2');
  await expect(card).toContainText('Not running right now');
  await expect(card.getByRole('button', { name: 'Play' })).toBeDisabled();
  await arcade(page, 'full');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(tile).not.toContainText('Off for now');
  card = await openGame(page, 'arcade-gauntlet2');
  await expect(card).toContainText('Full right now');
});

test('guest words only, and basic accessibility', async ({ page }) => {
  await h264(page, false);
  await open(page);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  for (const name of ['home', 'party', 'library', 'system'] as const) {
    await place(page, name);
    expect(await page.locator('#main').innerText(), name).not.toMatch(JARGON);
    // every control in the frame, bars included: at least 44 px each way
    expect(await smallTargets(page, '#main a, #main button, #main summary, #main select, #main input:not([type="range"])'), name).toEqual([]);
    expect(await sideways(page), name).toBeLessThanOrEqual(0);
  }
});

test('the frame: four places in one page, and the bar says which one you are in', async ({ page }) => {
  await open(page);
  await expect(page.locator('html')).toHaveAttribute('data-place', 'home');
  await expect(page.locator('#top-title')).toHaveText('Avrana Party');
  await expect(page.locator('#nav a[aria-current="page"]')).toHaveText('Home');
  for (const [name, title] of [['party', 'Party'], ['library', 'Library'], ['system', 'System']] as const) {
    await place(page, name);
    await expect(page.locator('#top-title')).toHaveText(title);
    await expect(page.locator('#top-title')).toBeFocused();              // a screen reader hears the new place
    await expect(page.locator('#nav a[aria-current="page"]')).toHaveText(title);
    await expect(page.locator('#nav a[aria-current="page"]')).toHaveCount(1);
    await expect(page).toHaveTitle(`${title} · Avrana Party`);
    await expect(page.locator(`#view-${name}`)).toBeVisible();
    await expect(page.locator('#view-home')).toBeHidden();
  }
  // one document: no load between places, and the phone's Back goes to the place before
  await page.goBack();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'library');
  // a reload stays where it was; an address the frame does not know is Home
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('html')).toHaveAttribute('data-place', 'library');
  await expect(page.locator('#games [data-game="arcade-gauntlet2"]')).toBeVisible();
  await page.goto('/party/#nowhere');
  await expect(page.locator('html')).toHaveAttribute('data-place', 'home');
  await expect(page.locator('#view-home')).toBeVisible();
});

test('"Skip to the games" goes to the Library and puts focus on its heading, from any place', async ({ page }) => {
  await open(page);
  const skip = page.locator('#skip');
  for (const from of ['home', 'library'] as const) {
    await place(page, from);
    await skip.focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('html')).toHaveAttribute('data-place', 'library');
    await expect(page.locator('#games-h')).toBeFocused();
  }
  await page.goBack();                                                    // it was a step, like the bar's
  await expect(page.locator('html')).toHaveAttribute('data-place', 'home');
});

test('the phone’s Back closes what is open over a place', async ({ page, context }) => {
  await context.addInitScript(() => { try { localStorage.setItem('wc-name', 'Robin'); } catch { /* none */ } });
  await open(page);
  await place(page, 'party');
  await place(page, 'system');
  await page.locator('#hud').click();
  await expect(page.locator('#social')).toBeVisible();
  await page.goBack();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'party');
  await expect(page.locator('#social')).toBeHidden();
});

test('the frame holds at 200% text on a small phone: nothing sideways, the bars stay, words stay whole', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 640 });
  await open(page);
  await page.evaluate(() => document.documentElement.style.setProperty('font-size', '200%'));
  for (const name of ['home', 'party', 'library', 'system'] as const) {
    await place(page, name);
    expect(await sideways(page), name).toBeLessThanOrEqual(0);
    const title = await page.locator('#top-title').evaluate((el) => {
      const range = document.createRange(); range.selectNodeContents(el);
      return { lines: new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size, words: (el.textContent || '').split(' ').length };
    });
    expect(title.lines, `${name}: the title breaks only between words`).toBeLessThanOrEqual(title.words);
    const bar = await page.locator('#nav').boundingBox();
    expect(bar!.y + bar!.height, name).toBeLessThanOrEqual(640);            // the bar is on screen
    expect(bar!.height / 640, name).toBeLessThan(0.3);                       // and leaves the page its room
  }
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
  await expect(page.locator('#home-games')).toBeHidden();                // nothing to browse while away
  await place(page, 'library');
  await expect(page.locator('#away')).toBeVisible();                     // said in every place, not only on Home
  await expect(page.locator('#games-section')).toBeHidden();
  await expect(page.locator('#away a')).toHaveCount(0);   // the retired LAN Games hub is not offered as a way out

  // Try again while still away: stays honest.
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.locator('#away')).toBeVisible();

  // Back on the Wi-Fi: the page recovers by itself (the 'online' event), no tap needed.
  await context.setOffline(false);
  await expect(page.locator('#away')).toBeHidden();
  await expect(page.locator('#status')).toContainText('Connected to the party');
  await expect(page.locator('#games [data-game="arcade-gauntlet2"]')).toBeVisible();
});

test('a refresh keeps keyboard focus on an unchanged card', async ({ page }) => {
  await h264(page, true);
  await open(page);
  await place(page, 'library');
  const refresh = async () => {
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));  // triggers a refresh
    await page.waitForTimeout(500);
  };
  const tile = page.locator('#games [data-game="arcade-gauntlet2"]');
  await tile.focus();
  await refresh();
  await expect(tile).toBeFocused();                                        // a cover on the shelf
  const play = (await openGame(page, 'arcade-gauntlet2')).getByRole('link', { name: 'Play' });
  await play.focus();
  await refresh();
  expect(await page.evaluate(() => document.activeElement?.textContent)).toBe('Play');
  await expect(play).toBeFocused();                                        // and the open game's own button
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
