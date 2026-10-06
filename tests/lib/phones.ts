import { expect, type APIRequestContext, type Browser, type BrowserContext, type Page } from '@playwright/test';

/**
 * Phones at one Party, for the suites that run against the dev server's real Party Core
 * (playwright.party.config.ts). Each phone is its own browser context: its own cookie jar (who it
 * is to Party Core) and its own localStorage (its profile).
 */

export type Phone = { name: string; context: BrowserContext; page: Page };

export async function phone(browser: Browser, name: string): Promise<Phone> {
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

/** A phone that stops asking: its page is gone, as when it is locked in a pocket. */
export const goQuiet = (p: Phone) => p.page.goto('about:blank');

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
