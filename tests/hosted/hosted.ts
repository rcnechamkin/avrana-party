import { expect, type Browser, type BrowserContext, type Page, type TestInfo } from '@playwright/test';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

/**
 * The hosted acceptance harness's view of a deployment (playwright.hosted.config.ts). Everything goes
 * through what a tester's phone has: the pages, the Party API with the device cookie, and the
 * access gateway's cookie. No control route, no clock, no reset: a run starts by ending whatever round
 * is on, through the Host's own controls.
 */

export const BASE = new URL(process.env.HOSTED_BASE_URL!).origin;
export const GAMES = process.env.HOSTED_GAME_ORIGIN
  ? new URL(process.env.HOSTED_GAME_ORIGIN).origin
  : `${new URL(BASE).protocol}//games.${new URL(BASE).host}`;
export const ACCESS = process.env.HOSTED_ACCESS_CLIENT_ID && process.env.HOSTED_ACCESS_CLIENT_SECRET
  ? { 'CF-Access-Client-Id': process.env.HOSTED_ACCESS_CLIENT_ID, 'CF-Access-Client-Secret': process.env.HOSTED_ACCESS_CLIENT_SECRET }
  : null;
export const EXPECT_ACCESS = process.env.HOSTED_EXPECT_ACCESS === '1';
export const OWNER_ASSIST = process.env.HOSTED_OWNER_ASSIST === '1';
export const GAME_LIST = (process.env.HOSTED_GAMES || '').split(',').map((s) => s.trim()).filter(Boolean);
const GAMES_REPO = process.env.HOSTED_GAMES_REPO ? resolve(process.env.HOSTED_GAMES_REPO) : null;
export const ACCESS_COOKIE = 'CF_Authorization';

export type Phone = { name: string; context: BrowserContext; page: Page; errors: string[] };

// A deployed Party outlives a run: members of earlier runs stay in it (away) until Party Core's own timing
// lets them go. Every name in this run carries the run's tag, so a phone is never mistaken for another run's.
export const RUN = Math.random().toString(36).slice(2, 5);
export const who = (name: string) => `${name} ${RUN}`;

/** A new phone: its own cookies and storage. Signed in to the access gateway the way a tester is (its
 * cookie on both hostnames, obtained here with the service token), or with no sign-in at all. */
export async function phone(browser: Browser, base: string, { signedIn = true, join = true } = {}): Promise<Phone> {
  const name = who(base);
  const context = await browser.newContext({ serviceWorkers: 'block' });
  if (signedIn) await signIn(context);
  await context.addInitScript((n) => { try { localStorage.setItem('wc-name', n); } catch { /* none */ } }, name);
  const page = await context.newPage();
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(`${name}: ${e.message}`));
  const p = { name, context, page, errors };
  if (join) {
    await page.goto(`${BASE}/party/`);
    // A round that is already on takes an arriving phone straight to the game's page (the Party moves it).
    await expect.poll(async () => page.url().includes('/games/')
      || (await page.locator('html').getAttribute('data-ready').catch(() => null)) === 'true').toBe(true);
    await expect.poll(async () => (await state(p))?.me?.name, `${name} is in the Party`).toBe(name);
  }
  return p;
}

/** The access gateway's cookie for both hostnames, as a browser gets it after signing in. With a service
 * token the gateway answers the first request with that cookie; if it does not, the token's headers ride on
 * every request instead (signIn says which, in the report). Without a token, nothing (a local harness). */
export async function signIn(context: BrowserContext) {
  if (!ACCESS) return 'none';
  for (const origin of [BASE, GAMES]) {
    await context.request.get(`${origin}/party/api/origin.json`, { headers: ACCESS, maxRedirects: 0 }).catch(() => null);
  }
  const cookies = await context.cookies([BASE, GAMES]);
  const both = [BASE, GAMES].every((o) => cookies.some((c) => c.name === ACCESS_COOKIE && o.endsWith(c.domain.replace(/^\./, ''))));
  if (both) return 'cookie';
  await context.setExtraHTTPHeaders(ACCESS);
  return 'headers';
}

/** Party Core's view for this phone, asked with the phone's own cookies (from any page it is on, the game
 * origin included, as its Party Home would ask). */
export async function state(p: Phone) {
  const res = await api(p, 'GET', 'state').catch(() => null);
  return res && res.ok() ? res.json() : null;
}

/** What the phone's Party Home sends for an action: JSON and the Party's Origin (Party Core's CSRF guard). */
export async function post(p: Phone, path: string, body: Record<string, unknown>) {
  return api(p, 'POST', path, body);
}

// HOSTED_RESOLVE_LOOPBACK (a local two-origin harness): the browser maps *.avrana.test to loopback, but an
// API request from the test runner resolves names itself, so it goes to 127.0.0.1 with the Party's Host and
// the phone's own cookies for that host. Against a real deployment the request goes to the name, as is.
const LOOPBACK = process.env.HOSTED_RESOLVE_LOOPBACK === '1';
async function api(p: Phone, method: 'GET' | 'POST', path: string, body?: Record<string, unknown>) {
  const headers: Record<string, string> = { 'Cache-Control': 'no-cache' };
  if (method === 'POST') Object.assign(headers, { 'Content-Type': 'application/json', Origin: BASE });
  let url = `${BASE}/party/api/${path}`;
  if (LOOPBACK) {
    const u = new URL(BASE);
    url = `${u.protocol}//127.0.0.1:${u.port || (u.protocol === 'https:' ? 443 : 80)}/party/api/${path}`;
    headers.Host = u.host;
    headers.Cookie = (await p.context.cookies(`${BASE}/party/api/`)).map((c) => `${c.name}=${c.value}`).join('; ');
  }
  return method === 'GET' ? p.context.request.get(url, { headers }) : p.context.request.post(url, { headers, data: body });
}

/** Local two-origin harness only: a fresh Party before a case, so one failed case cannot strand the next.
 * A deployed site has no reset route; there a case waits out Party Core's own timing instead (homeFor). */
export async function resetIfLocal() {
  if (!LOOPBACK) return;
  const u = new URL(BASE);
  const res = await fetch(`${u.protocol}//127.0.0.1:${u.port}/__test__/party/reset`, { method: 'POST', headers: { Host: u.host } });
  expect(res.status, 'the local dev server resets the Party').toBe(204);
}

/** What is deployed, as the status endpoint says: recorded once per run so every result names the commits it tested. */
export { api };
export async function recordDeployment(p: Phone, info: TestInfo) {
  const doc = await (await api(p, 'GET', 'status')).json();
  const record = {
    base: BASE, games_origin: GAMES, at: new Date().toISOString(), run: RUN,
    party: doc?.deployment?.party?.sha ?? doc?.party?.deployed_sha ?? null,
    games: doc?.deployment?.games?.sha ?? doc?.games?.deployed_sha ?? null,
    web_build: doc?.web_release?.build ?? null,
    summary: doc?.summary?.state ?? null,
    access: ACCESS ? 'service-token' : 'none',
  };
  if (!existsSync('test-results')) mkdirSync('test-results', { recursive: true });
  writeFileSync(join('test-results', 'hosted-run.json'), JSON.stringify(record, null, 2));
  await info.attach('deployment', { body: JSON.stringify(record, null, 2), contentType: 'application/json' });
  return record;
}

/** Everyone back at Party Home, by the Host's own control (lobby). When the Host is a phone of an earlier
 * run that has gone, Party Core passes hosting to someone who is here (away after 45 s, 30 s more): this
 * waits for that, as the people at a real Party would. Returns the phone that is now the Host. */
export async function homeFor(...phones: Phone[]) {
  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    const views = await Promise.all(phones.map(state));
    const v = views.find((x) => x?.me);
    if (v && v.location?.at === 'home') return phones[views.findIndex((x) => x?.me?.host)] ?? null;
    const i = views.findIndex((x) => x?.me?.host);
    if (i >= 0) {
      const res = await post(phones[i], 'lobby', { if_version: views[i].version });
      if (res.ok()) {
        for (const p of phones) await expect(p.page).toHaveURL(`${BASE}/party/`, { timeout: 60_000 });
        return phones[i];
      }
    }
    await phones[0].page.waitForTimeout(3000);
  }
  throw new Error('the Party did not come home within 180 s');
}

/** The phone among these that Party Core says is the Host, waiting for hosting to pass to one of them. */
export async function hostOf(phones: Phone[], ms = 180_000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    const views = await Promise.all(phones.map(state));
    const i = views.findIndex((x) => x?.me?.host);
    if (i >= 0) return phones[i];
    await phones[0].page.waitForTimeout(3000);
  }
  throw new Error('none of these phones became the Host');
}

/** The Host picks a game and every phone answers the briefing (Play, or Watch for `watchers`) where the
 * game asks; then the Host starts. Returns when every phone is on the game's page. */
export async function launch(host: Phone, others: Phone[], id: string, watchers: Phone[] = []) {
  const everyone = [host, ...others];
  await host.page.locator('#nav a[data-go="library"]').click();
  await host.page.locator(`#games [data-game="${id}"]`).click();
  await host.page.locator(`#game-detail[data-id="${id}"]`).getByRole('button', { name: 'Start for everyone' }).click();
  const atGame = (p: Phone) => p.page.url().startsWith(`${GAMES}/games/${id}/`) || p.page.url().startsWith(`${BASE}/games/${id}/`);
  // A game with a briefing: each phone chooses; a game without one goes straight to its page.
  const deadline = Date.now() + 60_000;
  while (!everyone.every(atGame) && Date.now() < deadline) {
    for (const p of everyone) {
      if (atGame(p)) continue;
      const choice = p.page.locator(watchers.includes(p) ? '#choose-watch' : '#choose-play');
      if (await choice.isVisible().catch(() => false) && (await choice.getAttribute('aria-pressed')) !== 'true') {
        await choice.click().catch(() => undefined);
        const ok = p.page.locator('#rules-ok');
        if (await ok.isVisible().catch(() => false)) await ok.click().catch(() => undefined);
      }
    }
    const start = host.page.locator('#scene-start');
    if (await start.isVisible().catch(() => false) && await start.isEnabled().catch(() => false)) await start.click().catch(() => undefined);
    await host.page.waitForTimeout(300);
  }
  for (const p of everyone) expect(atGame(p), `${p.name} reached ${id}'s page (${p.page.url()})`).toBe(true);
}

/** The game developer's driver for `id` (HOSTED_GAMES_REPO/<id>/party-driver.mjs): one person's action per call. */
export async function driverFor(id: string): Promise<{ step: (page: Page) => Promise<'done' | 'acted' | 'waiting'> }> {
  if (!GAMES_REPO) throw new Error('HOSTED_GAMES_REPO names the Games checkout whose drivers play the games');
  const dirs: Record<string, string> = { tanks: 'colyseus-tanks' };
  const file = join(GAMES_REPO, dirs[id] ?? id, 'party-driver.mjs');
  if (!existsSync(file)) throw new Error(`no driver for ${id}: ${file}`);
  return import(pathToFileURL(file).href);
}

/** Play until every player's page says the game is over, or the deadline passes. */
export async function playToTheEnd(id: string, players: Phone[], ms = 600_000) {
  const driver = await driverFor(id);
  const done = new Set<Phone>();
  const deadline = Date.now() + ms;
  let actions = 0;
  while (done.size < players.length && Date.now() < deadline) {
    let acted = false;
    for (const p of players) {
      if (done.has(p)) continue;
      const said = await driver.step(p.page).catch(() => 'waiting' as const);
      if (said === 'done') done.add(p);
      if (said === 'acted') { acted = true; actions++; }
    }
    if (!acted) await players[0].page.waitForTimeout(200);
  }
  return { finished: done.size === players.length, actions };
}

export async function close(...phones: (Phone | null | undefined)[]) {
  for (const p of phones) if (p) await p.context.close().catch(() => undefined);
}
