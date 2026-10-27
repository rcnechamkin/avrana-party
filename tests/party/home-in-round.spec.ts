import { test, expect } from '@playwright/test';
import { startForEveryone } from '../lib/frame';
import { endForEveryone, goQuiet, phone, post, view, type Phone } from '../lib/phones';

/**
 * Back to game (AVR-468, with the owner-gated home_in_round proposal of AVR-703 on for this dev server only):
 * a member who looked at Party Home during a round gets back to the SAME live round, seat and page with one
 * tap, after a reload, after the phone went quiet, and after a failed tap while the Wi-Fi was gone. No new
 * round, no second roster, and the Host's game never moves. A round that ended meanwhile leaves plain Home.
 * Tier 2: real Chromium, simulated appliance, stub game pages. Not a phone (iOS/Android are Tier 3, NOT RUN).
 */

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

test.describe('Back to game with two phones', () => {
  let host: Phone, bob: Phone;

  test.beforeEach(async ({ browser }) => {
    host = await phone(browser, 'Ada');
    bob = await phone(browser, 'Bob');
    await startForEveryone(host.page, 'expo');
    for (const p of [host, bob]) await expect(p.page, p.name).toHaveURL(/\/games\/expo\//);
  });

  test.afterEach(async () => { for (const p of [host, bob]) await p.context.close(); });

  async function onHome(p: Phone) {
    await expect(p.page).toHaveURL(/\/party\/(#.*)?$/);
    await expect(p.page.locator('html')).toHaveAttribute('data-ready', 'true');
    await expect(p.page.locator('#k2')).toBeVisible();
    await expect(p.page.locator('#k2-title')).toHaveText('EXPO');
    await expect(p.page.locator('#k2-back')).toBeEnabled();
  }

  test('reload, a quiet phone and a failed tap all keep the way back; one tap returns to the same round and seat', async () => {
    const before = await view(bob);
    const seatUrl = bob.page.url();
    expect(before.me.home_visit).toBe(false);
    expect(before.session.my_role).toBe('player');

    expect((await post(bob, 'home/visit', {})).status()).toBe(200);
    await onHome(bob);
    await expect(host.page).toHaveURL(/\/games\/expo\//);                  // a look is this phone's own

    // a reload: Party Core still knows this phone is looking at Home
    await bob.page.reload();
    await onHome(bob);

    // the phone went quiet (locked) and came back
    const back = await goQuiet(bob);
    await back();
    await bob.page.goto('/party/');
    await onHome(bob);

    // the Wi-Fi is gone: the tap fails, says so, and the control stays
    const block = (route: { abort: () => Promise<void> }) => route.abort();
    await bob.context.route('**/party/api/home/back', block);
    await bob.page.locator('#k2-back').click();
    await expect(bob.page.locator('#k2-error')).toHaveText('Couldn’t reach the Party. Check the Wi-Fi and try again.');
    await expect(bob.page.locator('#k2-back')).toBeEnabled();
    await expect(bob.page).toHaveURL(/\/party\/(#.*)?$/);
    await bob.context.unroute('**/party/api/home/back', block);

    // one tap: the same round, the same seat, the same page; nothing new was started
    await bob.page.locator('#k2-back').click();
    await expect(bob.page).toHaveURL(seatUrl);
    const after = await view(bob);
    expect(after.me.home_visit).toBe(false);
    expect(after.session.id).toBe(before.session.id);
    expect(after.session.my_role).toBe('player');
    expect(after.session.players).toBe(before.session.players);
    expect(after.members.length).toBe(before.members.length);
    expect(after.location).toEqual(before.location);
    await expect(host.page).toHaveURL(/\/games\/expo\//);
  });

  test('a round that ended while this phone looked at Home leaves plain Home, with no way back to a round that is gone', async () => {
    expect((await post(bob, 'home/visit', {})).status()).toBe(200);
    await onHome(bob);
    await endForEveryone(host);
    await expect(bob.page.locator('#k2')).toBeHidden();
    await expect(bob.page).toHaveURL(/\/party\/(#.*)?$/);
    expect((await view(bob)).state).toBe('lobby');
    await bob.page.reload();
    await expect(bob.page.locator('html')).toHaveAttribute('data-ready', 'true');
    await expect(bob.page.locator('#k2')).toBeHidden();
  });
});
