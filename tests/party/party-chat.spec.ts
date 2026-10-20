import { test, expect, type Page } from '@playwright/test';
import { place, smallTargets } from '../lib/frame';
import { keyboard, visibleHeight, visibleTop, withKeyboardModel } from '../lib/keyboard';
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

/**
 * UX-07 / AVR-579: with the software keyboard up, the composer must stay above it, the drawer must
 * stay open, and what was typed and where the history was scrolled to must survive. The keyboard is
 * SIMULATED (tests/lib/keyboard.ts: visualViewport shrinks, the layout viewport does not, as on
 * iPhone Safari and Android Chrome). Real iOS/Android keyboards are an owner check on a phone.
 */
for (const size of [
  { name: 'small portrait', viewport: { width: 320, height: 568 }, keys: 260 },
  { name: 'portrait', viewport: { width: 390, height: 844 }, keys: 336 },
  { name: 'landscape', viewport: { width: 740, height: 360 }, keys: 170 },
]) {
  test(`keyboard (${size.name}): composer stays above the keys; drawer, draft, focus and scroll survive`, async ({ browser }) => {
    const dee = await phone(browser, 'Dee', { viewport: size.viewport, isMobile: true, hasTouch: true });
    const eve = await phone(browser, 'Eve');
    try {
      for (let i = 0; i < 5; i++) {   // history from another phone, so Dee's own rate limit is untouched
        expect((await post(eve, 'messages', { party: await partyId(eve), text: `message number ${i} with a few more words in it so that it wraps`, client_id: `kb-${size.name.replace(/ /g, "-")}-${i}` })).status()).toBe(200);
      }
      await withKeyboardModel(dee.context);
      await dee.page.reload();
      await expect(dee.page.locator('html')).toHaveAttribute('data-ready', 'true');
      await openChat(dee);
      await expect(lines(dee.page)).toHaveCount(5, { timeout: 15_000 });
      const text = dee.page.locator('#chat-text');
      await text.fill('half a thought');
      await text.focus();
      await dee.page.locator('#chat').evaluate((el) => { el.scrollTop = 40; });
      const scrolled = await dee.page.locator('#chat').evaluate((el) => el.scrollTop);

      for (const cycle of [size.keys, 0, size.keys]) {
        await keyboard(dee.page, cycle);
        const visible = await visibleHeight(dee.page);
        await expect(dee.page.locator('#social')).toBeVisible();
        await expect(text).toBeFocused();
        await expect(text).toHaveValue('half a thought');
        const input = (await text.boundingBox())!, send = (await dee.page.locator('#chat-send').boundingBox())!;
        for (const b of [input, send]) {
          expect(b.y, 'composer top is on screen').toBeGreaterThanOrEqual(0);
          expect(b.y + b.height, `composer bottom ${b.y + b.height} is above the keys (${visible})`).toBeLessThanOrEqual(visible + 0.5);
        }
        const drawer = (await dee.page.locator('#social').boundingBox())!;
        expect(drawer.y + drawer.height).toBeLessThanOrEqual(visible + 0.5);
        expect(await dee.page.locator('#chat').evaluate((el) => el.scrollTop)).toBe(scrolled);
      }
      await text.press('Enter');   // and it can still be sent
      await expect(text).toHaveValue('');
      await expect(lines(dee.page).last().locator('p')).toHaveText('half a thought');
    } finally {
      await dee.context.close(); await eve.context.close();
    }
  });
}

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

/**
 * AVR-583: iPhone Safari pans the visual viewport down (visualViewport.offsetTop > 0) to keep the
 * focused field in view, while position:fixed boxes stay anchored to the layout viewport. The whole
 * drawer (its header and tabs too, not only the composer) must stay inside the visible region, and
 * turning the phone with the keyboard up must keep the drawer open, the draft and the focus.
 * SIMULATED (tests/lib/keyboard.ts); real Safari panning and rotation are an owner check on a phone.
 */
test('keyboard panned and the phone turned: the whole drawer stays in the visible region; draft, focus and drawer survive', async ({ browser }) => {
  const dee = await phone(browser, 'Dee', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const eve = await phone(browser, 'Eve');
  try {
    for (let i = 0; i < 5; i++) {
      expect((await post(eve, 'messages', { party: await partyId(eve), text: `message number ${i} with a few more words in it so that it wraps`, client_id: `pan-${i}` })).status()).toBe(200);
    }
    await withKeyboardModel(dee.context);
    await dee.page.reload();
    await expect(dee.page.locator('html')).toHaveAttribute('data-ready', 'true');
    await openChat(dee);
    await expect(lines(dee.page)).toHaveCount(5, { timeout: 15_000 });
    const text = dee.page.locator('#chat-text');
    await text.fill('half a thought');
    await text.focus();

    const inRegion = async (label: string) => {
      const top = await visibleTop(dee.page), height = await visibleHeight(dee.page);
      for (const sel of ['#social', '#chat-text', '#chat-send', '#tab-chat']) {
        const b = (await dee.page.locator(sel).boundingBox())!;
        expect(b.y, `${label}: ${sel} top ${b.y} is inside the visible region from ${top}`).toBeGreaterThanOrEqual(top - 0.5);
        expect(b.y + b.height, `${label}: ${sel} bottom ${b.y + b.height} is above the keys (${top + height})`).toBeLessThanOrEqual(top + height + 0.5);
      }
      await expect(dee.page.locator('#social')).toBeVisible();
      await expect(text).toBeFocused();
      await expect(text).toHaveValue('half a thought');
    };

    await keyboard(dee.page, 336, 120);
    await inRegion('portrait, keyboard up and panned');
    await dee.page.setViewportSize({ width: 844, height: 390 });   // rotate with the keyboard up
    await keyboard(dee.page, 170, 60);
    await inRegion('landscape, keyboard up and panned');
    await dee.page.setViewportSize({ width: 390, height: 844 });   // and back, keyboard closed
    await keyboard(dee.page, 0, 0);
    await inRegion('portrait, keyboard closed');
  } finally {
    await dee.context.close(); await eve.context.close();
  }
});

test('keyboard on a small phone with enlarged text and reduced motion: composer and Send stay reachable, nothing sideways', async ({ browser }) => {
  const dee = await phone(browser, 'Dee', { viewport: { width: 320, height: 568 }, isMobile: true, hasTouch: true, reducedMotion: 'reduce' });
  try {
    await withKeyboardModel(dee.context);
    await dee.page.reload();
    await expect(dee.page.locator('html')).toHaveAttribute('data-ready', 'true');
    await dee.page.evaluate(() => { document.documentElement.style.fontSize = '150%'; });   // like a phone set to larger text
    await openChat(dee);
    const text = dee.page.locator('#chat-text');
    await text.fill('half a thought');
    await text.focus();
    await keyboard(dee.page, 260, 80);
    const top = await visibleTop(dee.page), height = await visibleHeight(dee.page);
    for (const sel of ['#chat-text', '#chat-send']) {
      await expect(dee.page.locator(sel)).toBeVisible();
      const b = (await dee.page.locator(sel).boundingBox())!;
      expect(b.y, `${sel} top`).toBeGreaterThanOrEqual(top - 0.5);
      expect(b.y + b.height, `${sel} bottom ${b.y + b.height} above the keys (${top + height})`).toBeLessThanOrEqual(top + height + 0.5);
      expect(b.x + b.width, `${sel} is not pushed off the side`).toBeLessThanOrEqual(320 + 0.5);
    }
    expect(await dee.page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expect(text).toBeFocused();
    await expect(text).toHaveValue('half a thought');
  } finally {
    await dee.context.close();
  }
});
