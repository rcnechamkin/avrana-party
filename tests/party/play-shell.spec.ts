import { test, expect } from '@playwright/test';
import { phone, post, version } from '../lib/phones';

/**
 * PROPOSAL play_shell (AVR-766; draft ADR 0018 revision 3), Tier 2. A real Party Core behind the dev
 * server with every game registered to http://games.avrana.test:<port> (--game-origin) and the
 * proposal switched on (AVRANA_DEV_PROPOSALS=play_shell); Chromium resolves the test host names to
 * the dev server (playwright.party.config.ts, project play-shell-chromium).
 *
 * The top-level page never leaves /party/ during a round: the game is framed on its own origin and
 * the Party layer floats beside it, out of the game's reach.
 *
 * Not shown here: a top-level game page re-entering the shell (the stub game here runs no bridge;
 * tests/offline/party-bridge.test.mjs covers the bridge's side). And the reason AVR-766 exists: an installed app on a real iPhone (the browser bar),
 * Safari's frame rate, two-thumb touch, audio and wake lock, safe areas, the keyboard, Back. Tier 3.
 */
const PORT = Number(process.env.AVRANA_PARTY_SHELL_DEV_PORT || Number(process.env.AVRANA_PARTY_DEV_PORT || 8184) + 2);
const PARTY = `http://127.0.0.1:${PORT}`;
const GAMES = `http://games.avrana.test:${PORT}`;
const PLAY = `${PARTY}/party/play.html`;

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

test('a round runs inside /party/play.html: the game framed on its origin, the Party layer beside it, and back to Party Home at the end', async ({ browser }) => {
  const ana = await phone(browser, 'Ana'), ben = await phone(browser, 'Ben');
  const topLevel: string[] = [];
  for (const p of [ana, ben]) p.page.on('framenavigated', (f) => { if (f === p.page.mainFrame()) topLevel.push(f.url()); });

  expect((await post(ana, 'session/launch', { game: 'expo', if_version: await version(ana) })).status()).toBe(200);
  for (const p of [ana, ben]) {
    await expect(p.page).toHaveURL(PLAY);
    const game = p.page.locator('#game');
    await expect(game).toHaveAttribute('src', new RegExp(`^${GAMES}/games/expo/`));
    await expect(p.page.frameLocator('#game').locator('h1[data-game="expo"]')).toBeVisible();
    // the sandbox: its own origin and scripts, never the Party's navigation or a new window
    const sandbox = (await game.getAttribute('sandbox'))!.split(' ');
    expect(sandbox).toEqual(expect.arrayContaining(['allow-scripts', 'allow-same-origin']));
    expect(sandbox.some((w) => w.startsWith('allow-top-navigation') || w === 'allow-popups')).toBe(false);
    // the Party layer is the shell's own frame, a sibling of the game's, at its button size
    const layer = p.page.locator('iframe[data-avrana-party-layer]');
    await expect(layer).toHaveAttribute('src', `${PARTY}/party/layer.html?game=expo`);
    await expect(layer).toHaveAttribute('data-avrana-party-layer', 'button');
    const box = (await layer.boundingBox())!;
    expect(box.width).toBe(48);
    expect(box.height).toBe(48);
    // S23: the game cannot take the top-level page anywhere, whatever it tries
    await p.page.frame({ url: new RegExp(`^${GAMES}/games/expo/`) })!.evaluate(() => {
      try { window.top!.location.href = 'https://example.invalid/'; } catch { /* refused outright */ }
    });
    await p.page.waitForTimeout(300);
    await expect(p.page).toHaveURL(PLAY);
  }
  expect(topLevel.filter((u) => !u.startsWith(`${PARTY}/party/`)), 'the top-level page never left /party/').toEqual([]);

  // The Host ends the round: both phones are back on Party Home, still inside /party/.
  expect((await post(ana, 'session/end', { if_version: await version(ana) })).status()).toBe(200);
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(new RegExp(`^${PARTY}/party/(#.*)?$`));
  expect(topLevel.filter((u) => !u.startsWith(`${PARTY}/party/`))).toEqual([]);
  await ana.context.close(); await ben.context.close();
});

test('the shell may frame only the game origin and the Party, and nothing may frame it', async ({ request }) => {
  const csp = (await request.get('/party/play.html')).headers()['content-security-policy'];
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toContain(`frame-src 'self' ${GAMES}`);
  const bridge = (await request.get('/party/bridge.html')).headers()['content-security-policy'];
  expect(bridge).toContain(`frame-ancestors 'self' ${GAMES}`);
});

test('opened with no round on, the shell goes to Party Home', async ({ browser }) => {
  const ana = await phone(browser, 'Ana');
  await ana.page.goto('/party/play.html');
  await expect(ana.page).toHaveURL(new RegExp(`^${PARTY}/party/(#.*)?$`));
  await ana.context.close();
});

test('PROPOSAL fab_panel: the Party menu is a bounded sheet over the game, and ending the round is held to confirm', async ({ browser }) => {
  const ana = await phone(browser, 'Ana'), ben = await phone(browser, 'Ben');
  await ana.page.setViewportSize({ width: 390, height: 844 });
  expect((await post(ana, 'session/launch', { game: 'expo', if_version: await version(ana) })).status()).toBe(200);
  await expect(ana.page).toHaveURL(PLAY);
  const layer = ana.page.frameLocator('iframe[data-avrana-party-layer]');
  await layer.locator('#layer-button').click();
  await expect(ana.page.locator('iframe[data-avrana-party-layer]')).toHaveAttribute('data-avrana-party-layer', 'open');
  const sheet = layer.locator('#layer-sheet');
  await expect(sheet).toHaveAttribute('data-side', 'bottom');
  const box = (await sheet.boundingBox())!;
  expect(box.y + box.height).toBeCloseTo(844, 0);                        // along the bottom
  expect(box.height).toBeLessThanOrEqual(844 * 0.7 + 1);                // never the whole screen: the game is in sight
  // Escape closes it and the game has the focus again
  await ana.page.keyboard.press('Escape');
  await expect(ana.page.locator('iframe[data-avrana-party-layer]')).toHaveAttribute('data-avrana-party-layer', 'button');
  await expect.poll(() => ana.page.evaluate(() => document.activeElement && document.activeElement.id)).toBe('game');

  // End: a tap is not enough, a hold is
  await layer.locator('#layer-button').click();
  await layer.getByRole('button', { name: 'End the round for everyone' }).click();
  const yes = layer.locator('#layer-yes');
  await expect(layer.locator('#layer-hold-note')).toBeVisible();
  await yes.click();
  await expect(layer.locator('#layer-confirm-error')).toHaveText('Keep holding to confirm.');
  await expect(ana.page).toHaveURL(PLAY);
  const yb = (await yes.boundingBox())!;
  await ana.page.mouse.move(yb.x + yb.width / 2, yb.y + yb.height / 2);
  await ana.page.mouse.down();
  await ana.page.waitForTimeout(1000);
  await ana.page.mouse.up();
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(new RegExp(`^${PARTY}/party/(#.*)?$`));
  await ana.context.close(); await ben.context.close();
});

test('PROPOSAL fab_panel: in landscape the sheet runs along the button\'s side', async ({ browser }) => {
  const ana = await phone(browser, 'Ana');
  await ana.page.setViewportSize({ width: 844, height: 390 });
  expect((await post(ana, 'session/launch', { game: 'expo', if_version: await version(ana) })).status()).toBe(200);
  await expect(ana.page).toHaveURL(PLAY);
  const layer = ana.page.frameLocator('iframe[data-avrana-party-layer]');
  await layer.locator('#layer-button').click();
  const sheet = layer.locator('#layer-sheet');
  await expect(sheet).toHaveAttribute('data-side', 'right');            // the button starts on the right
  const box = (await sheet.boundingBox())!;
  expect(box.x + box.width).toBeCloseTo(844, 0);
  expect(box.width).toBeLessThanOrEqual(844 * 0.55 + 1);
  await ana.context.close();
});
