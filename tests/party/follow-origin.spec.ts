import { test, expect, type Page } from '@playwright/test';
import { phone, post, version, type Phone } from '../lib/phones';

/**
 * AVR-307 (Tier 2, ADR 0013): a member whose page is a game page on the PARTY origin goes to a
 * started game's registered game origin, as a phone on Party Home does, and is never shown the
 * game on the Party origin on the way. A real Party Core behind the dev server with every game
 * registered to http://games.avrana.test:<port> (--game-origin); Chromium resolves the test host
 * names to the dev server (playwright.party.config.ts, project two-origins-chromium).
 *
 * Not shown: real Safari or Android Chrome, HTTPS, the `__Host-` cookie, nginx. Tier 3, the owner's.
 */
const PORT = Number(process.env.AVRANA_PARTY_ORIGIN_DEV_PORT || Number(process.env.AVRANA_PARTY_DEV_PORT || 8184) + 1);
const PARTY = `http://127.0.0.1:${PORT}`;           // the Party origin (a secure context, so the arcade page follows)
const GAMES = `http://games.avrana.test:${PORT}`;   // what Party Core registers as the game origin
const NEXT = `${GAMES}/games/expo/?avrana=1`;        // game B: starts at once, no setup scene

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

const atPartyHome = (page: Page) => /\/party\/(#.*)?$/.test(new URL(page.url()).pathname + new URL(page.url()).hash);

test('the host starts B: a phone on Party Home and a member on the Party origin\'s page of A both end on B\'s registered origin, never on B at the Party origin', async ({ browser }) => {
  const ana = await phone(browser, 'Ana'), ben = await phone(browser, 'Ben');
  const seen: string[] = [];
  for (const p of [ana, ben]) p.context.on('request', (r) => { if (r.isNavigationRequest()) seen.push(r.url()); });

  // A is on: the arcade (game A starts at once). Both phones are taken to its registered origin.
  expect((await post(ana, 'session/launch', { game: 'arcade-gauntlet2', if_version: await version(ana) })).status()).toBe(200);
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(new RegExp(`^${GAMES}/arcade/`));

  // Ben opens A's page on the Party origin by hand (a bookmark): the party is there, so it stays.
  await ben.page.goto(`${PARTY}/arcade/`);
  await expect(ben.page.locator('#connect')).toBeVisible();
  await ben.page.waitForTimeout(1000);
  expect(new URL(ben.page.url()).origin).toBe(PARTY);

  // Ana's Party Home (the Host's way out of a round she was already taken to, as in the provider suite).
  const home = await ana.context.newPage();
  await home.goto(`${PARTY}/party/`);
  await expect(home.locator('#going-host')).toBeVisible();
  expect(atPartyHome(home)).toBe(true);
  seen.length = 0;

  // The Host switches to B from Party Home's phone: the party moves to B.
  const res = await home.evaluate(async () => {
    const state = await (await fetch('/party/api/state', { cache: 'no-store' })).json();
    const r = await fetch('/party/api/session/switch', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ game: 'expo', if_version: state.version }) });
    return r.status;
  });
  expect(res).toBe(200);
  for (const page of [home, ben.page]) await expect(page).toHaveURL(NEXT);
  await ben.page.waitForTimeout(1000);
  await expect(ben.page).toHaveURL(NEXT);                       // and stays: no loop back
  expect(seen.filter((u) => u.startsWith(`${PARTY}/games/`)), 'B was never requested on the Party origin').toEqual([]);
  await ana.context.close(); await ben.context.close();
});

test('AVR-476: from a game on its registered origin, the Host\'s Back crosses back to the Party\'s way out; a follower\'s does not', async ({ browser }) => {
  const ana = await phone(browser, 'Ana'), ben = await phone(browser, 'Ben');
  expect((await post(ana, 'session/launch', { game: 'expo', if_version: await version(ana) })).status()).toBe(200);
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(NEXT);
  await ana.page.goBack();
  expect(new URL(ana.page.url()).origin).toBe(PARTY);
  await expect(ana.page.locator('#going-host')).toBeVisible();
  await ana.page.locator('#going-return').tap();
  await expect(ana.page).toHaveURL(NEXT);
  await ben.page.goBack();
  expect(ben.page.url().startsWith(`${PARTY}/party/`), 'a follower is not walked back through Party Home').toBe(false);
  await ana.context.close(); await ben.context.close();
});
