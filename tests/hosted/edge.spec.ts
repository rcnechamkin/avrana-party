import { test, expect, request as playwrightRequest } from '@playwright/test';
import { ACCESS, ACCESS_COOKIE, BASE, EXPECT_ACCESS, GAMES, GATE_COOKIE, GATE_PASSWORD, close, phone, recordDeployment, signIn } from './hosted';

// The hosted edge (docs/design/HOSTED-STAGING.md §5 and §7): who may reach the Party and the game origin, what
// each origin serves and refuses, and that the access gateway's identity never becomes Party identity. One
// project is enough: none of this depends on the phone's size.
test.beforeEach(({}, info) => test.skip(info.project.name !== 'android-size', 'edge checks run once'));

test('the run records which commits it is testing', async ({ browser }, info) => {
  const ada = await phone(browser, 'EdgeA');
  try {
    const record = await recordDeployment(ada, info);
    console.log(`hosted run against party ${record.party} games ${record.games} build ${record.web_build}`);
    expect(record.party, 'the status endpoint names the deployed Party commit').toMatch(/^[0-9a-f]{40}$/);
  } finally { await close(ada); }
});

test('a stranger gets the access gateway, never the Party or a game, on both hostnames', async () => {
  test.skip(!EXPECT_ACCESS, 'HOSTED_EXPECT_ACCESS=1: the deployment is behind the access gateway');
  const stranger = await playwrightRequest.newContext();
  try {
    for (const url of [`${BASE}/party/`, `${BASE}/party/api/state`, `${BASE}/party/api/status`, `${BASE}/party/bridge.html`,
      `${GAMES}/games/bestguess/`, `${GAMES}/games/checkers/api/poll`, `${BASE}/internal/ended`]) {
      const res = await stranger.get(url, { maxRedirects: 0 });
      const where = res.headers()['location'] || '';
      expect([302, 401, 403], url).toContain(res.status());
      if (res.status() === 302) expect(where, url).toMatch(/cloudflareaccess\.com|\/cdn-cgi\/access\/login/);
      const body = await res.text();
      expect(body, url).not.toContain('avrana.origin/v0');
      expect(body, url).not.toContain('"party"');
    }
    // A forged assertion is not a sign-in.
    const forged = await stranger.get(`${BASE}/party/api/state`, { maxRedirects: 0, headers: {
      'Cf-Access-Jwt-Assertion': 'eyJhbGciOiJub25lIn0.eyJlbWFpbCI6Im93bmVyQGV4YW1wbGUuY29tIn0.', Cookie: `${ACCESS_COOKIE}=forged` } });
    expect([302, 401, 403]).toContain(forged.status());
  } finally { await stranger.dispose(); }
});

test('a stranger gets the password page, never the Party or a game, on both hostnames', async () => {
  test.skip(!GATE_PASSWORD, 'HOSTED_GATE_PASSWORD: the deployment is behind the password gate');
  const stranger = await playwrightRequest.newContext();
  try {
    for (const url of [`${BASE}/party/`, `${BASE}/party/api/state`, `${BASE}/party/api/status`, `${BASE}/party/bridge.html`,
      `${GAMES}/games/bestguess/`, `${GAMES}/games/checkers/app.mjs`, `${BASE}/games/checkers/api/party`, `${BASE}/internal/ended`,
      `${BASE}/__gatex`]) {
      const res = await stranger.get(url, { maxRedirects: 0 });
      expect(res.status(), url).toBe(302);
      expect(res.headers()['location'], url).toBe(`${BASE}/__gate/`);
      const body = await res.text();
      expect(body, url).not.toContain('avrana.origin/v0');
      expect(body, url).not.toContain('"party"');
    }
    // A game's API and rules card stay open on the game origin (its clients fetch them with no credentials), and
    // they hold nothing a seat has not earned: the Party origin to talk to, the rules, and a refusal.
    expect(await (await stranger.get(`${GAMES}/games/checkers/api/party`)).json()).toEqual({ partyOrigin: BASE });
    expect((await stranger.get(`${GAMES}/games/checkers/onboarding.json`)).status()).toBe(200);
    expect((await stranger.post(`${GAMES}/games/checkers/api/poll`, { data: {} })).status()).toBeGreaterThanOrEqual(400);
    // A made-up gate cookie is no key, and a wrong password gets the form again with no cookie.
    const forged = await stranger.get(`${BASE}/party/api/state`, { maxRedirects: 0, headers: { Cookie: `${GATE_COOKIE}=${'0'.repeat(32)}` } });
    expect(forged.status()).toBe(302);
    const form = await stranger.get(`${BASE}/__gate/`);
    expect(form.status()).toBe(200);
    expect(await form.text()).toContain('type="password"');
    const wrong = await stranger.post(`${BASE}/__gate/`, { form: { password: `${GATE_PASSWORD}x` }, maxRedirects: 0 });
    expect(wrong.status()).toBe(401);
    expect(wrong.headers()['set-cookie']).toBeUndefined();
  } finally { await stranger.dispose(); }
});

test('the Party origin serves the Party with its own guards, and the game origin serves none of it', async ({ browser }) => {
  const ada = await phone(browser, 'EdgeB');
  try {
    const req = ada.context.request;
    const origin = await (await req.get(`${BASE}/party/api/origin.json`)).json();
    expect(origin).toMatchObject({ schema: 'avrana.origin/v0', network: 'hosted', scheme: 'https' });
    expect(JSON.stringify(origin)).not.toMatch(/\b(10|127|192\.168)\.\d+\.\d+\.\d+/);
    const shell = await req.get(`${BASE}/party/`);
    expect(shell.headers()['content-security-policy']).toContain("frame-ancestors 'none'");
    const bridge = await req.get(`${BASE}/party/bridge.html`);
    expect(bridge.headers()['content-security-policy']).toContain(`frame-ancestors ${GAMES}`);
    expect(bridge.headers()['cross-origin-resource-policy']).toBe('same-site');
    for (const path of ['/party/', '/party/api/state', '/party/bridge.html', '/arcade/', '/games/checkers/avrana/launch', '/internal/ended']) {
      expect((await req.get(`${GAMES}${path}`, { maxRedirects: 0 })).status(), `game origin ${path}`).toBe(404);
    }
    for (const path of ['/internal/ended', '/arcade/', '/games/bluff/', '/api/games', '/games/checkers/avrana/end']) {
      expect((await req.get(`${BASE}${path}`, { maxRedirects: 0 })).status(), `party origin ${path}`).toBe(404);
    }
    // the device cookie: host-only, Secure, HttpOnly, and never on the game origin
    const cookies = await ada.context.cookies([BASE, GAMES]);
    const device = cookies.filter((c) => c.name.startsWith('__Host-avrana_device'));
    expect(device).toHaveLength(1);
    expect(device[0]).toMatchObject({ secure: true, httpOnly: true, sameSite: 'Lax', path: '/' });
    expect(device[0].domain).toBe(new URL(BASE).hostname);
    expect(await ada.page.evaluate(() => document.cookie)).not.toContain('avrana_device');
  } finally { await close(ada); }
});

test('Party Core keeps its own authority: a foreign Origin is refused, and proxy or gateway headers name nobody', async ({ browser }) => {
  const ada = await phone(browser, 'EdgeC'), dan = await phone(browser, 'EdgeD');
  try {
    const req = ada.context.request;
    const foreign = await req.post(`${BASE}/party/api/rename`, { data: { name: 'Mallory' },
      headers: { 'Content-Type': 'application/json', Origin: 'https://evil.example' } });
    expect(foreign.status()).toBe(403);
    // Claim to be Dan, by every header a proxy or the gateway could carry: Ada stays Ada.
    const before = (await (await req.get(`${BASE}/party/api/state`)).json()).me;
    const spoofed = await req.get(`${BASE}/party/api/state`, { headers: {
      'X-Forwarded-For': '10.42.0.23', 'X-Real-IP': '10.42.0.23', Forwarded: 'for=10.42.0.23',
      'Cf-Access-Authenticated-User-Email': 'dan@example.com',
      'X-Forwarded-Host': 'party.avrana.net', 'X-Avrana-Member': (await (await dan.context.request.get(`${BASE}/party/api/state`)).json()).me.id } });
    expect(spoofed.ok()).toBeTruthy();
    expect((await spoofed.json()).me).toEqual(before);
    // Cloudflare's edge refuses a client-sent Cf-Connecting-Ip outright (403, its own page); if it ever passes one
    // through, the Party must still answer as Ada.
    const cfip = await req.get(`${BASE}/party/api/state`, { headers: { 'Cf-Connecting-Ip': '10.42.0.23' } });
    if (cfip.ok()) expect((await cfip.json()).me).toEqual(before);
    else expect(cfip.status()).toBe(403);
    // and the gateway's sign-in alone is no Party identity: a signed-in browser with no device cookie is nobody yet
    const fresh = await browser.newContext({ serviceWorkers: 'block' });
    await signIn(fresh);
    const anon = await (await fresh.request.get(`${BASE}/party/api/state`)).json();
    expect(anon.me).toBeNull();
    await fresh.close();
  } finally { await close(ada, dan); }
});

test('an expired gateway sign-in on an open Party Home says "Sign in again", and signing in again restores the person', async ({ browser }) => {
  test.skip(!ACCESS || !EXPECT_ACCESS, 'needs the access gateway and a service token');
  const ada = await phone(browser, 'EdgeE');
  try {
    const me = (await (await ada.context.request.get(`${BASE}/party/api/state`)).json()).me;
    // The session ends: the gateway's cookie is gone (as at expiry); the device cookie stays.
    const kept = (await ada.context.cookies()).filter((c) => c.name !== ACCESS_COOKIE);
    await ada.context.clearCookies();
    await ada.context.addCookies(kept);
    await ada.context.setExtraHTTPHeaders({});
    await ada.page.evaluate(() => window.dispatchEvent(new Event('online')));
    await expect(ada.page.locator('html')).toHaveAttribute('data-link', 'signin', { timeout: 60_000 });
    await expect(ada.page.locator('#net-title')).toHaveText(/sign in again/i);
    // Signing in again (the service token here; a person's one-time PIN) and reloading: the same member.
    await signIn(ada.context);
    await ada.page.reload();
    await expect(ada.page.locator('html')).toHaveAttribute('data-ready', 'true');
    expect((await (await ada.context.request.get(`${BASE}/party/api/state`)).json()).me?.id).toBe(me.id);
  } finally { await close(ada); }
});
