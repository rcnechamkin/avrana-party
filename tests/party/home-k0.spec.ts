import { test, expect } from '@playwright/test';
import { place, startForEveryone } from '../lib/frame';
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
    await expect(row).toHaveAccessibleName('3 here · You host. Open people');   // the words it shows, the Host tag said, what it opens
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

/**
 * K3 (Concept K, AVR-709): Home after a round. Only what each phone saw (the round it was taken to)
 * and where Party Core says the Party is: "Just played", the Party's size, "Round over" and who
 * chooses next. No score, no winner, no round length.
 */
test.describe('Home K3 after a round', () => {
  let host: Phone, bob: Phone, cleo: Phone;

  test.beforeEach(async ({ browser }) => {
    host = await phone(browser, 'Ada');
    bob = await phone(browser, 'Bob');
    cleo = await phone(browser, 'Cleo');
  });
  test.afterEach(async () => { for (const p of [host, bob, cleo]) await p.context.close(); });

  async function roundThenHome() {
    await startForEveryone(host.page, 'expo');
    for (const p of [host, bob, cleo]) await expect(p.page, p.name).toHaveURL(/\/games\/expo\//);
    await host.page.locator('#avrana-party-end').click();
    await host.page.locator('#avrana-party-end').click();
    for (const p of [host, bob, cleo]) {
      await expect(p.page, p.name).toHaveURL(/\/party\/(#.*)?$/);
      await expect(p.page.locator('html'), p.name).toHaveAttribute('data-ready', 'true');
      await place(p.page, 'home');
    }
  }

  test('Just played: the Host has Play again and Choose another game; a member has neither, and is told who chooses', async () => {
    await roundThenHome();
    for (const p of [host, bob]) {
      const stage = p.page.locator('#home-lead .avrana-stage');
      await expect(stage, p.name).toHaveAttribute('data-just', '');
      await expect(stage.locator('.avrana-eyebrow'), p.name).toHaveText('Just played');
      await expect(stage.locator('.avrana-eyebrow'), p.name).not.toHaveClass(/selected/);
      await expect(stage.locator('h2'), p.name).toHaveText('EXPO');
      await expect(stage.locator('.avrana-meta').first(), p.name).toHaveText('3 in the Party');
      await expect(p.page.locator('#home-lead .round-over'), p.name).toContainText('Round over');
      // nothing about how it went
      await expect(p.page.locator('#view-home'), p.name).not.toContainText(/score|winner|won|minutes|points/i);
    }
    await expect(host.page.locator('#home-actions button')).toHaveText(['Play again', 'Choose another game']);
    await expect(host.page.locator('#home-lead .round-over .sub')).toHaveText('Play again, or choose another game.');
    await expect(bob.page.locator('#home-actions button')).toHaveCount(0);
    await expect(bob.page.locator('#home-lead .round-over .sub')).toHaveText('Ada chooses what’s next.');
    // EXPO seats two: Cleo watched, and a watched round is not "played" on her phone (the owner, 2026-10-06)
    expect((await view(cleo)).me.id).toBeTruthy();
    await expect(cleo.page.locator('#home-lead [data-game]')).toBeVisible();
    await expect(cleo.page.locator('#home-lead [data-just]')).toHaveCount(0);
    await expect(cleo.page.locator('#home-lead .round-over')).toHaveCount(0);
    // the game on the stage is not on the rail as well
    await expect(host.page.locator('#home-great [data-game="expo"]')).toHaveCount(0);

    // Choose another game is this phone's own: the Host's Home is Featured again, and focus stays on its actions
    await host.page.locator('#just-other').click();
    await expect(host.page.locator('#home-lead .avrana-stage .avrana-eyebrow')).toHaveText('Featured');
    await expect(host.page.locator('#home-lead .round-over')).toHaveCount(0);
    await expect(host.page.locator('#home-actions button').first()).toBeFocused();
    await expect(bob.page.locator('#home-lead .avrana-stage .avrana-eyebrow')).toHaveText('Just played');
    await host.page.reload();
    await expect(host.page.locator('html')).toHaveAttribute('data-ready', 'true');
    await expect(host.page.locator('#home-lead .avrana-stage .avrana-eyebrow')).toHaveText('Featured');   // and it stays chosen
  });

  test('Play again is the Host’s start of the same game: everyone moves to it together', async () => {
    await roundThenHome();
    await host.page.locator('#home-actions button', { hasText: 'Play again' }).click();
    for (const p of [host, bob, cleo]) await expect(p.page, p.name).toHaveURL(/\/games\/expo\//);
  });
});
