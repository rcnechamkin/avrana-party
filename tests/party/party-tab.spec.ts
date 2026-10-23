import { test, expect } from '@playwright/test';
import { place } from '../lib/frame';
import { phone, view, type Phone } from '../lib/phones';

/**
 * The Party tab (Concept K, AVR-710) at a real Party Core behind the dev server: everyone here in
 * one group, what is true of each in words, the HOST tag, and the Host's hand-over (Party Core's
 * transfer_host, POST /party/api/host). Tier 2: real Chromium, simulated appliance. Not a phone.
 */

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

test.describe('the Party tab with three phones', () => {
  let host: Phone, bob: Phone, cleo: Phone;

  test.beforeEach(async ({ browser }) => {
    host = await phone(browser, 'Ada');
    bob = await phone(browser, 'Bob');
    cleo = await phone(browser, 'Cleo');
    for (const p of [host, bob, cleo]) await place(p.page, 'party');
  });
  test.afterEach(async () => { for (const p of [host, bob, cleo]) await p.context.close(); });

  const row = (p: Phone, name: string) => p.page.locator('#party-members li', { hasText: name });

  test('one row each: the name, "Here" in words, the HOST tag on the Host’s row only', async () => {
    await expect(host.page.locator('#party-h')).toHaveText(/In this Party\s*·\s*3 people/);
    await expect(host.page.locator('#party-members li')).toHaveCount(3);
    await expect(row(host, 'Ada').locator('.who')).toHaveText('Ada (you)');
    for (const name of ['Ada', 'Bob', 'Cleo']) await expect(row(host, name).locator('.sub')).toHaveText('Here');
    await expect(row(host, 'Ada').locator('.avrana-tag.host')).toHaveText(/host/i);
    await expect(host.page.locator('#party-members .avrana-tag.host')).toHaveCount(1);
    await expect(bob.page.locator('#party-members .avrana-tag.host')).toHaveCount(1);
  });

  test('only the Host can hand hosting over, to someone who is here; then the new Host can', async () => {
    await expect(host.page.locator('#party-members .hand')).toHaveCount(2);         // Bob and Cleo, never Ada
    await expect(row(host, 'Ada').locator('.hand')).toHaveCount(0);
    for (const p of [bob, cleo]) await expect(p.page.locator('#party-members .hand'), p.name).toHaveCount(0);
    const make = row(host, 'Bob').locator('.hand');
    await expect(make).toHaveAccessibleName('Make Bob the host');
    await make.click();
    await expect(host.page.locator('#party-h')).toBeFocused();                      // the button is gone; focus is not lost
    await expect.poll(async () => (await view(bob)).me.host).toBe(true);
    for (const p of [host, bob, cleo]) await expect(row(p, 'Bob').locator('.avrana-tag.host'), p.name).toBeVisible();
    await expect(host.page.locator('#party-members .hand')).toHaveCount(0);
    await expect(bob.page.locator('#party-members .hand')).toHaveCount(2);           // Ada and Cleo now
  });
});
