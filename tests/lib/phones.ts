import { expect, type APIRequestContext, type Browser, type BrowserContext, type BrowserContextOptions, type Page } from '@playwright/test';

/**
 * Phones at one Party, for the suites that run against the dev server's real Party Core
 * (playwright.party.config.ts). Each phone is its own browser context: its own cookie jar (who it
 * is to Party Core) and its own localStorage (its profile).
 */

export type Phone = { name: string; context: BrowserContext; page: Page };

export async function phone(browser: Browser, name: string, options: BrowserContextOptions = {}): Promise<Phone> {
  const context = await browser.newContext(options);
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

/** A phone arriving at Party Home, without waiting for the page to settle: a phone that arrives in
 * the middle of a round is taken to the game's page before Party Home has drawn anything. With
 * `profile: false` it is a brand-new guest with no saved profile, so Party Core has never heard of
 * it (see `chooseName`); by default it has one and is in the Party on its own (ADR 0011 decision 2).
 * `layer: true` opts the stub game pages it opens into the Party layer (AVR-292), as party-layer.spec.ts does. */
export async function arrive(browser: Browser, who: string, { profile = true, layer = false }: { profile?: boolean; layer?: boolean } = {}): Promise<Phone> {
  const context = await browser.newContext();
  if (layer) await context.addInitScript(() => { try { localStorage.setItem('avrana-test-layer', '1'); } catch { /* none */ } });
  if (profile) await context.addInitScript((name) => { window.localStorage.setItem('wc-name', name); }, who);
  const page = await context.newPage();
  page.on('pageerror', (e) => console.log(`[${who}] pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') console.log(`[${who}] console: ${m.text()}`); });
  await page.goto('/party/');
  return { name: who, context, page };
}

/** A new guest's first step on Party Home is choosing a name (profile-ui.js); then they are in the
 * Party. `then` says where that leaves them: Party Home ('home'), a round's briefing ('scene', when
 * the Party is setting one up) or just a member ('joined', the name may carry a number if it was taken). */
export async function chooseName(p: Phone, then: 'home' | 'scene' | 'joined' = 'home') {
  await expect(p.page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(p.page.locator('#home-name'), `${p.name} is asked for a name on Home`).toBeVisible();   // Home's first step for a nameless phone (Concept K)
  expect((await view(p)).me, `${p.name} is not in the Party before choosing a name`).toBeNull();
  await p.page.locator('#home-name').click();
  await expect(p.page.locator('#profile-name')).toBeFocused();
  await p.page.locator('#profile-name').fill(p.name);
  await p.page.locator('#profile-form button[type="submit"]').click();
  if (then === 'home') await expect(p.page.locator('#party-members')).toContainText(`${p.name} (you)`);
  else if (then === 'scene') await expect(p.page.locator('#scene')).toBeVisible();
  await expect.poll(async () => (await view(p)).me?.name, `${p.name} is in the Party`).toMatch(new RegExp(`^${p.name}( [0-9]+)?$`));
}

export async function view(p: Phone) {
  const res = await p.page.request.get('/party/api/state');
  expect(res.ok()).toBeTruthy();
  return res.json();
}

export async function post(p: Phone, path: string, body: Record<string, unknown>) {
  // What the page's own fetch sends: JSON plus the page's Origin (Party Core's CSRF guard).
  const origin = new URL(p.page.url()).origin;
  return p.page.request.post(`/party/api/${path}`, { data: body, headers: { 'Content-Type': 'application/json', Origin: origin } });
}

export async function version(p: Phone) {
  return (await view(p)).version as number;
}

/** Move the simulated Party's clock on: what Party Core does by time alone (a quiet member is
 * away after 45 s, an away Host's role passes on 30 s later), it now does. */
export async function later(request: APIRequestContext, seconds: number) {
  expect((await request.post(`/__test__/party/advance?s=${seconds}`)).status()).toBe(204);
}

/** A phone that stops asking: its page is gone, as when it is locked in a pocket. Nothing more
 * leaves it for Party Core, and what was already on its way is given a moment to land: a request
 * the page had just made could otherwise arrive after the test has moved the clock, and count
 * as the phone being here. Returns the way to let the phone ask again (before it comes back). */
export async function goQuiet(p: Phone) {
  const block = (route: { abort: () => Promise<void> }) => route.abort();
  await p.context.route('**/party/api/**', block);
  await p.page.goto('about:blank');
  await p.page.waitForTimeout(250);
  return () => p.context.unroute('**/party/api/**', block);
}

/** Party Core stops answering this phone (the Wi-Fi dropped): every new ask fails, and the ask
 * already waiting is ended by a change it was waiting for. Returns the way to bring it back. */
export async function cutOff(p: Phone, other: Phone) {
  const block = (route: { abort: () => Promise<void> }) => route.abort();
  await p.context.route('**/party/api/state**', block);
  expect((await post(other, 'rename', { name: other.name, avatar: 'gaze-05' })).status()).toBe(200);
  return () => p.context.unroute('**/party/api/state**', block);
}

export async function endForEveryone(host: Phone) {
  const end = await post(host, 'session/end', { if_version: await version(host) });
  expect(end.status()).toBe(200);
}
