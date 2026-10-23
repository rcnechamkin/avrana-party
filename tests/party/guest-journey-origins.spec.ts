import { test, expect } from '@playwright/test';
import { arrive, chooseName, phone, post, version, view } from '../lib/phones';

/**
 * AVR-698 (Sprint 06, track 06C), the game-origin case of the guest journey (ADR 0013): a guest who
 * is NEW to the Party arrives after the round has started and is taken to the game on its registered
 * game origin, once, as a watcher, without a second copy of anyone in the Party. The rest of the
 * journey is guest-journey.spec.ts; the moves between the two origins themselves are
 * follow-origin.spec.ts. Runs in the two-origins-chromium project (games registered to
 * games.avrana.test, which Chromium resolves to the dev server).
 *
 * Tier 2: Chromium emulating a Pixel 7, plain HTTP on two host names of one site, stub game pages
 * that do not follow the Party themselves on the game origin. Not Safari, not HTTPS, not the
 * `__Host-` cookie, not nginx: Tier 3, the owner's.
 */
const PORT = Number(process.env.AVRANA_PARTY_ORIGIN_DEV_PORT || Number(process.env.AVRANA_PARTY_DEV_PORT || 8184) + 1);
const GAMES = `http://games.avrana.test:${PORT}`;
const ROUND = `${GAMES}/games/expo/?avrana=1`;

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

test('a guest new to the Party arrives mid-round: taken to the registered game origin once, watching, and counted once', async ({ browser }) => {
  const ana = await phone(browser, 'Ana');
  const ben = await arrive(browser, 'Ben', { profile: false });
  await chooseName(ben);
  expect((await post(ana, 'session/launch', { game: 'expo', if_version: await version(ana) })).status()).toBe(200);
  for (const p of [ana, ben]) await expect(p.page, p.name).toHaveURL(ROUND);

  const cy = await arrive(browser, 'Cy', { profile: false });
  const navigations: string[] = [];
  cy.context.on('request', (r) => { if (r.isNavigationRequest()) navigations.push(r.url()); });
  // she is not in the Party yet, so she is on Party Home until she has a name; then the Party takes her where it is
  await chooseName(cy, 'joined');
  await expect(cy.page).toHaveURL(ROUND);
  expect(navigations.filter((u) => u.includes('/games/')), 'only ever the registered origin, never the Party origin\'s copy').toEqual([ROUND]);
  const v = await view(ana);
  expect(v.members.map((m: { name: string }) => m.name).sort()).toEqual(['Ana', 'Ben', 'Cy']);
  expect(new Set(v.members.map((m: { id: string }) => m.id)).size).toBe(3);
  expect(v.session.players, 'two seats, both taken before she came').toBe(2);
  for (const p of [ana, ben, cy]) await p.context.close();
});
