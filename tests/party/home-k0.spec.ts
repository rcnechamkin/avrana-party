import { test, expect } from '@playwright/test';
import { place } from '../lib/frame';
import { phone, view, type Phone } from '../lib/phones';

/**
 * Home's K0 (Concept K, AVR-708) at a real Party Core behind the dev server: who is here in a row,
 * the Host's Select for Party (today's Host start: no select-then-launch, AVR-701 is a proposal),
 * and nothing on Home that a member who is not the Host can use to move the Party.
 * Tier 2: real Chromium, simulated appliance, stub game pages. Not a phone.
 */

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

test.describe('Home K0 with three phones', () => {
  let host: Phone, bob: Phone, cleo: Phone;

  test.beforeEach(async ({ browser }) => {
    host = await phone(browser, 'Ada');
    bob = await phone(browser, 'Bob');
    cleo = await phone(browser, 'Cleo');
  });

  test.afterEach(async () => {
    for (const p of [host, bob, cleo]) await p.context.close();
  });

  test('the Host has Select for Party; a member has Preview only, and no Select anywhere on Home', async () => {
    for (const p of [host, bob]) await place(p.page, 'home');
    await expect(host.page.locator('#home-actions button')).toHaveText(['Select for Party', 'Preview']);
    await expect(bob.page.locator('#home-actions button')).toHaveText(['Preview']);
    // the facts, opened by each: the same game, the Host's Select there too, a member's not
    for (const p of [host, bob]) await p.page.locator('#home-great [data-game]').first().click();
    await expect(host.page.locator('#home-preview').getByRole('button', { name: 'Select for Party' })).toHaveCount(1);
    await expect(bob.page.locator('#home-preview').getByRole('button', { name: 'Select for Party' })).toHaveCount(0);
    await expect(bob.page.locator('#view-home').getByRole('button', { name: /select|start/i })).toHaveCount(0);
    // one primary action live at a time: the stage's Select is out of reach while the facts are open
    expect(await host.page.locator('#home-actions').evaluate((el) => (el as HTMLElement).inert)).toBe(true);
    // a look is this phone's own: nobody else's Home changed
    await expect(cleo.page.locator('#home-preview')).toBeHidden();
  });

  test('the presence row: faces, how many, the Host tag for the Host, and it opens the Party tab', async () => {
    await place(host.page, 'home');
    const row = host.page.locator('#home-presence');
    await expect(row).toHaveAccessibleName('Your Party: 3 people here. Open people');
    await expect(host.page.locator('#home-faces > *')).toHaveCount(3);
    await expect(host.page.locator('#home-host')).toHaveText(/host/i);
    await row.click();
    await expect(host.page.locator('html')).toHaveAttribute('data-place', 'party');
    await expect(host.page.locator('#party-members')).toContainText('Ada (you)');
    await expect(host.page.locator('#party-host')).toContainText('You’re the host');
  });

  test('Select for Party is the Host’s start: everyone moves together, and Home intercepts none of it', async () => {
    for (const p of [host, bob, cleo]) await place(p.page, 'home');
    const game = await host.page.locator('#home-lead [data-game]').getAttribute('data-game');
    await host.page.locator('#home-actions').getByRole('button', { name: 'Select for Party' }).click();
    // a game with a briefing sends everyone there; one without sends everyone straight in
    await expect.poll(async () => (await view(host)).location.at).not.toBe('home');
    const at = (await view(host)).location.at;
    for (const p of [host, bob, cleo]) {
      if (at === 'setup') await expect(p.page.locator('#scene'), p.name).toBeVisible();
      else await expect(p.page, p.name).not.toHaveURL(/\/party\/(#.*)?$/);
    }
    expect(game).toBeTruthy();
  });
});
