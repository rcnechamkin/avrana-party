import { test, expect, type Page } from '@playwright/test';
import { place, startForEveryone } from '../lib/frame';
import { goQuiet, later, phone, post, view, type Phone } from '../lib/phones';

/**
 * Leave Party and Reconnect (AVR-580) against a real Party Core behind the dev server: refresh,
 * several tabs, Host departure, reconnect and network loss. Each phone is its own browser context
 * (cookie jar + localStorage); two pages in one context are two tabs of one phone.
 * Tier 2: real Chromium, simulated appliance, stub game pages. Not a phone.
 */

test.beforeEach(async ({ request }) => {
  const res = await request.post('/__test__/party/reset');
  expect(res.status()).toBe(204);
});

/** The Party page's Leave, through its confirmation. Returns the confirmation's words. */
async function leaveParty(page: Page, confirm = true) {
  await place(page, 'party');
  await page.locator('#party-leave').click();
  const dialog = page.locator('#leave');
  await expect(dialog).toBeVisible();
  const words = (await dialog.locator('.body').innerText()).trim();
  if (confirm) await dialog.getByRole('button', { name: 'Leave Party' }).click();
  return words;
}

const reconnectShown = (page: Page) => expect(page.locator('#reconnect')).toBeVisible();

test.describe('Leave Party', () => {
  let host: Phone, bob: Phone, cleo: Phone;

  test.beforeEach(async ({ browser }) => {
    host = await phone(browser, 'Ada');
    bob = await phone(browser, 'Bob');
    cleo = await phone(browser, 'Cleo');
  });

  test.afterEach(async () => {
    for (const p of [host, bob, cleo]) await p.context.close();
  });

  test('a member leaves after confirming; Reconnect? stays through refresh and a second tab; Reconnect opts back in', async () => {
    const words = await leaveParty(bob.page, false);
    expect(words).toContain('Everyone else stays where they are');
    expect(words).not.toContain('Host');
    await bob.page.locator('#leave').getByRole('button', { name: 'Stay' }).click();
    expect((await view(bob)).me).not.toBeNull();                      // cancelling changes nothing

    await leaveParty(bob.page);
    await reconnectShown(bob.page);
    await expect(bob.page.locator('#reconnect')).toContainText('You left the party.');
    expect((await view(bob)).departed).toBe(true);
    await expect(host.page.locator('#party-count')).toHaveText('2 people');
    await expect(host.page.locator('#party-members')).not.toContainText('Bob');
    expect(await bob.page.evaluate(() => localStorage.getItem('wc-name'))).toBe('Bob');   // settings stay

    // a refresh, and then a second tab of the same phone: neither joins on its own
    await bob.page.reload();
    await reconnectShown(bob.page);
    const tab = await bob.context.newPage();
    await tab.goto('/party/');
    await expect(tab.locator('html')).toHaveAttribute('data-ready', 'true');
    await reconnectShown(tab);
    await expect(tab.locator('#party-members')).toBeHidden();
    await tab.waitForTimeout(1500);                                   // longer than any retry the page makes
    expect((await view(bob)).me).toBeNull();
    await expect(host.page.locator('#party-count')).toHaveText('2 people');

    // the other tab hears the Reconnect
    await bob.page.locator('#reconnect-btn').click();
    await expect(bob.page.locator('#party-members')).toContainText('Bob (you)');
    await expect(tab.locator('#party-members')).toContainText('Bob (you)');
    await expect(host.page.locator('#party-count')).toHaveText('3 people');
    expect((await view(bob)).me.host).toBe(false);
    await tab.close();
  });

  test('a second tab left open hears the Leave and does not rejoin', async () => {
    const tab = await bob.context.newPage();
    await tab.goto('/party/');
    await expect(tab.locator('#party-members')).toContainText('Bob (you)');
    await leaveParty(bob.page);
    await reconnectShown(tab);
    await tab.waitForTimeout(1500);
    expect((await view(bob)).departed).toBe(true);
    expect((await view(host)).members.map((m: { name: string }) => m.name)).toEqual(['Ada', 'Cleo']);
  });

  test('Leave in the middle of a round: a non-host leaves, nobody else moves, and Reconnect follows the party', async () => {
    await startForEveryone(host.page, 'expo');
    await expect(cleo.page).toHaveURL(/\/games\/expo\//);
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    const before = await view(cleo);
    // Bob leaves from another tab at the party (his game page goes to Party Home on its own)
    const origin = new URL(bob.page.url()).origin;
    const left = await bob.context.request.post('/party/api/leave', { data: {}, headers: { 'Content-Type': 'application/json', Origin: origin } });
    expect(left.status()).toBe(200);
    await expect(bob.page).toHaveURL(/\/party\/$/);
    await reconnectShown(bob.page);
    const after = await view(cleo);
    for (const key of ['nav', 'location', 'host', 'state']) expect(after[key]).toEqual(before[key]);
    await expect(host.page).toHaveURL(/\/games\/expo\//);
    await expect(cleo.page).toHaveURL(/\/games\/expo\//);
    // he comes back: Core says where the party is, and his phone follows
    await bob.page.locator('#reconnect-btn').click();
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
  });

  test('the Host leaves: the confirmation names the successor, the next phone hosts, the old Host keeps no authority', async () => {
    const words = await leaveParty(host.page, false);
    expect(words).toContain('You are the Host. Bob becomes the Host right away.');
    await host.page.locator('#leave').getByRole('button', { name: 'Leave Party' }).click();
    await reconnectShown(host.page);
    await expect(bob.page.locator('#party-host')).toContainText('You’re the host');
    await expect(cleo.page.locator('#party-host')).toContainText('Bob is the host');
    // the former Host cannot act, even by name (Core's word, not the page's)
    const stale = await post(host, 'session/launch', { game: 'expo', if_version: (await view(bob)).version });
    expect(stale.status()).toBe(403);
    // coming back, she is a member again and not the Host
    await host.page.locator('#reconnect-btn').click();
    await expect(host.page.locator('#party-host')).toContainText('Bob is the host');
    const launch = await post(host, 'session/launch', { game: 'expo', if_version: (await view(host)).version });
    expect(launch.status()).toBe(403);
    await startForEveryone(bob.page, 'expo');
    await expect(cleo.page).toHaveURL(/\/games\/expo\//);
  });

  test('the Host leaves during a round: the round goes on for everyone else', async () => {
    await startForEveryone(host.page, 'expo');
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    const origin = new URL(host.page.url()).origin;
    const left = await host.context.request.post('/party/api/leave', { data: {}, headers: { 'Content-Type': 'application/json', Origin: origin } });
    expect(left.status()).toBe(200);
    const v = await view(bob);
    expect([v.state, v.location.at, v.me.host]).toEqual(['active', 'game', true]);
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    await expect(cleo.page).toHaveURL(/\/games\/expo\//);
    await expect(host.page).toHaveURL(/\/party\/$/);                 // her game page took her to Reconnect?
    await reconnectShown(host.page);
  });

  test('network loss is not Leave: a quiet phone is Away, comes back by itself, and never sees Reconnect?', async ({ request }) => {
    const wake = await goQuiet(bob);
    await later(request, 60);
    await expect(host.page.locator('#party-members li').filter({ hasText: 'Bob' })).toContainText('Away');
    expect((await view(host)).members.map((m: { name: string }) => m.name)).toContain('Bob');
    await wake();
    await bob.page.goto('/party/');
    await expect(bob.page.locator('#party-members')).toContainText('Bob (you)');
    await expect(bob.page.locator('#reconnect')).toBeHidden();
  });

  test('Leave with no network is reported unconfirmed, claims nothing, and works when the network is back', async () => {
    await place(bob.page, 'party');
    await bob.page.locator('#party-leave').click();
    await bob.context.route('**/party/api/leave', (route) => route.abort());
    await bob.page.locator('#leave').getByRole('button', { name: 'Leave Party' }).click();
    await expect(bob.page.locator('#leave-note')).toContainText('Couldn’t confirm that you left');
    await expect(bob.page.locator('#reconnect')).toBeHidden();       // not claimed
    expect((await view(host)).members.map((m: { name: string }) => m.name)).toContain('Bob');
    await bob.context.unroute('**/party/api/leave');
    await expect(bob.page.locator('#leave-confirm')).toBeEnabled();  // a retry is offered
    await bob.page.locator('#leave').getByRole('button', { name: 'Leave Party' }).click();
    await reconnectShown(bob.page);
    expect((await view(host)).members.map((m: { name: string }) => m.name)).not.toContain('Bob');
  });

  test('a restarted Pi forgets the party but not the choice: the phone still asks, and does not join', async ({ request }) => {
    await leaveParty(bob.page);
    await reconnectShown(bob.page);
    expect((await request.post('/__test__/party/reset')).status()).toBe(204);
    await bob.page.reload();
    await reconnectShown(bob.page);
    await bob.page.waitForTimeout(1500);
    expect((await view(bob)).me).toBeNull();
    await bob.page.locator('#reconnect-btn').click();
    await expect(bob.page.locator('#party-members')).toContainText('Bob (you)');
  });

  test('the lone Host who leaves is not asked to end anything: the consequence is said, nothing is ended', async () => {
    await bob.page.close();
    await cleo.page.close();
    await later(await bob.context.request, 60);                         // the others are away: nobody can take over
    await host.page.reload();
    const words = await leaveParty(host.page, false);
    expect(words).toContain('nobody else is here to take over');
    expect(words).not.toMatch(/will end|is ended|will stop/);
    await host.page.locator('#leave').getByRole('button', { name: 'Leave Party' }).click();
    await reconnectShown(host.page);
  });
});
