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
  // every phone says so for a moment, then Party Home
  await expect(ben.page.locator('#play-banner')).toHaveText('The Host ended the game.');
  await expect(ana.page.locator('#play-banner')).toHaveText('You ended the game.');
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
  // Move menu: two steps clockwise from the first place (top right, then bottom right... bottom left)
  await layer.getByRole('button', { name: 'Move menu to the next corner' }).click();
  await layer.getByRole('button', { name: 'Move menu to the next corner' }).click();
  await layer.getByRole('button', { name: 'Move menu to the next corner' }).click();
  await expect(sheet).toHaveAttribute('data-side', 'left');
  await ana.context.close();
});

test('PROPOSAL fab_panel: on a small phone at 200% text the panel stays bounded and End is still reachable', async ({ browser }) => {
  const ana = await phone(browser, 'Ana');
  await ana.page.setViewportSize({ width: 320, height: 568 });
  expect((await post(ana, 'session/launch', { game: 'expo', if_version: await version(ana) })).status()).toBe(200);
  await expect(ana.page).toHaveURL(PLAY);
  const layer = ana.page.frameLocator('iframe[data-avrana-party-layer]');
  await layer.locator('#layer-button').click();
  await layer.locator('html').evaluate((el) => { (el as HTMLElement).style.fontSize = '200%'; });
  const sheet = layer.locator('#layer-sheet');
  const box = (await sheet.boundingBox())!;
  expect(box.height).toBeLessThanOrEqual(568 * 0.7 + 1);
  expect(box.y + box.height).toBeCloseTo(568, 0);
  const end = layer.getByRole('button', { name: 'End the round for everyone' });
  await end.scrollIntoViewIfNeeded();
  await end.click();
  const yes = layer.locator('#layer-yes');
  await yes.scrollIntoViewIfNeeded();
  const yb = (await yes.boundingBox())!;
  expect(yb.y).toBeGreaterThanOrEqual(box.y - 1);                       // inside the sheet, on screen
  expect(yb.y + yb.height).toBeLessThanOrEqual(568 + 2);
  await ana.context.close();
});

// ---- negative and boundary checks (ADR 0018 rev 3 S10, S23; AVR-767/769) -------------------------------

test('S23: in the shell the game cannot open a window, and cannot draw over the Party button however high it stacks', async ({ browser }) => {
  const ana = await phone(browser, 'Ana');
  expect((await post(ana, 'session/launch', { game: 'expo', if_version: await version(ana) })).status()).toBe(200);
  await expect(ana.page).toHaveURL(PLAY);
  await expect(ana.page.frameLocator('#game').locator('h1[data-game="expo"]')).toBeVisible();
  const game = ana.page.frame({ url: new RegExp(`^${GAMES}/games/expo/`) })!;
  await expect(ana.page.frameLocator('iframe[data-avrana-party-layer]').locator('#layer-button')).toBeVisible();
  // no popups: the sandbox has no allow-popups
  expect(await game.evaluate(() => window.open('https://example.invalid/', '_blank') === null)).toBe(true);
  expect(ana.page.context().pages()).toHaveLength(1);
  // a full-screen element at the top of the game's own stack stays inside the game's frame
  await game.evaluate(() => {
    const cover = document.createElement('div');
    Object.assign(cover.style, { position: 'fixed', inset: '0', zIndex: '2147483647', background: 'rgba(255,0,0,0.5)' });
    cover.id = 'lure';
    document.body.append(cover);
  });
  const box = (await ana.page.locator('iframe[data-avrana-party-layer]').boundingBox())!;
  const top = await ana.page.evaluate(([x, y]) => { const el = document.elementFromPoint(x, y) as HTMLElement; return el.dataset.avranaPartyLayer || `${el.tagName}#${el.id}`; }, [box.x + box.width / 2, box.y + box.height / 2]);
  expect(top).toBe('button');
  await ana.page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(ana.page.locator('iframe[data-avrana-party-layer]')).toHaveAttribute('data-avrana-party-layer', 'open');
  await ana.context.close();
});

test('fab_panel: while the menu is open the game frame is inert, and it is not once it closes', async ({ browser }) => {
  const ana = await phone(browser, 'Ana');
  expect((await post(ana, 'session/launch', { game: 'expo', if_version: await version(ana) })).status()).toBe(200);
  await expect(ana.page).toHaveURL(PLAY);
  const layer = ana.page.frameLocator('iframe[data-avrana-party-layer]');
  await layer.locator('#layer-button').click();
  await expect.poll(() => ana.page.evaluate(() => (document.getElementById('game') as HTMLIFrameElement).inert)).toBe(true);
  await layer.locator('#layer-close').click();
  await expect.poll(() => ana.page.evaluate(() => (document.getElementById('game') as HTMLIFrameElement).inert)).toBe(false);
  await ana.context.close();
});

test('S10 in fallback: over a top-level game page of another origin, a tap under a lure cannot end the round; only a hold can', async ({ browser }) => {
  // the Party on a name of the same site as the game origin, so its cookie reaches the layer frame
  // (as party.avrana.net and games.avrana.net do); 127.0.0.1 would be a third party there
  const SITE_PARTY = `http://party.avrana.test:${PORT}`;
  const ana = await phone(browser, 'Ana', { baseURL: SITE_PARTY });
  // launched from the page's own fetch: Node cannot resolve the test host names, Chromium maps them
  const launched = await ana.page.evaluate(async () => {
    const v = await (await fetch('/party/api/state', { cache: 'no-store' })).json();
    const res = await fetch('/party/api/session/launch', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ game: 'expo', if_version: v.version }) });
    return res.status;
  });
  expect(launched).toBe(200);
  await expect(ana.page).toHaveURL(`${SITE_PARTY}/party/play.html`);
  // the fallback: the game page itself, top level, mounting the vendored layer (no shell)
  await ana.page.goto(`${GAMES}/__test__/layer-game.html?party=${encodeURIComponent(SITE_PARTY)}&game=expo`);
  const layer = ana.page.frameLocator('iframe[data-avrana-party-layer]');
  await layer.locator('#layer-button').click();
  await expect(layer.locator('#layer-sheet')).toHaveAttribute('data-side', '');      // the bounded panel is the shell's only
  await layer.getByRole('button', { name: 'End the round for everyone' }).click();
  await expect(layer.locator('#layer-hold-note')).toBeVisible();
  const yes = layer.locator('#layer-yes');
  const yb = (await yes.boundingBox())!;
  // #258: the game lays a see-through lure over the frame; a tap still lands on the frame's button
  await ana.page.evaluate(() => {
    const lure = document.createElement('div');
    lure.textContent = 'Tap to collect your prize';
    Object.assign(lure.style, { position: 'fixed', inset: '0', zIndex: '2147483647', pointerEvents: 'none', opacity: '0.9', background: '#fff' });
    document.body.append(lure);
  });
  await ana.page.mouse.click(yb.x + yb.width / 2, yb.y + yb.height / 2);
  await expect(layer.locator('#layer-confirm-error')).toHaveText('Keep holding to confirm.');
  // asked from the layer frame, on the Party's origin with its cookie (Node cannot resolve the test host names)
  const ended = async () => ana.page.frame({ url: /\/party\/layer\.html/ })!.evaluate(
    () => fetch('/party/api/state', { cache: 'no-store' }).then((r) => r.json()).then((v) => v.state));
  expect(await ended()).not.toBe('lobby');               // the round is still on
  await ana.page.mouse.move(yb.x + yb.width / 2, yb.y + yb.height / 2);
  await ana.page.mouse.down();
  await ana.page.waitForTimeout(1000);
  await ana.page.mouse.up();
  await expect.poll(ended, { timeout: 10_000 }).toBe('lobby');   // ended: everyone at Party Home
  await ana.context.close();
});
