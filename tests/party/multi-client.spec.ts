import { test, expect, type Browser, type BrowserContext, type Page } from '@playwright/test';

/**
 * Several phones at one party (ADR 0011 console model) against a real Party Core behind the dev
 * server. Each phone is its own browser context: its own cookie jar (device identity) and its own
 * localStorage (profile). Covers: host and followers, one place for everyone, game switching,
 * reconnect without losing the seat, stale/unauthorized actions, host departure and succession.
 * Tier 2: real Chromium, simulated appliance, stub game pages. Not a phone.
 */

type Phone = { name: string; context: BrowserContext; page: Page };

async function phone(browser: Browser, name: string): Promise<Phone> {
  const context = await browser.newContext();
  await context.addInitScript((who) => {
    // A saved profile is who this phone is at the party; presence then is automatic.
    window.localStorage.setItem('wc-name', who);
  }, name);
  const page = await context.newPage();
  page.on('pageerror', (e) => console.log(`[${name}] pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') console.log(`[${name}] console: ${m.text()}`); });
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('#party')).toBeVisible();
  await expect(page.locator('#party-members')).toContainText(`${name} (you)`);
  return { name, context, page };
}

async function view(p: Phone) {
  const res = await p.page.request.get('/party/api/state');
  expect(res.ok()).toBeTruthy();
  return res.json();
}

async function post(p: Phone, path: string, body: Record<string, unknown>) {
  // What the page's own fetch sends: JSON plus the page's Origin (Party Core's CSRF guard).
  const origin = new URL(p.page.url()).origin;
  return p.page.request.post(`/party/api/${path}`, { data: body, headers: { 'Content-Type': 'application/json', Origin: origin } });
}

async function version(p: Phone) {
  return (await view(p)).version as number;
}

async function endForEveryone(host: Phone) {
  const end = await post(host, 'session/end', { if_version: await version(host) });
  expect(end.status()).toBe(200);
}

test.beforeEach(async ({ request }) => {
  const res = await request.post('/__test__/party/reset');
  expect(res.status()).toBe(204);
});

test.describe('three phones at one party', () => {
  let host: Phone, bob: Phone, cleo: Phone;

  test.beforeEach(async ({ browser }) => {
    host = await phone(browser, 'Ada');
    bob = await phone(browser, 'Bob');
    cleo = await phone(browser, 'Cleo');
  });

  test.afterEach(async () => {
    for (const p of [host, bob, cleo]) await p.context.close();
  });

  test('the first phone hosts; followers see the host and cannot start a game', async () => {
    await expect(host.page.locator('#party-count')).toHaveText('3 people');
    await expect(host.page.locator('#party-host')).toContainText('You’re the host');
    await expect(bob.page.locator('#party-host')).toContainText('Ada is the host');
    await expect(cleo.page.locator('#party-members li')).toHaveCount(3);
    const tile = (p: Phone) => p.page.locator('[data-id="expo"]');
    await expect(tile(host).getByRole('button', { name: 'Start for everyone' })).toBeEnabled();
    await expect(tile(bob).getByRole('button', { name: 'The host starts it' })).toBeDisabled();
    // The API refuses a follower who tries anyway, and a stale host tab too.
    const refused = await post(bob, 'session/launch', { game: 'expo', if_version: await version(bob) });
    expect(refused.status()).toBe(403);
    expect((await refused.json()).error).toBe('not_host');
    const stale = await post(host, 'session/launch', { game: 'expo', if_version: 0 });
    expect(stale.status()).toBe(409);
    expect((await stale.json()).error).toBe('stale');
    const stranger = await host.page.request.post('/party/api/session/launch', {
      data: { game: 'expo' }, headers: { 'Content-Type': 'application/json', Origin: 'https://evil.example' } });
    expect(stranger.status()).toBe(403);                      // a page from elsewhere cannot act
  });

  test('the host starts a game and everyone goes there; ending it brings everyone home', async () => {
    await host.page.locator('[data-id="expo"]').getByRole('button', { name: 'Start for everyone' }).click();
    for (const p of [host, bob, cleo]) {
      await expect(p.page).toHaveURL(/\/games\/expo\/\?avrana=1/);
      await expect(p.page.locator('h1[data-game="expo"]')).toBeVisible();
    }
    // Two seats: the third phone watches, but is at the same place as everyone else.
    const s = (await view(cleo)).session;
    expect(s.game).toBe('expo');
    expect(s.my_role).toBe('spectator');
    expect((await view(bob)).session.my_role).toBe('player');
    // Only the host gets the fallback "end" control on a page that draws none of its own.
    await expect(host.page.locator('#avrana-party-end')).toBeVisible();
    await expect(bob.page.locator('#avrana-party-end')).toHaveCount(0);
    await host.page.locator('#avrana-party-end').click();
    await expect(host.page.locator('#avrana-party-end')).toHaveText('Tap again to end it');
    await host.page.locator('#avrana-party-end').click();
    for (const p of [host, bob, cleo]) {
      await expect(p.page).toHaveURL(/\/party\/$/);
      await expect(p.page.locator('html'), p.name).toHaveAttribute('data-ready', 'true');
      await expect(p.page.locator('#party-count'), p.name).toHaveText('3 people');
    }
  });

  test('switching games: the next start moves the whole party, and the old page follows', async () => {
    await host.page.locator('[data-id="expo"]').getByRole('button', { name: 'Start for everyone' }).click();
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    // The host switches from inside the game (the party API, as a game's shell would call it).
    const sw = await post(host, 'session/switch', { game: 'arcade-gauntlet2', if_version: await version(host) });
    expect(sw.status()).toBe(200);
    for (const p of [host, bob, cleo]) await expect(p.page).toHaveURL(/\/arcade\//);
    expect((await view(host)).session.game).toBe('arcade-gauntlet2');
    await endForEveryone(host);
    for (const p of [host, bob, cleo]) await expect(p.page).toHaveURL(/\/party\/$/);
  });

  test('a phone that reloads mid-game keeps its identity and its seat', async () => {
    await host.page.locator('[data-id="expo"]').getByRole('button', { name: 'Start for everyone' }).click();
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    const before = await view(bob);
    await bob.page.reload();
    await expect(bob.page.locator('h1[data-game="expo"]')).toBeVisible();
    const after = await view(bob);
    expect(after.me.id).toBe(before.me.id);
    expect(after.session.id).toBe(before.session.id);
    expect(after.session.my_role).toBe('player');
    expect(after.members).toHaveLength(3);                 // no duplicate member from the reload
    // A phone that wanders back to Party Home during the round is sent to the game again.
    await bob.page.goto('/party/');
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    await endForEveryone(host);
  });

  test('a ticket for a session that ended is refused, and the next round is a new session', async () => {
    await host.page.locator('[data-id="expo"]').getByRole('button', { name: 'Start for everyone' }).click();
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    const first = (await view(bob)).session.id;
    await endForEveryone(host);
    await expect(bob.page).toHaveURL(/\/party\/$/);
    const stale = await post(bob, 'session/ticket', { game: 'expo' });
    expect([404, 409]).toContain(stale.status());
    await host.page.locator('[data-id="expo"]').getByRole('button', { name: 'Start for everyone' }).click();
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    expect((await view(bob)).session.id).not.toBe(first);
    await endForEveryone(host);
  });

  test('the ready-or-watch setup: everyone chooses, only the host starts', async () => {
    await host.page.locator('[data-id="bluff"]').getByRole('button', { name: 'Start for everyone' }).click();
    for (const p of [host, bob, cleo]) await expect(p.page.locator('#scene')).toBeVisible();
    await expect(bob.page.locator('#scene-start')).toBeHidden();
    await expect(host.page.locator('#scene-start')).toBeVisible();
    await expect(host.page.locator('#scene-start')).toBeDisabled();       // nobody chose yet
    for (const p of [host, bob]) {
      await p.page.locator('#choose-play').click();
      const ok = p.page.locator('#rules-ok');
      if (await ok.isVisible().catch(() => false)) await ok.click();      // first-play briefing
      await expect(p.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'true');
    }
    await cleo.page.locator('#choose-watch').click();
    await expect(cleo.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    await expect(host.page.locator('#scene-start')).toBeEnabled();
    const refused = await post(cleo, 'session/start', { if_version: await version(cleo) });
    expect(refused.status()).toBe(403);
    await host.page.locator('#scene-start').click();
    for (const p of [host, bob, cleo]) await expect(p.page).toHaveURL(/\/games\/bluff\//);
    expect((await view(cleo)).session.my_role).toBe('spectator');
    await endForEveryone(host);
  });

  test('when the host leaves, the next phone hosts at once and the party goes on', async () => {
    const leave = await post(host, 'leave', {});
    expect(leave.status()).toBe(200);
    await expect(bob.page.locator('#party-host')).toContainText('You’re the host');
    await expect(cleo.page.locator('#party-host')).toContainText('Bob is the host');
    await expect(bob.page.locator('[data-id="expo"]').getByRole('button', { name: 'Start for everyone' })).toBeEnabled();
    await bob.page.locator('[data-id="expo"]').getByRole('button', { name: 'Start for everyone' }).click();
    await expect(cleo.page).toHaveURL(/\/games\/expo\//);
    await endForEveryone(bob);
  });
});

test('the status endpoint names the running build for people and agents', async ({ request }) => {
  const res = await request.get('/party/api/status');
  expect(res.ok()).toBeTruthy();
  const doc = await res.json();
  expect(doc.schema).toBe('avrana.status/v0');
  expect(doc.contract.party_games).toBe('avrana.party-games/v0');
  expect(doc.party.checkout_sha).toMatch(/^[0-9a-f]{40}$/);
  expect(['ok', 'unknown']).toContain(doc.summary.state);
  expect(JSON.stringify(doc)).not.toMatch(/token|privkey|cookie/i);
});
