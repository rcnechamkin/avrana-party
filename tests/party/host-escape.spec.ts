import { test, expect, type Page } from '@playwright/test';
import { sideways, smallTargets, startForEveryone } from '../lib/frame';
import { phone, post, version, view, type Phone } from '../lib/phones';

/**
 * AVR-476: the Host's way out of a round whose game fills the whole screen. A game page owns the
 * viewport during a round (ADR 0011 decision 5), so nothing the Party draws there can be relied on
 * to stay reachable: OpenCE's canvas covered the End control. What the Party owns, and the game page
 * cannot cover, is the browser's own Back. The Host's Party Home stays in the history, so Back brings
 * the Host to the Party's way out (index.html #going-host): return to the game, or end the round for
 * everyone, on the Party's origin. Everyone else's Back is unchanged.
 *
 * Tier 2: Chromium as a Pixel 7 (touch), the dev server's real Party Core, stub game pages; the
 * full-screen game is simulated by a layer over the whole stub page. Not a phone: iPhone Safari's
 * edge swipe and Android's back gesture are Tier 3, the owner's.
 */

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

/** What OpenCE did: a game surface over the whole page, above everything the page had drawn. */
async function fillScreen(page: Page) {
  await page.evaluate(() => {
    const cover = document.createElement('canvas');
    cover.id = 'game-fills-the-screen';
    cover.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;z-index:2147483647;background:#000';
    document.body.append(cover);
  });
}

const atGame = /\/games\/expo\/\?avrana=1/;
const atHome = /\/party\/(#.*)?$/;           // Party Home, on whichever of its pages the phone was

/** The Host starts the round with Party Home as the only page in this tab's history (a phone that
 * opened Party Home and started at once, or came back to it for Play again): no page of the
 * Party's own lies behind the game, so only the Party's choice to keep Party Home makes Back work.
 * `viaLibrary` starts it from the game's page in the Library instead, as most Hosts do. */
async function startRound(host: Phone, others: Phone[], viaLibrary = false) {
  if (viaLibrary) await startForEveryone(host.page, 'expo');
  else expect((await post(host, 'session/launch', { game: 'expo', if_version: await version(host) })).status()).toBe(200);
  for (const p of [host, ...others]) await expect(p.page).toHaveURL(atGame);
}

test.describe('the Host\'s way out of a full-screen game', () => {
  let host: Phone, bob: Phone;

  test.beforeEach(async ({ browser }) => {
    host = await phone(browser, 'Ada');
    bob = await phone(browser, 'Bob');
  });
  test.afterEach(async () => { for (const p of [host, bob]) await p.context.close(); });

  test('covered: the page\'s own End cannot be reached, the browser\'s Back brings the Host to the Party\'s End, by touch', async () => {
    await startRound(host, [bob]);
    await expect(host.page.locator('#avrana-party-end')).toBeVisible();
    await fillScreen(host.page);
    const box = (await host.page.locator('#avrana-party-end').boundingBox())!;
    const onTop = await host.page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.id, [box.x + box.width / 2, box.y + box.height / 2]);
    expect(onTop, 'the game covers the End control, as OpenCE did').toBe('game-fills-the-screen');

    await host.page.goBack();
    await expect(host.page).toHaveURL(atHome);
    await expect(host.page.locator('#going-host')).toBeVisible();
    await expect(host.page.locator('#going-return')).toHaveText(/^Return to /);
    await host.page.locator('#going-lobby').tap();
    await expect(host.page.locator('#going-confirm-text')).toHaveText('This ends the round for everyone.');
    await host.page.locator('#going-lobby-yes').tap();
    for (const p of [host, bob]) await expect(p.page, p.name).toHaveURL(atHome);
    expect((await view(bob)).location.at).toBe('home');
  });

  test('Return to the game: Back, then the Party\'s Return, and Back again still finds the way out', async () => {
    await startRound(host, [bob]);
    await host.page.goBack();
    await expect(host.page.locator('#going-host')).toBeVisible();
    await host.page.locator('#going-return').tap();
    await expect(host.page).toHaveURL(atGame);
    expect((await view(host)).location.at, 'looking at the way out changed nothing').toBe('game');
    await host.page.goBack();
    await expect(host.page.locator('#going-host')).toBeVisible();
  });

  test('not the Host: Back never offers the round\'s end, and Party Home sends the phone back to the game', async () => {
    await startRound(host, [bob]);
    await expect(bob.page.locator('#avrana-party-end')).toHaveCount(0);
    await bob.page.goBack();
    expect(bob.page.url(), 'a follower\'s Back does not bounce through Party Home').not.toMatch(atHome);
    await bob.page.goto('/party/');
    await expect(bob.page).toHaveURL(atGame);
    await expect(bob.page.locator('#going-host')).toHaveCount(0);
    const refused = await post(bob, 'session/end', { if_version: await version(bob) });
    expect(refused.status(), 'Party Core refuses a non-Host\'s end, whatever a page shows').toBe(403);
    expect((await view(bob)).location.at).toBe('game');
  });

  test('keyboard only: focus lands on the way out, every choice is reachable and can be backed out of', async () => {
    await startRound(host, [bob]);
    await host.page.goBack();
    await expect(host.page.locator('#going-text')).toBeFocused();
    await host.page.keyboard.press('Tab');
    await expect(host.page.locator('#going-return')).toBeFocused();
    await host.page.keyboard.press('Tab');
    await expect(host.page.locator('#going-lobby')).toBeFocused();
    await host.page.keyboard.press('Enter');
    await expect(host.page.locator('#going-confirm-text')).toBeFocused();
    await host.page.keyboard.press('Tab');
    await host.page.keyboard.press('Tab');
    await expect(host.page.locator('#going-lobby-no')).toBeFocused();
    await host.page.keyboard.press('Enter');
    await expect(host.page.locator('#going-return')).toBeFocused();
    expect((await view(host)).location.at).toBe('game');
    await host.page.keyboard.press('Tab');
    await host.page.keyboard.press('Enter');
    await host.page.keyboard.press('Tab');
    await expect(host.page.locator('#going-lobby-yes')).toBeFocused();
    await host.page.keyboard.press('Enter');
    for (const p of [host, bob]) await expect(p.page, p.name).toHaveURL(atHome);
  });

  test('a small phone (320 x 568): the way out fits, nothing sideways, thumb-sized targets', async () => {
    await host.page.setViewportSize({ width: 320, height: 568 });
    await startRound(host, [bob]);
    await host.page.goBack();
    await expect(host.page.locator('#going-host')).toBeVisible();
    for (const id of ['#going-return', '#going-lobby']) {
      const b = (await host.page.locator(id).boundingBox())!;
      expect(b.x >= 0 && b.y >= 0 && b.x + b.width <= 320 && b.y + b.height <= 568, `${id} on screen: ${JSON.stringify(b)}`).toBe(true);
    }
    expect(await smallTargets(host.page, '#going-host button')).toEqual([]);
    expect(await sideways(host.page)).toBe(0);
    await host.page.locator('#going-lobby').tap();
    expect(await smallTargets(host.page, '#going-confirm button')).toEqual([]);
  });

  test('interrupted: the round ends elsewhere while the Host is on the way out; it goes, and nothing is ended twice', async () => {
    await startRound(host, [bob]);
    await host.page.goBack();
    await expect(host.page.locator('#going-host')).toBeVisible();
    expect((await post(host, 'session/end', { if_version: await version(host) })).status()).toBe(200);   // as the game's own End would
    await expect(host.page.locator('#going-host')).toBeHidden();
    await expect(host.page.locator('html')).toHaveAttribute('data-screen', 'main');
    await expect(bob.page).toHaveURL(atHome);
  });

  test('a slow first try: the watchdog\'s retry also keeps Party Home behind the Host\'s game', async () => {
    test.setTimeout(60_000);
    let held: import('@playwright/test').Route | null = null;
    await host.page.route('**/games/expo/**', async (route) => {
      if (held === null && route.request().isNavigationRequest()) { held = route; return; }   // the first try never answers
      await route.continue();
    });
    expect((await post(host, 'session/launch', { game: 'expo', if_version: await version(host) })).status()).toBe(200);
    await expect(bob.page).toHaveURL(atGame);
    await expect(host.page).toHaveURL(atGame, { timeout: 20_000 });      // the watchdog's one retry, about 8 s on
    expect(held, 'the first navigation was the one held').not.toBeNull();
    await host.page.goBack();
    await expect(host.page).toHaveURL(atHome);
    await expect(host.page.locator('#going-host')).toBeVisible();
    await (held as import('@playwright/test').Route | null)?.abort().catch(() => {});
  });

  test('reconnecting: an End that cannot reach the Party says so, and works once the phone is back', async () => {
    await startRound(host, [bob]);
    await host.page.goBack();
    await expect(host.page.locator('#going-host')).toBeVisible();
    await host.context.setOffline(true);
    await host.page.locator('#going-lobby').tap();
    await host.page.locator('#going-lobby-yes').tap();
    await expect(host.page.locator('#going-problem')).not.toHaveText('');
    expect((await view(bob)).location.at, 'nothing changed while the phone was away').toBe('game');
    await host.context.setOffline(false);
    await expect(host.page.locator('#going-host')).toBeVisible();
    await host.page.locator('#going-lobby').tap();                         // the failed End closed the question; ask again
    await host.page.locator('#going-lobby-yes').tap();
    for (const p of [host, bob]) await expect(p.page, p.name).toHaveURL(atHome);
  });
});
