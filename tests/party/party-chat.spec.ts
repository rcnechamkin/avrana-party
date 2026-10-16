import { test, expect, type Page } from '@playwright/test';
import { place, smallTargets } from '../lib/frame';
import { phone, post, type Phone } from '../lib/phones';

/**
 * The Party's chat (AVR-54, docs/design/MESSAGING.md) on several phones against the dev server's
 * real Party Core: sender identity from the Party, one ordered room, unread on the Party control,
 * reload and reconnect without doubles, markup as text, refusals, keyboard and a small phone.
 * Tier 2: real Chromium at phone size. Not a phone, not Safari, not the Pi's Wi-Fi.
 */

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

async function openChat(p: Phone) {
  await p.page.locator('#hud').click();
  await expect(p.page.locator('#social')).toBeVisible();
  await p.page.locator('#tab-chat').click();
  await expect(p.page.locator('#tab-chat')).toHaveAttribute('aria-pressed', 'true');
  await expect(p.page.locator('#chat-send')).toBeEnabled();
}

async function say(p: Phone, text: string) {
  await p.page.locator('#chat-text').fill(text);
  await p.page.locator('#chat-text').press('Enter');
  await expect(p.page.locator('#chat-text')).toHaveValue('');
}

const lines = (page: Page) => page.locator('#chat-messages .avrana-chat-line');
const partyId = async (p: Phone) => (await (await p.page.request.get('/party/api/state')).json()).party as string;

test.describe('the Party chat on three phones', () => {
  let ada: Phone, bob: Phone, cleo: Phone;

  test.beforeEach(async ({ browser }) => {
    ada = await phone(browser, 'Ada');
    bob = await phone(browser, 'Bob');
    cleo = await phone(browser, 'Cleo');
  });

  test.afterEach(async () => {
    for (const p of [ada, bob, cleo]) await p.context.close();
  });

  test('one room, in order, each line under its sender’s Party name', async () => {
    await openChat(ada);
    await openChat(bob);
    await say(ada, 'Hello everyone');
    await expect(lines(bob.page)).toHaveCount(1);
    await say(bob, 'Hi Ada');
    await say(ada, 'Ready to play?');
    for (const p of [ada, bob]) {
      await expect(lines(p.page)).toHaveCount(3);
      await expect(lines(p.page).locator('p')).toHaveText(['Hello everyone', 'Hi Ada', 'Ready to play?']);
    }
    await expect(lines(ada.page).nth(0).locator('strong')).toHaveText('Ada (you)');
    await expect(lines(bob.page).nth(0).locator('strong')).toHaveText('Ada');
    await expect(lines(bob.page).nth(1).locator('strong')).toHaveText('Bob (you)');
    // the Party's own lines are drawn apart from people's words
    await expect(ada.page.locator('#chat-messages .avrana-chat-system').first()).toContainText('joined the Party');
  });

  test('no phone can write as another: a forged sender is ignored', async () => {
    const ana = await (await ada.page.request.get('/party/api/state')).json();
    const res = await post(bob, 'messages', { party: ana.party, text: 'I am Ada', client_id: 'forge-1',
      from: ana.me.id, name: 'Ada', kind: 'system', event: 'host' });
    expect(res.status()).toBe(200);
    await openChat(cleo);
    const forged = lines(cleo.page).filter({ hasText: 'I am Ada' });
    await expect(forged.locator('strong')).toHaveText('Bob');
    await expect(cleo.page.locator('#chat-messages .avrana-chat-system').filter({ hasText: 'I am Ada' })).toHaveCount(0);
  });

  test('unread: counted on the Party control while the drawer is closed, cleared once read', async () => {
    await place(bob.page, 'home');
    await openChat(ada);
    await say(ada, 'one');
    await say(ada, 'two');
    const hud = bob.page.locator('#hud');
    await expect(bob.page.locator('#hud-unread')).toHaveText('2');
    await expect(hud).toHaveAccessibleName('Your Party: 3 people here, 2 new messages. Open people and chat');
    await openChat(bob);
    await expect(bob.page.locator('#hud-unread')).toHaveText('');
    await expect(bob.page.locator('#tab-chat')).toHaveAccessibleName('Chat');
    await bob.page.keyboard.press('Escape');
    await expect(hud).toHaveAccessibleName('Your Party: 3 people here. Open people and chat');
    // a phone's own words are never unread to it
    await expect(ada.page.locator('#hud-unread')).toHaveText('');
  });

  test('a reload keeps the room, without doubles, and what was read stays read', async () => {
    await openChat(ada);
    await say(ada, 'before the reload');
    await openChat(bob);
    await expect(lines(bob.page)).toHaveCount(1);
    await bob.page.reload();
    await expect(bob.page.locator('html')).toHaveAttribute('data-ready', 'true');
    await expect(bob.page.locator('#hud-unread')).toHaveText('');           // read before the reload
    await openChat(bob);
    await expect(lines(bob.page)).toHaveCount(1);
    await expect(lines(bob.page).locator('p')).toHaveText(['before the reload']);
  });

  test('a phone that lost the Party’s Wi-Fi catches up on its return, once each', async () => {
    await openChat(bob);
    const block = (route: { abort: () => Promise<void> }) => route.abort();
    await bob.context.route('**/party/api/messages**', block);
    await openChat(ada);
    await say(ada, 'while you were away');
    await bob.page.waitForTimeout(500);
    await bob.context.unroute('**/party/api/messages**', block);
    await bob.page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));   // the phone wakes
    await expect(lines(bob.page).filter({ hasText: 'while you were away' })).toHaveCount(1, { timeout: 15_000 });
    await say(ada, 'and after');
    await expect(lines(bob.page).locator('p')).toHaveText(['while you were away', 'and after']);
  });

  test('a message is text, never markup', async () => {
    await openChat(ada);
    await say(ada, '<img src=x onerror="document.title=1"><b>bold</b>');
    await openChat(bob);
    await expect(lines(bob.page).locator('p')).toHaveText('<img src=x onerror="document.title=1"><b>bold</b>');
    await expect(bob.page.locator('#chat-messages img:not(.avrana-avatar), #chat-messages b')).toHaveCount(0);
  });

  test('too fast is said and the words stay to send again', async () => {
    await openChat(ada);
    for (let i = 0; i < 6; i++) await say(ada, `quick ${i}`);
    await ada.page.locator('#chat-text').fill('one more');
    await ada.page.locator('#chat-text').press('Enter');
    await expect(ada.page.locator('#chat-feedback')).toHaveText('Slow down a little, then send again.');
    await expect(ada.page.locator('#chat-text')).toHaveValue('one more');
  });

  test('keyboard only: the drawer, the Chat side, a message, and back', async () => {
    await place(ada.page, 'home');
    await ada.page.locator('#hud').focus();
    await ada.page.keyboard.press('Enter');
    await expect(ada.page.locator('#social')).toBeVisible();
    await ada.page.locator('#tab-chat').focus();
    await ada.page.keyboard.press('Enter');
    await ada.page.locator('#chat-text').focus();
    await ada.page.keyboard.type('typed with keys');
    await ada.page.keyboard.press('Enter');
    await expect(lines(ada.page).locator('p')).toHaveText(['typed with keys']);
    await ada.page.keyboard.press('Escape');
    await expect(ada.page.locator('#social')).toBeHidden();
    await expect(ada.page.locator('#hud')).toBeFocused();
  });

  test('a message for a Party that has ended is refused and stored nowhere', async () => {
    const res = await post(ada, 'messages', { party: 'party-' + '0'.repeat(32), text: 'last night', client_id: 'old-1' });
    expect(res.status()).toBe(400);
    expect((await res.json()).error).toBe('bad_party');
    const read = await ada.page.request.get(`/party/api/messages?party=${await partyId(ada)}&after=0`);
    const body = await read.json();
    expect(body.messages.filter((m: { kind: string }) => m.kind === 'member')).toEqual([]);
  });
});

test('a small phone: the composer is on screen with the keyboard space, nothing sideways', async ({ browser }) => {
  const small = await phone(browser, 'Dee', { viewport: { width: 320, height: 568 }, isMobile: true, hasTouch: true });
  try {
    await openChat(small);
    for (let i = 0; i < 6; i++) await say(small, `message number ${i} with a few more words in it so that it wraps`);   // the most 4 s allow
    const box = await small.page.locator('#chat-text').boundingBox();
    expect(box).not.toBeNull();
    expect(box!.y + box!.height).toBeLessThanOrEqual(568);
    expect(await small.page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(await smallTargets(small.page, '#social button, #social input')).toEqual([]);
    await expect(lines(small.page).last()).toBeInViewport();
  } finally {
    await small.context.close();
  }
});

test('one phone alone: the room says so, and is not a dead end', async ({ browser }) => {
  const solo = await phone(browser, 'Eve');
  try {
    await openChat(solo);
    await expect(solo.page.locator('#chat-messages .avrana-chat-empty, #chat-messages .avrana-chat-system').first()).toBeVisible();
    await say(solo, 'anyone?');
    await expect(lines(solo.page)).toHaveCount(1);
  } finally {
    await solo.context.close();
  }
});
