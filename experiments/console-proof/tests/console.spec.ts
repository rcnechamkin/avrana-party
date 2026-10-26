// The proof's behaviour tests, run for each framework (vanilla, svelte) and each game-view
// strategy (M: console over the mounted game; R: leave the game, restore it from the server).
import WebSocket from 'ws';
import { GAME, admin, backToGame, consoleRoot, expect, layerFrame, openConsole, openGame, phone, probe, stats, test, waitReady } from './fixtures';

test.beforeEach(async ({ request }) => {
  await request.post('http://127.0.0.1:8370/test/reset', { headers: { 'x-cp-test': '1' } });
});

/** The hello frames a page sent: the tickets it used. */
const tickets = (sent: string[]) => sent.map((s) => JSON.parse(s)).filter((m) => m.type === 'hello').map((m) => m.ticket as string);

/** Present a ticket to the game server from outside any browser; resolves with its answer. */
function hello(game: string, ticket: string): Promise<{ type: string; reason?: string; role?: string }> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`ws://127.0.0.1:8371/ws/${game}`, { headers: { origin: GAME } });
    ws.on('open', () => ws.send(JSON.stringify({ type: 'hello', ticket })));
    ws.on('message', (raw) => { const m = JSON.parse(String(raw)); if (m.type === 'welcome' || m.type === 'reject') { ws.close(); resolve(m); } });
    ws.on('error', reject);
  });
}

test('ordinary browse and Back to Game: same participant and role, fresh ticket, old one refused, no Party version bump, no one else moved', async ({ browser, request, fw, strategy }) => {
  for (const game of ['rt', 'turn'] as const) {
    await request.post('http://127.0.0.1:8370/test/reset', { headers: { 'x-cp-test': '1' } });
    await request.post('http://127.0.0.1:8370/test/location', { headers: { 'x-cp-test': '1' }, data: { game } });
    const p1 = await phone(browser, 'P1', game), p2 = await phone(browser, 'P2', game);
    await openGame(p1, game, fw, strategy); await openGame(p2, game, fw, strategy);
    const before = await probe(p1.page);
    const s0 = await stats(p1.page);
    const p2url = p2.page.url();

    await openConsole(p1.page, strategy);
    const ui = consoleRoot(p1.page, strategy);
    await expect(ui.locator('#where')).toContainText(game === 'rt' ? 'playing Dot Rally' : 'playing Duel');
    await ui.locator('#tab-party').click();
    await expect(ui.locator('#people')).toContainText('P1 (you)');
    await expect(ui.locator('#people')).toContainText('Host');
    await ui.locator('#tab-library').click();
    await expect(ui.locator('#library li')).toHaveCount(8);
    await ui.locator('[data-key="suggest-coup"]').click();
    await expect(ui.locator('[data-key="suggest-coup"]')).toBeDisabled();
    await ui.locator('#tab-home').click();
    await expect(ui.locator('#fixture-note')).toHaveText('Preview: fixture data, not a voting backend.');
    await ui.locator('[data-key="approve-s2"]').click();                 // Best Guess: 1 -> 2 approvals, named
    await expect(ui.locator('[data-suggestion="s2"] [data-approvals]')).toHaveText('2 approvals: Ben and P1');
    await expect(ui.locator('#sugg > li').first()).toHaveAttribute('data-suggestion', 's1');   // ties keep the earlier one first
    await ui.locator('[data-key="approve-s3"]').click();
    await expect(ui.locator('#sugg > li').nth(1)).toHaveAttribute('data-suggestion', 's2');

    await backToGame(p1.page, strategy);
    const after = await probe(p1.page);
    expect(after.role).toBe(before.role);
    expect(after.role).toBe('player');
    expect(after.you).toBe(before.you);
    const s1 = await stats(p1.page);
    expect(s1.version, 'browsing never bumps the Party version').toBe(s0.version);
    expect(s1.location).toEqual(s0.location);
    expect(p2.page.url(), 'nobody else moved').toBe(p2url);
    expect(s1.game.cookieLeaks, 'the game origin never received the Party cookie').toBe(0);
    const used = tickets(p1.sent);
    if (strategy === 'R') {
      expect(used.length, 'R: Back to Game used a fresh ticket').toBeGreaterThanOrEqual(2);
      expect(used.at(-1)).not.toBe(used[0]);
    }
    expect((await hello(game, used[0])).reason, 'the first ticket cannot be replayed').toBe('replayed');
    const forged = used[0].replace(/^[^.]+/, Buffer.from(JSON.stringify({ pid: 'ben', name: 'Ben', game, role: 'player', exp: Date.now() + 60_000, n: 'x' })).toString('base64url'));
    expect((await hello(game, forged)).reason, 'never another player\'s seat').toBe('bad');
    await p1.ctx.close(); await p2.ctx.close();
  }
});

test('reload while the console is open keeps the seat', async ({ browser, request, fw, strategy }) => {
  const p1 = await phone(browser, 'P1', 'rt');
  await openGame(p1, 'rt', fw, strategy);
  const you = (await probe(p1.page)).you;
  await openConsole(p1.page, strategy);
  await p1.page.reload();
  if (strategy === 'M') { await waitReady(p1.page); await expect(p1.page.locator('iframe[title="Your Party"]')).toHaveAttribute('data-avrana-party-layer', 'button'); }
  else { await p1.page.locator('body[data-ready="1"]').waitFor(); await backToGame(p1.page, strategy); }
  const after = await probe(p1.page);
  expect(after.role).toBe('player'); expect(after.you).toBe(you);
});

test('a socket the server drops comes back by itself with the same seat', async ({ browser, request, fw, strategy }) => {
  const p1 = await phone(browser, 'P1', 'rt');
  await openGame(p1, 'rt', fw, strategy);
  if (strategy === 'M') await openConsole(p1.page, strategy);   // dropped while browsing (M keeps the socket while browsing)
  await admin(p1.page, '/test/drop');
  await expect.poll(async () => (await probe(p1.page)).reconnects).toBeGreaterThanOrEqual(1);
  if (strategy === 'M') await backToGame(p1.page, strategy);
  const after = await probe(p1.page);
  expect(after.role).toBe('player');
  expect(after.rejects).toEqual([]);     // a reconnect asks for a fresh ticket, never reuses one
});

test('stale session: an expired ticket is renewed through the Party and rejoins only its own seat', async ({ browser, request, fw, strategy }) => {
  const p1 = await phone(browser, 'P1', 'rt');
  await openGame(p1, 'rt', fw, strategy);
  const you = (await probe(p1.page)).you;
  await openConsole(p1.page, strategy);
  await admin(p1.page, '/test/expire-next', { name: 'P1' });
  if (strategy === 'M') { await admin(p1.page, '/test/drop'); await expect.poll(async () => (await probe(p1.page)).rejects).toContain('expired'); await backToGame(p1.page, strategy); }
  else { await backToGame(p1.page, strategy); await expect.poll(async () => (await probe(p1.page)).rejects).toContain('expired'); }
  await expect.poll(async () => (await probe(p1.page)).role).toBe('player');
  expect((await probe(p1.page)).you).toBe(you);
});

test('revoked while browsing: Back to Game shows a spectator and no private state', async ({ browser, request, fw, strategy }) => {
  await request.post('http://127.0.0.1:8370/test/location', { headers: { 'x-cp-test': '1' }, data: { game: 'turn' } });
  const p1 = await phone(browser, 'P1', 'turn'), p2 = await phone(browser, 'P2', 'turn');
  await openGame(p1, 'turn', fw, strategy); await openGame(p2, 'turn', fw, strategy);
  await expect(p1.page.locator('#hand button')).toHaveCount(3);
  await openConsole(p1.page, strategy);
  await admin(p1.page, '/test/seat-remove', { name: 'P1', game: 'turn' });
  const mark = p1.frames.length;
  await backToGame(p1.page, strategy);
  await expect.poll(async () => (await probe(p1.page)).role).toBe('spectator');
  await expect(p1.page.locator('#hand button')).toHaveCount(0);
  await expect(p1.page.locator('#status')).toHaveText('You are watching.');
  await p1.page.waitForTimeout(500);
  const later = p1.frames.slice(mark).filter((f) => !f.includes('"type":"role"'));
  expect(later.filter((f) => f.includes('PRIVATE-')), 'no hand after the seat was taken').toEqual([]);
});

test('private-state boundary: a spectator never receives a player\'s hand, before or after browsing', async ({ browser, request, fw, strategy }) => {
  await request.post('http://127.0.0.1:8370/test/location', { headers: { 'x-cp-test': '1' }, data: { game: 'turn' } });
  const p1 = await phone(browser, 'P1', 'turn'), p2 = await phone(browser, 'P2', 'turn'), watcher = await phone(browser, 'W', 'none');
  await openGame(p1, 'turn', fw, strategy); await openGame(p2, 'turn', fw, strategy); await openGame(watcher, 'turn', fw, strategy);
  expect((await probe(watcher.page)).role).toBe('spectator');
  await openConsole(watcher.page, strategy);
  await backToGame(watcher.page, strategy);
  await p1.page.locator('#hand button').first().click().catch(() => {});     // whoever's turn it is plays; hands are re-dealt
  await p2.page.locator('#hand button').first().click().catch(() => {});
  await watcher.page.waitForTimeout(600);
  expect(p1.frames.some((f) => f.includes('PRIVATE-')), 'positive control: a player gets their own hand').toBe(true);
  expect(watcher.frames.filter((f) => f.includes('PRIVATE-'))).toEqual([]);
  expect(await watcher.page.locator('#hand li').count()).toBe(0);
});

test('turn timer while browsing: the server times the turn out exactly as for a locked phone', async ({ browser, request, fw, strategy }) => {
  await request.post('http://127.0.0.1:8370/test/location', { headers: { 'x-cp-test': '1' }, data: { game: 'turn' } });
  const p1 = await phone(browser, 'P1', 'turn'), p2 = await phone(browser, 'P2', 'turn');
  await openGame(p1, 'turn', fw, strategy); await openGame(p2, 'turn', fw, strategy);
  const start = (await stats(p1.page)).state.turn;
  await openConsole(p1.page, strategy);
  await p1.page.waitForTimeout(5600);                     // CP_TURN_MS=5000: one turn times out while P1 browses
  const mid = (await stats(p1.page)).state.turn;
  expect(mid.turnNo).toBeGreaterThan(start.turnNo);
  expect(mid.log.join(' ')).toContain('timed out');
  await backToGame(p1.page, strategy);
  await expect.poll(async () => (await probe(p1.page)).turnNo).toBe((await stats(p1.page)).state.turn.turnNo);
  // The client shows the server's deadline (not a timer of its own), on the server's clock.
  await expect.poll(async () => (await probe(p1.page)).deadline, { message: 'the client holds the server deadline' }).toBe((await stats(p1.page)).state.turn.deadline);
  const drift = await p1.page.evaluate(() => { const p = (window as any).__probe; return Math.abs(p.shownLeft - Math.round((p.deadline - (Date.now() + p.serverOffset)) / 1000)); });
  expect(drift, 'the countdown follows the server deadline').toBeLessThanOrEqual(1);
  // The locked-phone control: P2's page closed outright; its turn times out all the same.
  await p2.page.close();
  const t0 = (await stats(p1.page)).state.turn.turnNo;
  await expect.poll(async () => (await stats(p1.page)).state.turn.turnNo, { timeout: 12_000 }).toBeGreaterThan(t0);
});

test('keyboard: tab order, Escape closes, focus returns', async ({ browser, request, fw, strategy }) => {
  const p1 = await phone(browser, 'P1', 'rt');
  await openGame(p1, 'rt', fw, strategy);
  const btn = layerFrame(p1.page).locator('#layer-button');
  await btn.focus();
  await p1.page.keyboard.press('Enter');
  if (strategy === 'M') {
    const ui = layerFrame(p1.page);
    await expect(ui.locator('#close')).toBeFocused();
    await p1.page.keyboard.press('Tab');
    await expect(ui.locator('#back-to-game')).toBeFocused();
    await p1.page.keyboard.press('Tab');
    await expect(ui.locator('#tab-home')).toBeFocused();
    for (let i = 0; i < 12; i++) await p1.page.keyboard.press('Tab');            // the drawer traps Tab
    expect(await ui.locator('#sheet').evaluate((s) => s.contains(document.activeElement))).toBe(true);
    await p1.page.keyboard.press('Escape');
    await expect(p1.page.locator('iframe[title="Your Party"]')).toHaveAttribute('data-avrana-party-layer', 'button');
    await expect(ui.locator('#layer-button')).toBeFocused();
  } else {
    await p1.page.waitForURL(/party\.cp\.test/);
    await expect(p1.page.locator('#back-to-game')).toBeFocused();
    await p1.page.keyboard.press('Tab');
    await expect(p1.page.locator('#tab-home')).toBeFocused();
    await p1.page.keyboard.press('Shift+Tab');
    await p1.page.keyboard.press('Enter');
    await p1.page.waitForURL(/games\.cp\.test/); await waitReady(p1.page);
    await expect(p1.page.locator('#stage')).toBeFocused();
  }
});

test('reduced motion turns the entrance off; 200% text keeps the game indicator and no sideways scroll', async ({ browser, request, fw, strategy }) => {
  for (const reducedMotion of ['reduce', 'no-preference'] as const) {
    const p1 = await phone(browser, 'P1', 'rt', { reducedMotion });
    await openGame(p1, 'rt', fw, strategy);
    await openConsole(p1.page, strategy);
    const ui = consoleRoot(p1.page, strategy);
    const dur = await ui.locator('#sheet').evaluate((s) => getComputedStyle(s).transitionDuration);
    expect(dur.split(',')[0].trim()).toBe(reducedMotion === 'reduce' ? '0s' : '0.22s');
    await ui.locator('#sheet').evaluate(() => { document.documentElement.style.fontSize = '200%'; });
    await expect(ui.locator('#where')).toBeVisible();
    await expect(ui.locator('#where')).toHaveAttribute('aria-live', 'polite');
    const over = await ui.locator('#sheet').evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over).toBeLessThanOrEqual(1);
    await p1.ctx.close();
  }
});

test('click interception: can game-page content cover the trusted Back to Game control?', async ({ browser, request, fw, strategy }) => {
  const p1 = await phone(browser, 'P1', 'rt');
  await openGame(p1, 'rt', fw, strategy);
  await openConsole(p1.page, strategy);
  if (strategy === 'M') {
    // The game page owns the frame element: a hostile or buggy game can lay content over the drawer.
    await p1.page.evaluate(() => {
      const lure = document.createElement('div');
      lure.id = 'lure';
      Object.assign(lure.style, { position: 'fixed', inset: '0', zIndex: '2147483647', background: 'transparent' });
      lure.addEventListener('click', () => { (window as any).__lured = true; });
      document.body.append(lure);
    });
    const box = await p1.page.locator('iframe[title="Your Party"]').boundingBox();
    const back = await layerFrame(p1.page).locator('#back-to-game').boundingBox();
    await p1.page.mouse.click(back!.x + back!.width / 2, back!.y + back!.height / 2);
    expect(box).not.toBeNull();
    expect(await p1.page.evaluate(() => (window as any).__lured), 'M is coverable: the game, not the Party, got the tap').toBe(true);
  } else {
    // R: the console is a top-level Party page; no game document exists to draw over it.
    expect(new URL(p1.page.url()).host).toBe('party.cp.test:8370');
    expect(await p1.page.locator('iframe').count()).toBe(0);
    await p1.page.locator('#back-to-game').click();
    await p1.page.waitForURL(/games\.cp\.test/);
  }
});

test('Limited Mode stand-in (game same-origin under /g/): browse and Back to Game keep the seat', async ({ browser, request, fw, strategy }) => {
  const p1 = await phone(browser, 'P1', 'rt');
  await p1.page.goto(`http://party.cp.test:8370/g/rt.html?fw=${fw}&s=${strategy}`);
  await waitReady(p1.page);
  const you = (await probe(p1.page)).you;
  await openConsole(p1.page, strategy);
  await backToGame(p1.page, strategy);
  expect(new URL(p1.page.url()).host, 'stays on the one origin').toBe('party.cp.test:8370');
  const after = await probe(p1.page);
  expect(after.role).toBe('player'); expect(after.you).toBe(you);
  expect((await stats(p1.page)).game.cookieLeaks, 'the socket proxy strips the cookie, as nginx does').toBe(0);
});
