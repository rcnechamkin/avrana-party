import { test, expect, type BrowserContext, type Page } from '@playwright/test';

/**
 * ADR 0013 / AVR-226 (Tier 2): a game page on ANOTHER origin of the same site reaches the Party
 * only through the bridge frame. Real Chromium, the real Party Core behind the dev server, two
 * host names that resolve to it (party.avrana.test, games.avrana.test: the same registrable
 * domain, so "same site" exactly as party.avrana.net and games.avrana.net are).
 *
 * What this cannot show: Safari on a real iPhone, HTTPS, the `__Host-` cookie (plain HTTP keeps
 * the old cookie name) and nginx's own headers. Those are Tier 3 and the owner's.
 */
const PORT = Number(process.env.AVRANA_DEV_PORT || 8181) + 1;      // the dev server with a real Party Core
const PARTY = `http://party.avrana.test:${PORT}`;
const GAMES = `http://games.avrana.test:${PORT}`;
const GAME = 'arcade-gauntlet2';                       // starts at once (no setup scene)
const gameUrl = (origin = GAMES, party = PARTY) =>
  `${origin}/__test__/bridge-game.html?party=${encodeURIComponent(party)}&game=${GAME}`;

async function api(page: Page, path: string, body?: unknown) {
  return page.evaluate(async ([p, b]) => {
    const res = await fetch('/party/api/' + p, b === undefined ? { cache: 'no-store' } : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
    return { status: res.status, body: await res.json().catch(() => null) };
  }, [path, body] as const);
}

/** Ana joins on the Party origin and, as host, starts the game for everyone. */
async function hostWithGameOn(page: Page) {
  // Playwright's own client does not use the browser's resolver, so it talks to 127.0.0.1.
  await page.request.post(`http://127.0.0.1:${PORT}/__test__/party/reset`);
  await page.goto(`${PARTY}/party/`);
  const joined = await api(page, 'join', { name: 'Ana' });
  expect(joined.status).toBe(200);
  const launched = await api(page, 'session/launch', { game: GAME, if_version: joined.body.version });
  expect(launched.status).toBe(200);
  expect(launched.body.state).toBe('active');
}

/** The game page in its own tab. The host's Party Home tab is left alone: it follows the party
 * to the game by itself, and a second navigation of that tab would race with it. */
async function openGame(context: BrowserContext, url = gameUrl()) {
  const game = await context.newPage();
  await game.goto(url);
  return game;
}

const lastView = (page: Page) => page.evaluate(() => (window as any).partyViews.at(-1) ?? null);

test('a game page on the game origin follows the party through the bridge and holds no identity', async ({ page: host, context }) => {
  await hostWithGameOn(host);
  const page = await openGame(context);
  await expect.poll(() => lastView(page)).toMatchObject({
    party: true, member: true, host: true, hostName: 'Ana', location: { at: 'game', game: GAME } });
  // The frame is the Party's page on the Party's origin, invisible and sandboxed.
  const frame = page.locator('iframe');
  await expect(frame).toHaveAttribute('src', `${PARTY}/party/bridge.html`);
  await expect(frame).toHaveAttribute('sandbox', 'allow-scripts allow-same-origin');
  await expect(frame).toBeHidden();
  // Nothing of the Party's identity is on the game origin.
  expect(await page.evaluate(() => document.cookie)).toBe('');
  expect(await page.evaluate(() => Object.keys(localStorage).length)).toBe(0);
  const seen = JSON.stringify(await page.evaluate(() => (window as any).partyViews));
  for (const bad of ['member-', 'device-', 'session-', 'participant-', 'party-']) expect(seen).not.toContain(bad);
});

test('the game page gets a ticket through the bridge, and none by asking the Party itself', async ({ page: host, context }) => {
  await hostWithGameOn(host);
  const page = await openGame(context);
  await expect.poll(() => lastView(page)).toMatchObject({ member: true });
  const ticket = await page.evaluate(() => (window as any).party.ticket());
  expect(ticket.ok).toBe(true);
  expect(ticket.ticket).toMatch(/^aps0\./);
  expect(Object.keys(ticket).sort()).toEqual(['expiresIn', 'ok', 'role', 'ticket']);

  // The same page calling the Party API directly, with the browser attaching the cookie:
  const direct = await page.evaluate(async (party) => {
    const out: Record<string, string> = {};
    for (const [name, init] of Object.entries({
      read: { credentials: 'include' },
      ticket: { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: '{"game":"arcade-gauntlet2"}' },
    } as Record<string, RequestInit>)) {
      try {
        const res = await fetch(`${party}/party/api/${name === 'read' ? 'state' : 'session/ticket'}`, init);
        out[name] = `answered ${res.status}`;
      } catch { out[name] = 'blocked'; }
    }
    return out;
  }, PARTY);
  expect(direct).toEqual({ read: 'blocked', ticket: 'blocked' });          // no CORS: nothing readable
});

test('a blind request from the game page changes nothing at the Party', async ({ page: host, context }) => {
  await hostWithGameOn(host);
  const page = await openGame(context);
  await expect.poll(() => lastView(page)).toMatchObject({ member: true });
  // no-cors requests are sent (cookie attached) even though the page cannot read the answer.
  await page.evaluate(async (party) => {
    await fetch(`${party}/party/api/session/end`, { method: 'POST', mode: 'no-cors', credentials: 'include', body: '{}' }).catch(() => {});
    await fetch(`${party}/party/api/leave`, { method: 'POST', mode: 'no-cors', credentials: 'include', body: '{}' }).catch(() => {});
    const form = new FormData();
    await fetch(`${party}/party/api/leave`, { method: 'POST', mode: 'no-cors', credentials: 'include', body: form }).catch(() => {});
  }, PARTY);
  // Read the Party's state as Ana without opening Party Home (which would follow the party away).
  const check = await context.newPage();
  const state = await (await check.goto(`${PARTY}/party/api/state`))!.json();
  expect(state.state).toBe('active');                                      // the round is still on
  expect(state.me.name).toBe('Ana');                                       // and Ana is still a member
  await check.close();
});

test('the host ends the round from the game page and is taken to Party Home', async ({ page: host, context }) => {
  await hostWithGameOn(host);
  const page = await openGame(context);
  await expect.poll(() => lastView(page)).toMatchObject({ host: true });
  const done = page.evaluate(() => (window as any).party.end()).catch(() => null);   // the page navigates away
  await page.waitForURL(`${PARTY}/party/`);
  await done;
  const state = await (await page.goto(`${PARTY}/party/api/state`))!.json();
  expect(state.state).toBe('lobby');
});

test('a page on an origin that is not a game origin gets nothing from the bridge', async ({ page, context }) => {
  await hostWithGameOn(page);
  const blocked: string[] = [];
  // A fresh tab: the host's own Party Home tab is busy following the party to the game.
  const other = await context.newPage();
  other.on('console', (m) => { if (/frame-ancestors|Refused to (frame|display)/i.test(m.text())) blocked.push(m.text()); });
  // The Party's own other host name is not a game origin: the browser refuses to frame the
  // bridge there (frame-ancestors), and the bridge would not answer it anyway.
  await other.goto(gameUrl(`http://127.0.0.1:${PORT}`, PARTY));
  await other.waitForTimeout(1500);
  expect(await lastView(other)).toBeNull();
  expect(await other.evaluate(() => (window as any).party.ticket())).toEqual({ ok: false, error: 'timeout' });
  expect(blocked.length).toBeGreaterThan(0);
  await other.close();
});

test('every other Party page still refuses to be framed', async ({ page }) => {
  for (const path of ['/party/', '/party/diag/']) {
    const res = await page.goto(PARTY + path);
    expect(res!.headers()['content-security-policy']).toContain("frame-ancestors 'none'");
  }
  const bridge = await page.goto(`${PARTY}/party/bridge.html`);
  const csp = bridge!.headers()['content-security-policy'];
  expect(csp).toContain(`frame-ancestors ${GAMES}`);
  expect(csp).not.toContain("frame-ancestors 'none'");
});
