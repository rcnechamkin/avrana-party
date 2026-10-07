import { test, expect, type Page } from '@playwright/test';
import { openGame, place, sideways, smallTargets, startForEveryone } from '../lib/frame';
import { cutOff, endForEveryone, goQuiet, later, phone, post, version, view, type Phone } from '../lib/phones';

/**
 * Several phones at one party (ADR 0011 console model) against a real Party Core behind the dev
 * server. Each phone is its own browser context: its own cookie jar (device identity) and its own
 * localStorage (profile). Covers: host and followers, one place for everyone, game switching,
 * reconnect without losing the seat, stale/unauthorized actions, host departure and succession.
 * Tier 2: real Chromium, simulated appliance, stub game pages. Not a phone.
 */

/** A game's onboarding as BLUFF ships it (avrana.onboarding/v0), for the stub game the dev server
 * serves: enough to exercise How to play and a first-timer's acknowledgement. The real file is
 * read in the provider suite. */
const ONBOARDING = { schema: 'avrana.onboarding/v0', premise: 'A test premise: claim anything.',
  facts: { cards: 5 }, ack: { key: 'test-bluff-rules', version: '2' },
  rules: [{ title: 'Your turn', points: ['Play a card and claim what it is.', 'You start with {cards} cards.'] },
    { title: 'Calling it', points: ['Anyone may call a claim.'] }] };
async function withOnboarding(...phones: Phone[]) {
  for (const p of phones) await p.context.route('**/games/bluff/onboarding.json', (route) => route.fulfill({ json: ONBOARDING }));
}

/** How far the briefing is scrolled, and a way to scroll it. On a tall phone its middle scrolls
 * above a pinned dock; on a short one (or with large text) the whole briefing does. */
const briefScroll = (page: Page, to?: number) => page.evaluate((y) => {
  const all = document.getElementById('scene')!, mid = document.getElementById('scene-scroll')!;
  const el = all.scrollHeight > all.clientHeight + 1 ? all : mid;
  if (typeof y === 'number') el.scrollTop = y;
  return Math.round(el.scrollTop);
}, to);

/** Three ways to close what is open over the page: Escape, its own Close, a tap outside it. */
const CLOSERS = (page: Page, close: string, outside: [number, number]): Array<[string, () => Promise<unknown>]> => [
  ['Escape', () => page.keyboard.press('Escape')],
  ['Close', () => page.locator(close).click()],
  ['a tap outside', () => page.mouse.click(...outside)],
];


test.beforeEach(async ({ request }) => {
  const res = await request.post('/__test__/party/reset');
  expect(res.status()).toBe(204);
});

test.describe('three phones at one party', () => {
  let host: Phone, bob: Phone, cleo: Phone;

  test.beforeEach(async ({ browser }) => {
    host = await phone(browser, 'Ada');
    bob = await phone(browser, 'Bob');
    cleo = await phone(browser, 'Cleo');
  });

  test.afterEach(async () => {
    for (const p of [host, bob, cleo]) await p.context.close();
  });

  test('the first phone hosts; followers see the host and cannot start a game', async () => {
    await expect(host.page.locator('#party-count')).toHaveText('3 people');
    await expect(host.page.locator('#party-host')).toContainText('You’re the host');
    await expect(bob.page.locator('#party-host')).toContainText('Ada is the host');
    await expect(cleo.page.locator('#party-members li')).toHaveCount(3);
    for (const p of [host, bob]) await place(p.page, 'library');
    const mine = await openGame(host.page, 'expo');
    await expect(mine.getByRole('button', { name: 'Start for everyone' })).toBeEnabled();
    await expect(mine.locator('.avrana-helper')).toHaveText('Moves everyone to this game.');
    await expect(mine.locator('[data-suits]')).toHaveText('Room for all three of you.');
    // a guest reads who starts it: a sentence, not a button that cannot be pressed
    const theirs = await openGame(bob.page, 'expo');
    await expect(theirs.locator('[data-wait]')).toHaveText('The host starts it. Ada chooses what the Party plays.');
    await expect(theirs.getByRole('button', { name: /start/i })).toHaveCount(0);
    await expect(theirs.getByRole('link')).toHaveCount(0);
    await expect(theirs.getByRole('button', { name: 'Add EXPO to favorites' })).toBeVisible();   // browsing is still theirs
    // Gauntlet II seats four (AVR-311): three phones all fit, and its page says so
    // (a game too small for the party is in "a fifth phone", below)
    const four = await openGame(bob.page, 'arcade-gauntlet2');
    await expect(four.locator('[data-suits="true"]')).toHaveText('Room for all three of you.');
    // The API refuses a follower who tries anyway, and a stale host tab too.
    const refused = await post(bob, 'session/launch', { game: 'expo', if_version: await version(bob) });
    expect(refused.status()).toBe(403);
    expect((await refused.json()).error).toBe('not_host');
    const stale = await post(host, 'session/launch', { game: 'expo', if_version: 0 });
    expect(stale.status()).toBe(409);
    expect((await stale.json()).error).toBe('stale');
    const stranger = await host.page.request.post('/party/api/session/launch', {
      data: { game: 'expo' }, headers: { 'Content-Type': 'application/json', Origin: 'https://evil.example' } });
    expect(stranger.status()).toBe(403);                      // a page from elsewhere cannot act
  });

  test('the frame: the Party control counts the people, the drawer and the Party page list them', async () => {
    const hud = host.page.locator('#hud'), drawer = host.page.locator('#social');
    for (const p of [host, bob]) await place(p.page, 'home');
    await expect(hud).toHaveAccessibleName('Your Party: 3 people here. Open people and chat');
    await expect(host.page.locator('#hud-faces img')).toHaveCount(3);
    await expect(host.page.locator('#party-lede')).toHaveText('Three of you are here.');
    await expect(host.page.locator('#party-names')).toHaveText('Ada (you), Bob and Cleo.');
    await expect(bob.page.locator('#party-names')).toHaveText('Bob (you), Ada and Cleo.');
    // Home's shelves are the same for the Host and a guest: what suits three, never a different list
    for (const p of [host, bob]) {
      await expect(p.page.locator('#home-great-h')).toHaveText('Great for three');
      await expect(p.page.locator('#home-lead [data-game]')).toBeVisible();
      await expect(p.page.locator('#home-recent-sec')).toBeHidden();        // nothing played on these phones yet
    }
    await hud.click();
    await expect(drawer).toBeVisible();
    await host.page.getByRole('button', { name: 'People', exact: true }).click();
    await expect(host.page.getByRole('button', { name: 'People', exact: true })).toHaveAttribute('aria-pressed', 'true');
    const rows = host.page.locator('#social-people li');
    await expect(rows).toHaveCount(3);
    await expect(rows.filter({ hasText: 'Ada (you)' }).locator('.avrana-tag')).toHaveText('Host');   // a word, not a crown
    await expect(rows.filter({ hasText: 'Bob' }).locator('.avrana-tag')).toHaveCount(0);
    expect(await smallTargets(host.page, '#social button, #social a, #social input')).toEqual([]);
    expect(await host.page.evaluate(() => document.activeElement?.closest('dialog')?.id)).toBe('social');
    await host.page.mouse.click(195, 800);                                  // a tap outside it closes it
    await expect(drawer).toBeHidden();
    await expect(host.page.locator('html')).toHaveAttribute('data-place', 'home');
    await hud.click();
    await host.page.keyboard.press('Escape');
    await expect(drawer).toBeHidden();
    await expect(hud).toBeFocused();
    await place(cleo.page, 'party');
    const faces = cleo.page.locator('#party-members li');
    await expect(faces).toHaveCount(3);
    await expect(faces.filter({ hasText: 'Ada' }).locator('.avrana-tag')).toHaveText('Host');
    await expect(faces.filter({ hasText: 'Cleo (you)' })).toBeVisible();
  });

  test('the Party moving wins over the frame: what is open closes, and a briefing keeps only the top bar', async () => {
    await place(bob.page, 'system');
    await bob.page.locator('#hud').click();
    await expect(bob.page.locator('#social')).toBeVisible();
    await place(cleo.page, 'library');
    await openGame(cleo.page, 'expo');                                       // Cleo is reading about another game
    await startForEveryone(host.page, 'bluff');
    for (const p of [host, bob, cleo]) await expect(p.page.locator('#scene')).toBeVisible();
    await expect(bob.page.locator('#social')).toBeHidden();                  // nothing stands between Bob and his answer
    for (const p of [host, bob, cleo]) {
      const page = p.page;
      // the top bar stays: what is going on, and who is here
      await expect(page.locator('#top-title'), p.name).toHaveText('Getting ready');
      await expect(page.locator('#top-title'), p.name).toBeFocused();        // the move is announced where focus is
      await expect(page.locator('#hud'), p.name).toBeVisible();
      await expect(page.locator('#top-back'), p.name).toBeHidden();
      await expect(page.locator('#limited-mark'), p.name).toBeHidden();      // Full Mode phones are never marked
      await expect(page.locator('#scene-title'), p.name).toHaveText('BLUFF');
      // and nothing else of the frame: no places, no Library, no chat, no "This phone"
      for (const gone of ['#nav', '#content', '#games', '#view-library', '#view-game', '#view-system', '#chat', '#party-chat', '#skip'])
        await expect(page.locator(gone), `${p.name} ${gone}`).toBeHidden();
      await expect(page.locator('#scene a[href]'), p.name).toHaveCount(0);   // no link leaves the briefing
      expect(await page.locator('#scene').getByRole('button').evaluateAll((els) => els.filter((el) => el.getClientRects().length).map((el) => el.id)), p.name)
        .toEqual(p === host ? ['scene-rules', 'choose-play', 'choose-watch', 'scene-start', 'scene-cancel'] : ['scene-rules', 'choose-play', 'choose-watch']);
    }
    await bob.page.locator('#choose-watch').click();
    await expect(bob.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    // the address does not decide: a phone's Back, or a typed place, leaves it on the briefing
    await bob.page.evaluate(() => { location.hash = '#library'; });
    await expect(bob.page.locator('#scene')).toBeVisible();
    await expect(bob.page.locator('#nav')).toBeHidden();
    await expect(bob.page.locator('#top-title')).toHaveText('Getting ready');
    await endForEveryone(host);
    // everyone is home again, in the frame; Cleo is back on the page she was reading
    await expect(bob.page.locator('#nav')).toBeVisible();
    await expect(bob.page.locator('#top-title')).not.toHaveText('Getting ready');
    await expect(cleo.page.locator('html')).toHaveAttribute('data-place', 'game');
    await expect(cleo.page.locator('#game-detail[data-id="expo"]')).toBeVisible();
    await expect(cleo.page.locator('#game-title')).toBeFocused();
  });

  test('over a briefing the Party control opens the people, and closing it any way keeps the page, its scroll and the focus', async () => {
    await bob.page.setViewportSize({ width: 360, height: 560 });             // short: the briefing scrolls
    await startForEveryone(host.page, 'bluff');
    for (const p of [host, bob, cleo]) await expect(p.page.locator('#scene')).toBeVisible();
    const page = bob.page, hud = page.locator('#hud'), drawer = page.locator('#social');
    await page.locator('#choose-watch').click();
    await expect(page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    await expect(hud).toHaveAccessibleName('Your Party: 3 people here. Open people');   // people, and nothing else, here
    await briefScroll(page, 90);
    const was = await briefScroll(page);
    expect(was).toBeGreaterThan(0);
    for (const [how, close] of CLOSERS(page, '#social-close', [180, 540])) {
      await hud.click();
      await expect(drawer, how).toBeVisible();
      await expect(drawer, how).toHaveAccessibleName('Your Party');
      await expect(page.locator('#social-where'), how).toHaveText('Getting ready for BLUFF.');
      await expect(page.locator('#social-people li'), how).toHaveCount(3);
      await expect(page.locator('#social-people li', { hasText: 'Ada' }).locator('.avrana-tag'), how).toHaveText('Host');
      // people only: no chat, no tabs, no link out
      for (const gone of ['#social-tabs', '#chat', '#chat-form', '#chat-name']) await expect(page.locator(gone), `${how} ${gone}`).toBeHidden();
      await expect(drawer.locator('a[href]'), how).toHaveCount(0);
      // a modal: focus is inside and stays inside, and the briefing behind cannot be reached
      expect(await page.evaluate(() => document.activeElement?.closest('dialog')?.id), how).toBe('social');
      for (let i = 0; i < 4; i++) {
        await page.keyboard.press('Tab');
        expect(await page.evaluate(() => Boolean(document.activeElement?.closest('#social')) || document.activeElement === document.body), how).toBe(true);
      }
      expect(await page.evaluate(() => { const b = document.getElementById('choose-play')!; b.focus(); return document.activeElement === b; }), how).toBe(false);
      expect(await smallTargets(page, '#social button'), how).toEqual([]);
      await close();
      await expect(drawer, how).toBeHidden();
      await expect(page.locator('#scene'), how).toBeVisible();               // the same page
      await expect(hud, how).toBeFocused();                                  // focus is back on what opened it
      expect(await briefScroll(page), how).toBe(was);                        // at the same scroll
      await expect(page.locator('#choose-watch'), how).toHaveAttribute('aria-pressed', 'true');   // with the same answer
    }
    // a person's answer, arriving while the drawer is open, does not close it
    await hud.click();
    await host.page.locator('#choose-watch').click();
    await expect(page.locator('#scene-count')).toHaveText('0 playing · 2 watching');
    await expect(drawer).toBeVisible();
    // the Party moving does: the Host chooses another game, and the drawer does not follow anyone home
    await host.page.locator('#scene-cancel').click();
    await expect(drawer).toBeHidden();
    await expect(page.locator('#scene')).toBeHidden();
    await expect(page.locator('#nav')).toBeVisible();
    await expect(hud).toHaveAccessibleName(/^Your Party: 3 people here\. Open people/);
  });

  test('How to play: from a game’s page and from the briefing; a first-timer reads it before playing', async () => {
    await withOnboarding(host, bob, cleo);
    // the game's page shows the game's own premise and offers its rules
    await place(host.page, 'library');
    const card = await openGame(host.page, 'bluff');
    await expect(card.locator('.avrana-premise')).toHaveText('Claim anything. Get caught, lose a card.');   // the catalog's sentence stays
    await expect(card.locator('.avrana-about')).toHaveText(ONBOARDING.premise);                            // the game's own, under it
    const row = card.getByRole('button', { name: 'How to play' });
    const rules = host.page.locator('#rules');
    for (const [how, close] of CLOSERS(host.page, '#rules-close', [200, 30])) {
      await row.click();
      await expect(rules, how).toBeVisible();
      await expect(rules, how).toHaveAccessibleName('How to play BLUFF');
      await expect(host.page.locator('#rules-body section'), how).toHaveCount(2);
      await expect(host.page.locator('#rules-body'), how).toContainText('You start with 5 cards.');   // the game's facts, filled in
      await expect(host.page.locator('#rules-ok'), how).toHaveText('Got it');
      expect(await host.page.evaluate(() => document.activeElement?.closest('dialog')?.id), how).toBe('rules');
      await close();
      await expect(rules, how).toBeHidden();
      await expect(row, how).toBeFocused();
      await expect(host.page.locator('html'), how).toHaveAttribute('data-place', 'game');
    }
    expect(await host.page.evaluate(() => localStorage.getItem('test-bluff-rules'))).toBeNull();   // closing is not agreeing
    await row.click();
    await host.page.locator('#rules-ok').click();
    await expect(rules).toBeHidden();
    expect(await host.page.evaluate(() => localStorage.getItem('test-bluff-rules'))).toBe('2');
    // a game with no onboarding offers no rules row and keeps the catalog's own sentence
    const expo = await openGame(host.page, 'expo');
    await expect(expo.locator('.avrana-premise')).toHaveText('One crew. Every card matters.');
    await expect(expo.locator('.avrana-about')).toHaveCount(0);
    await expect(expo.getByRole('button', { name: 'How to play' })).toHaveCount(0);

    await startForEveryone(host.page, 'bluff');
    for (const p of [host, bob, cleo]) await expect(p.page.locator('#scene')).toBeVisible();
    await expect(bob.page.locator('#scene-premise')).toHaveText(ONBOARDING.premise);
    // Ada read them on the game's page: her Play is her answer at once
    await host.page.locator('#choose-play').click();
    await expect(host.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'true');
    await expect(rules).toBeHidden();
    // Bob has not: Play shows him the rules first, and leaving them any way chooses nothing for him
    const play = bob.page.locator('#choose-play'), sheet = bob.page.locator('#rules');
    for (const [how, close] of CLOSERS(bob.page, '#rules-close', [200, 30])) {
      await play.click();
      await expect(sheet, how).toBeVisible();
      await expect(bob.page.locator('#rules-ok'), how).toHaveText('Got it, I’ll play');
      await close();
      await expect(sheet, how).toBeHidden();
      await expect(play, how).toBeFocused();
      await expect(play, how).toHaveAttribute('aria-pressed', 'false');
      expect((await view(bob)).session.setup.mine ?? null, how).toBeNull();           // Party Core was not told anything
      await expect(bob.page.locator('#scene'), how).toBeVisible();
    }
    // reading them from the row does not choose either, and closing them is not agreeing
    await bob.page.locator('#scene-rules').click();
    await expect(bob.page.locator('#rules-ok')).toHaveText('Got it');
    await bob.page.keyboard.press('Escape');
    await expect(bob.page.locator('#scene-rules')).toBeFocused();
    expect(await bob.page.evaluate(() => localStorage.getItem('test-bluff-rules'))).toBeNull();
    await play.click();
    await bob.page.locator('#rules-ok').click();                             // Got it, I’ll play
    await expect(sheet).toBeHidden();
    await expect(play).toHaveAttribute('aria-pressed', 'true');
    expect((await view(bob)).session.setup.mine).toBe('player');
    // once is enough: changing his mind and back asks nothing
    await bob.page.locator('#choose-watch').click();
    await expect(bob.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    await play.click();
    await expect(play).toHaveAttribute('aria-pressed', 'true');
    await expect(sheet).toBeHidden();
    // "Got it" from the briefing's own row records that Cleo read them, and chooses nothing
    await cleo.page.locator('#scene-rules').click();
    await cleo.page.locator('#rules-ok').click();
    await expect(cleo.page.locator('#rules')).toBeHidden();
    expect(await cleo.page.evaluate(() => localStorage.getItem('test-bluff-rules'))).toBe('2');
    expect((await view(cleo)).session.setup.mine ?? null).toBeNull();
    // watching never needs the rules
    await cleo.page.locator('#choose-watch').click();
    await expect(cleo.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    await expect(cleo.page.locator('#rules')).toBeHidden();
    // the rules are open when the Party moves: they close, and the phone goes with the Party
    await cleo.page.locator('#scene-rules').click();
    await expect(cleo.page.locator('#rules')).toBeVisible();
    await host.page.locator('#scene-cancel').click();
    await expect(cleo.page.locator('#rules')).toBeHidden();
    await expect(cleo.page.locator('#scene')).toBeHidden();
    await expect(cleo.page.locator('#nav')).toBeVisible();
    expect(await cleo.page.evaluate(() => document.querySelectorAll('dialog[open]').length)).toBe(0);
  });

  test('the briefing on a small phone: thumb-sized targets, nothing sideways, and everything reachable at 200% text', async () => {
    for (const p of [host, bob]) await p.page.setViewportSize({ width: 360, height: 640 });
    await bob.page.emulateMedia({ reducedMotion: 'reduce' });
    await startForEveryone(host.page, 'bluff');
    for (const p of [host, bob, cleo]) await expect(p.page.locator('#scene')).toBeVisible();
    const everything = '#scene :is(a, button), #top :is(a, button)';
    for (const p of [host, bob]) {
      expect(await smallTargets(p.page, everything), p.name).toEqual([]);
      expect(await sideways(p.page), p.name).toBeLessThanOrEqual(0);
      expect(await p.page.locator('#scene').evaluate((el) => el.scrollWidth - el.clientWidth), p.name).toBeLessThanOrEqual(0);
    }
    // the decision is in reach without scrolling on a phone this size
    for (const id of ['choose-play', 'choose-watch', 'scene-start']) await expect(host.page.locator('#' + id), id).toBeInViewport();
    // reading order: what, its rules, who, then the decision
    expect(await host.page.locator('#scene').evaluate((el) =>
      [...el.querySelectorAll('h2, h3, button')].filter((n) => n.getClientRects().length).map((n) => n.id)))
      .toEqual(['scene-title', 'scene-rules', 'scene-people-h', 'choose-play', 'choose-watch', 'scene-start', 'scene-cancel']);
    // what the game is, its rules and the decision are on screen at once; only the line-up may scroll
    for (const id of ['scene-title', 'scene-rules']) await expect(host.page.locator('#' + id), id).toBeInViewport({ ratio: 1 });
    // nothing on it moves for someone who asked for no motion
    expect(await bob.page.evaluate(() => [...document.querySelectorAll('#scene, #scene *, #top *')]
      .filter((el) => { const s = getComputedStyle(el); return s.animationName !== 'none' || parseFloat(s.transitionDuration) > 0; }).length)).toBe(0);
    // a choice is never colour alone: the chosen one carries a tick and is announced as pressed
    await host.page.locator('#choose-watch').click();
    await expect(host.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    await expect(host.page.locator('#choose-watch .tick')).toBeVisible();
    await expect(host.page.locator('#choose-play .tick')).toBeHidden();
    await expect(host.page.locator('#choose-watch')).toHaveAccessibleName('Watch this round');   // its words do not change
    for (const p of [host, bob]) {
      await p.page.evaluate(() => document.documentElement.style.setProperty('font-size', '200%'));
      expect(await sideways(p.page), p.name).toBeLessThanOrEqual(0);
      expect(await p.page.locator('#scene').evaluate((el) => el.scrollWidth - el.clientWidth), p.name).toBeLessThanOrEqual(0);
      await expect(p.page.locator('#top-title'), p.name).toBeInViewport();
      await expect(p.page.locator('#hud'), p.name).toBeInViewport();
      const reach = p === host ? ['scene-title', 'scene-roster', 'scene-rules', 'choose-play', 'choose-watch', 'scene-start', 'scene-status', 'scene-cancel']
        : ['scene-title', 'scene-roster', 'scene-rules', 'choose-play', 'choose-watch', 'scene-status'];
      for (const id of reach) {
        await p.page.locator('#' + id).scrollIntoViewIfNeeded();
        await expect(p.page.locator('#' + id), `${p.name} ${id}`).toBeInViewport();
      }
      expect(await smallTargets(p.page, everything), p.name).toEqual([]);
      // the people, over it, at that size
      await p.page.locator('#hud').scrollIntoViewIfNeeded();
      await p.page.locator('#hud').click();
      expect(await p.page.locator('#social').evaluate((el) => el.scrollWidth - el.clientWidth), p.name).toBeLessThanOrEqual(1);
      await p.page.locator('#social-people li').last().scrollIntoViewIfNeeded();
      await expect(p.page.locator('#social-people li').last(), p.name).toBeInViewport();
      await p.page.keyboard.press('Escape');
    }
    await endForEveryone(host);
  });

  test('the Library for three: the size of the party orders the shelf and never empties it', async () => {
    const page = host.page;
    await place(page, 'library');
    const order = () => page.locator('#games [data-game]').evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.game));
    // all five seat three (Gauntlet II seats four since AVR-311): one shelf, and nobody is "not for three"
    await expect(page.locator('#games h3')).toHaveText(['Great for three']);
    await expect(page.locator('#games .avrana-sec .meta')).toHaveText(['5']);
    expect(await order()).toEqual(['bluff', 'expo', 'arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms']);
    await expect(page.locator('#game-count')).toHaveText('5 games');
    const four = page.locator('#games [data-game="arcade-gauntlet2"]');
    await expect(four.locator('.seats')).toHaveText('1–4');
    await expect(four).toHaveAccessibleName(/^Gauntlet II\. 1–4 players\. TV optional/);
    await expect(page.locator('#games [data-game="bluff"] .seats')).toHaveText('2–6');
    // the sheet says how many are here; it does not filter for them
    await page.locator('#lib-filter').click();
    await expect(page.locator('#filters-party')).toHaveText('Your Party is 3');
    await expect(page.locator('#filter-players').getByRole('button', { pressed: true })).toHaveText('Any');
    await expect(page.locator('#filters-show')).toHaveText('Show 5 games');
    await page.keyboard.press('Escape');
    // a guest sees the same shelf as the Host
    await place(bob.page, 'library');
    await expect(bob.page.locator('#games h3')).toHaveText(['Great for three']);
    // the smallest covers drop the plain range: nothing is wrong, so nothing is shown
    await page.locator('#lib-view').click();
    await page.locator('#view-choices [data-v="compact"]').click();
    await expect(four.locator('.seats')).toBeHidden();
    await expect(page.locator('#games [data-game="bluff"] .seats')).toBeHidden();
    // the list is the same list, in the same order
    await page.locator('#lib-view').click();
    await page.locator('#view-choices [data-v="list"]').click();
    await expect(page.locator('#games h3')).toHaveText(['Great for three']);
    expect(await order()).toEqual(['bluff', 'expo', 'arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms']);
    await expect(page.locator('#games .avrana-row', { hasText: 'Gauntlet II' })).toContainText('1–4');
    // Home says the same thing
    await place(page, 'home');
    await expect(page.locator('#home-lead [data-game="bluff"]')).toContainText('Room for all three of you.');
    await expect(page.locator('#home-great [data-game="arcade-gauntlet2"]')).toHaveCount(1);
    // someone goes home: the shelf follows the party without being asked
    // (her page is closed first: an open Party page puts its phone straight back in the party)
    const origin = new URL(cleo.page.url()).origin;
    await cleo.page.close();
    const left = await cleo.context.request.post('/party/api/leave', { data: {}, headers: { 'Content-Type': 'application/json', Origin: origin } });
    expect(left.status()).toBe(200);
    await expect(page.locator('#home-great-h')).toHaveText('Great for two');
    await expect(page.locator('#home-great [data-game="arcade-gauntlet2"]')).toHaveCount(1);
    await place(page, 'library');
    await expect(page.locator('#games h3')).toHaveText(['Great for two']);
    await expect(page.locator('#games [data-game]')).toHaveCount(5);
  });

  test('a fifth phone: a game too small for the party says who sits out, and the shelf still lists all five', async ({ browser }) => {
    const dee = await phone(browser, 'Dee'), eli = await phone(browser, 'Eli');
    try {
      const page = host.page;
      await place(page, 'library');
      const order = () => page.locator('#games [data-game]').evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.game));
      const all = ['bluff', 'expo', 'arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms'];
      await expect(page.locator('#games h3')).toHaveText(['Great for five', 'Not for five']);
      await expect(page.locator('#games .avrana-sec .meta')).toHaveText(['2', '3']);
      expect(await order()).toEqual(all);                                         // all five, best fit first
      await expect(page.locator('#game-count')).toHaveText('5 games');
      const four = page.locator('#games [data-game="arcade-gauntlet2"]');
      await expect(four.locator('.seats')).toHaveText('Max 4');
      await expect(four).toHaveAccessibleName(/^Gauntlet II\. Max 4, you’re 5\. TV optional/);
      await expect(page.locator('#games [data-game="bluff"] .seats')).toHaveText('2–6');
      // the sheet says how many are here; it does not filter for them
      await page.locator('#lib-filter').click();
      await expect(page.locator('#filters-party')).toHaveText('Your Party is 5');
      await expect(page.locator('#filters-show')).toHaveText('Show 5 games');
      await page.keyboard.press('Escape');
      // a guest sees the same shelf as the Host, and the game's page says what happens to the rest
      await place(bob.page, 'library');
      await expect(bob.page.locator('#games h3')).toHaveText(['Great for five', 'Not for five']);
      const gauntlet = await openGame(bob.page, 'arcade-gauntlet2');
      await expect(gauntlet.locator('[data-suits="false"]')).toHaveText('Up to 4 play; one of you sits out.');
      await expect(gauntlet.locator('[data-suits="false"] svg')).toBeVisible();   // a mark and words, not colour
      await expect((await openGame(bob.page, 'bluff')).locator('[data-suits="true"]')).toHaveText('Room for all five of you.');
      // the smallest covers drop the plain range and keep the warning
      await page.locator('#lib-view').click();
      await page.locator('#view-choices [data-v="compact"]').click();
      await expect(four.locator('.seats')).toBeVisible();
      await expect(page.locator('#games [data-game="bluff"] .seats')).toBeHidden();
      // the list is one list, in the same order, and says why a title is last
      await page.locator('#lib-view').click();
      await page.locator('#view-choices [data-v="list"]').click();
      await expect(page.locator('#games h3')).toHaveText(['All games']);
      await expect(page.locator('#games .avrana-sec .meta')).toHaveText('5, best fit first');
      expect(await order()).toEqual(all);
      await expect(page.locator('#games .avrana-row', { hasText: 'Gauntlet II' })).toContainText('Max 4, you’re 5');
      // Home says the same thing: only what seats five is on its shelf
      await place(page, 'home');
      await expect(page.locator('#home-lead [data-game="bluff"]')).toContainText('Room for all five of you.');
      await expect(page.locator('#home-great [data-game="arcade-gauntlet2"]')).toHaveCount(0);
      // one goes home: the shelf follows the party, and Gauntlet II is on it again
      // (his page is closed first: an open Party page puts its phone straight back in the party)
      const origin = new URL(eli.page.url()).origin;
      await eli.page.close();
      const left = await eli.context.request.post('/party/api/leave', { data: {}, headers: { 'Content-Type': 'application/json', Origin: origin } });
      expect(left.status()).toBe(200);
      await expect(page.locator('#home-great-h')).toHaveText('Great for four');
      await expect(page.locator('#home-great [data-game="arcade-gauntlet2"]')).toHaveCount(1);
      await place(page, 'library');
      await expect(page.locator('#games h3')).toHaveText(['Great for four']);
      await expect(page.locator('#games [data-game]')).toHaveCount(5);
    } finally {
      await dee.context.close();
      await eli.context.close();
    }
  });

  test('a round is remembered on the phones that played it, once, and not on a phone that watched', async () => {
    await startForEveryone(host.page, 'expo');
    for (const p of [host, bob, cleo]) await expect(p.page).toHaveURL(/\/games\/expo\//);
    expect((await view(cleo)).session.my_role).toBe('spectator');           // two play this one here; Party Core says who
    await bob.page.goto('/party/');                                          // wanders back mid-round; sent in again
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    await cleo.page.goto('/party/');                                         // so does the watcher: still nothing to remember
    await expect(cleo.page).toHaveURL(/\/games\/expo\//);
    await endForEveryone(host);
    for (const p of [host, bob, cleo]) await expect(p.page, p.name).toHaveURL(/\/party\/$/);
    for (const p of [host, bob]) {
      await expect(p.page, p.name).toHaveURL(/\/party\/$/);
      await expect(p.page.locator('#home-lead [data-game="expo"]'), p.name).toContainText('You played this last.');
      await expect(p.page.locator('#home-recent-sec'), p.name).toBeHidden();   // it leads; it is not listed twice
      // per phone, in the list the games have always written (decision 9: nothing Party-wide)
      expect(await p.page.evaluate(() => localStorage.getItem('lg-recent')), p.name).toBe('["avrana:expo"]');
      // once: Bob came back to the page mid-round, and the round still counts as one game opened
      expect(await p.page.evaluate(() => localStorage.getItem('lg-play-total')), p.name).toBe('1');
    }
    // a second round is a second game opened; held results are not a round
    await startForEveryone(host.page, 'expo');
    for (const p of [host, bob]) await expect(p.page).toHaveURL(/\/games\/expo\//);
    await endForEveryone(host);
    await expect(bob.page).toHaveURL(/\/party\/$/);
    expect(await bob.page.evaluate(() => localStorage.getItem('lg-play-total'))).toBe('2');
    // Cleo watched both rounds: nothing is "recently played" on her phone, anywhere it would show
    await expect(cleo.page.locator('html')).toHaveAttribute('data-ready', 'true');
    await expect(cleo.page.locator('#home-lead [data-game]')).toBeVisible();
    await expect(cleo.page.locator('#home-lead')).not.toContainText('You played this last.');
    await expect(cleo.page.locator('#home-recent-sec')).toBeHidden();
    expect(await cleo.page.evaluate(() => [localStorage.getItem('lg-recent'), localStorage.getItem('lg-play-total')])).toEqual([null, null]);
    await place(cleo.page, 'library');
    await cleo.page.locator('#game-views').getByRole('button', { name: 'Recent', exact: true }).click();
    await expect(cleo.page.locator('#games [data-empty="recent"]')).toContainText('Nothing played yet');
  });

  test('the host starts a game and everyone goes there; ending it brings everyone home', async () => {
    await startForEveryone(host.page, 'expo');
    for (const p of [host, bob, cleo]) {
      await expect(p.page).toHaveURL(/\/games\/expo\/\?avrana=1/);
      await expect(p.page.locator('h1[data-game="expo"]')).toBeVisible();
    }
    // Two seats: the third phone watches, but is at the same place as everyone else.
    const s = (await view(cleo)).session;
    expect(s.game).toBe('expo');
    expect(s.my_role).toBe('spectator');
    expect((await view(bob)).session.my_role).toBe('player');
    // Only the host gets the fallback "end" control on a page that draws none of its own.
    await expect(host.page.locator('#avrana-party-end')).toBeVisible();
    await expect(bob.page.locator('#avrana-party-end')).toHaveCount(0);
    await host.page.locator('#avrana-party-end').click();
    await expect(host.page.locator('#avrana-party-end')).toHaveText('Tap again to end it');
    await host.page.locator('#avrana-party-end').click();
    for (const p of [host, bob, cleo]) {
      await expect(p.page).toHaveURL(/\/party\/$/);
      await expect(p.page.locator('html'), p.name).toHaveAttribute('data-ready', 'true');
      await expect(p.page.locator('#party-count'), p.name).toHaveText('3 people');
    }
  });

  test('switching games: the next start moves the whole party, and the old page follows', async () => {
    await startForEveryone(host.page, 'expo');
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    // The host switches from inside the game (the party API, as a game's shell would call it).
    const sw = await post(host, 'session/switch', { game: 'arcade-gauntlet2', if_version: await version(host) });
    expect(sw.status()).toBe(200);
    for (const p of [host, bob, cleo]) await expect(p.page).toHaveURL(/\/arcade\//);
    expect((await view(host)).session.game).toBe('arcade-gauntlet2');
    await endForEveryone(host);
    for (const p of [host, bob, cleo]) await expect(p.page).toHaveURL(/\/party\/$/);
  });

  test('a phone that reloads mid-game keeps its identity and its seat', async () => {
    await startForEveryone(host.page, 'expo');
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    const before = await view(bob);
    await bob.page.reload();
    await expect(bob.page.locator('h1[data-game="expo"]')).toBeVisible();
    const after = await view(bob);
    expect(after.me.id).toBe(before.me.id);
    expect(after.session.id).toBe(before.session.id);
    expect(after.session.my_role).toBe('player');
    expect(after.members).toHaveLength(3);                 // no duplicate member from the reload
    // A phone that wanders back to Party Home during the round is sent to the game again.
    await bob.page.goto('/party/');
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    await endForEveryone(host);
  });

  test('a ticket for a session that ended is refused, and the next round is a new session', async () => {
    await startForEveryone(host.page, 'expo');
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    const first = (await view(bob)).session.id;
    await endForEveryone(host);
    await expect(bob.page).toHaveURL(/\/party\/$/);
    const stale = await post(bob, 'session/ticket', { game: 'expo' });
    expect([404, 409]).toContain(stale.status());
    await startForEveryone(host.page, 'expo');
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
    expect((await view(bob)).session.id).not.toBe(first);
    await endForEveryone(host);
  });

  test('the ready-or-watch setup: everyone chooses, only the host starts', async () => {
    await startForEveryone(host.page, 'bluff');
    for (const p of [host, bob, cleo]) await expect(p.page.locator('#scene')).toBeVisible();
    await expect(bob.page.locator('#scene-start')).toBeHidden();
    await expect(bob.page.locator('#scene-cancel')).toBeHidden();
    await expect(bob.page.locator('#scene-status')).toHaveText('Waiting for Ada to start');
    await expect(host.page.locator('#scene-start')).toBeVisible();
    await expect(host.page.locator('#scene-start')).toBeDisabled();       // nobody chose yet
    await expect(host.page.locator('#scene-status')).not.toBeEmpty();     // and Party Core's reason is said
    await expect(host.page.locator('#scene-cancel')).toBeVisible();
    // the line-up: a name, the word "Host", and each answer as an icon and a word
    const line = (p: Phone, who: string) => p.page.locator('#scene-roster li', { hasText: who });
    await expect(host.page.locator('#scene-roster li')).toHaveCount(3);
    await expect(line(host, 'You').locator('.avrana-tag')).toHaveText('Host');
    await expect(line(bob, 'Ada').locator('.avrana-tag')).toHaveText('Host');
    await expect(line(bob, 'You').locator('.avrana-tag')).toHaveCount(0);
    for (const who of ['Ada', 'You', 'Cleo']) {
      await expect(line(bob, who).locator('.ans')).toHaveText('Choosing');
      await expect(line(bob, who).locator('.ans svg')).toBeVisible();
    }
    for (const p of [host, bob]) {
      await p.page.locator('#choose-play').click();
      const ok = p.page.locator('#rules-ok');
      if (await ok.isVisible().catch(() => false)) await ok.click();      // first-play briefing
      await expect(p.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'true');
    }
    await cleo.page.locator('#choose-watch').click();
    await expect(cleo.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    await expect(host.page.locator('#scene-count')).toHaveText('2 playing · 1 watching');
    await expect(line(host, 'You').locator('.ans')).toHaveText('Playing');
    await expect(line(host, 'Bob').locator('.ans')).toHaveText('Playing');
    await expect(line(host, 'Cleo').locator('.ans')).toHaveText('Watching');
    await expect(line(cleo, 'You').locator('.ans')).toHaveText('Watching');
    await expect(host.page.locator('#scene-start')).toBeEnabled();
    // a phone that reloads on the briefing is back on it, with its answer
    await bob.page.reload();
    await expect(bob.page.locator('html')).toHaveAttribute('data-ready', 'true');
    await expect(bob.page.locator('#scene')).toBeVisible();
    await expect(bob.page.locator('#nav')).toBeHidden();
    await expect(bob.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'true');
    // only the Host moves the Party: a guest's start, and a guest's "choose another game", are refused
    const refused = await post(cleo, 'session/start', { if_version: await version(cleo) });
    expect(refused.status()).toBe(403);
    expect((await post(bob, 'session/end', { if_version: await version(bob) })).status()).toBe(403);
    await expect(bob.page.locator('#scene')).toBeVisible();
    await host.page.locator('#scene-start').click();
    for (const p of [host, bob, cleo]) await expect(p.page).toHaveURL(/\/games\/bluff\//);
    expect((await view(cleo)).session.my_role).toBe('spectator');
    await endForEveryone(host);
  });

  test('a start that is refused says why at the top of the page, and the Host’s button keeps the focus', async () => {
    await host.page.route('**/party/api/session/launch', (route) => route.fulfill({ status: 503, json: { error: 'unavailable' } }));
    await place(host.page, 'library');
    const card = await openGame(host.page, 'bluff');
    const start = card.getByRole('button', { name: 'Start for everyone' });
    await start.focus();
    await host.page.keyboard.press('Enter');
    await expect(host.page.locator('#party-note')).not.toBeEmpty();
    await expect(host.page.locator('#party-note')).toBeInViewport();
    await expect(start).toBeFocused();                                       // not dropped by the redraw
    await expect(start).toBeEnabled();                                       // and it can be pressed again
    await expect(host.page.locator('#scene')).toBeHidden();
    expect((await view(host)).location.at).toBe('home');
    for (const p of [bob, cleo]) await expect(p.page.locator('#scene')).toBeHidden();
    // pressed again once the Party answers: the same button starts it
    await host.page.unroute('**/party/api/session/launch');
    await host.page.keyboard.press('Enter');
    for (const p of [host, bob, cleo]) await expect(p.page.locator('#scene')).toBeVisible();
    await expect(host.page.locator('#party-note')).toBeEmpty();
    await endForEveryone(host);
  });

  test('the Host’s button starts the game on screen, also when one game’s page follows another’s directly', async () => {
    await place(host.page, 'library');
    const expo = await openGame(host.page, 'expo');
    await expect(expo.getByRole('button', { name: 'Start for everyone' })).toHaveAttribute('data-start', 'expo');
    await host.page.evaluate(() => { location.hash = '#game/arcade-gauntlet2'; });   // no place in between: the page is redrawn in place
    const two = host.page.locator('#game-detail[data-id="arcade-gauntlet2"]');
    await expect(two).toBeVisible();
    await expect(host.page.locator('#game-title')).toHaveText('Gauntlet II');
    const start = two.getByRole('button', { name: 'Start for everyone' });
    await expect(start).toHaveAttribute('data-start', 'arcade-gauntlet2');
    await start.click();
    for (const p of [host, bob, cleo]) await expect(p.page, p.name).toHaveURL(/\/arcade\//);
    expect((await view(host)).session.game).toBe('arcade-gauntlet2');
    await endForEveryone(host);
  });

  test('Choose another game: the Host takes everyone back, each to the page they were on', async () => {
    await place(bob.page, 'party');
    await startForEveryone(host.page, 'bluff');                              // Ada starts it from BLUFF's own page
    for (const p of [host, bob, cleo]) await expect(p.page.locator('#scene')).toBeVisible();
    await bob.page.locator('#choose-watch').click();
    await host.page.locator('#scene-cancel').click();
    for (const p of [host, bob, cleo]) {
      await expect(p.page.locator('#scene'), p.name).toBeHidden();
      await expect(p.page.locator('#nav'), p.name).toBeVisible();
    }
    await expect(host.page.locator('#game-detail[data-id="bluff"]')).toBeVisible();   // where she was: she can pick again, or go back
    await expect(host.page.locator('#game-title')).toBeFocused();
    await expect(host.page.locator('#top-back')).toHaveAccessibleName('Library');
    await expect(host.page.getByRole('button', { name: 'Start for everyone' })).toBeEnabled();
    await host.page.locator('#top-back').click();
    await expect(host.page.locator('html')).toHaveAttribute('data-place', 'library');
    await expect(bob.page.locator('html')).toHaveAttribute('data-place', 'party');
    await expect(bob.page.locator('#top-title')).toHaveText('Party');
    await expect(cleo.page.locator('html')).toHaveAttribute('data-place', 'home');
    expect((await view(bob)).location.at).toBe('home');
  });

  test('a fourth phone: three guests, and still only the Host’s button moves the Party', async ({ browser }) => {
    const dee = await phone(browser, 'Dee');
    try {
      const guests = [bob, cleo, dee];
      for (const p of [host, ...guests]) await place(p.page, 'library');
      for (const p of guests) {
        for (const id of ['bluff', 'expo', 'arcade-gauntlet2']) {
          const card = await openGame(p.page, id);
          await expect(card.locator('[data-wait]'), `${p.name} ${id}`).toContainText('The host starts it. Ada chooses');
          await expect(card.getByRole('button', { name: /start/i }), `${p.name} ${id}`).toHaveCount(0);
        }
        expect((await post(p, 'session/launch', { game: 'bluff', if_version: await version(p) })).status(), p.name).toBe(403);
      }
      // Gauntlet II seats four (AVR-311): all four phones fit it, as they fit BLUFF
      // (a title too small for the party is in "a fifth phone", above)
      await expect((await openGame(dee.page, 'arcade-gauntlet2')).locator('[data-suits="true"]')).toHaveText('Room for all four of you.');
      await expect((await openGame(dee.page, 'bluff')).locator('[data-suits="true"]')).toHaveText('Room for all four of you.');
      expect((await view(host)).location.at).toBe('home');                   // nobody but Ada moved anything
      // BLUFF: a briefing for all four, and a guest can neither start it nor call it off
      await startForEveryone(host.page, 'bluff');
      for (const p of [host, ...guests]) {
        await expect(p.page.locator('#scene'), p.name).toBeVisible();
        await expect(p.page.locator('#scene-roster li'), p.name).toHaveCount(4);
      }
      for (const p of guests) {
        await expect(p.page.locator('#scene-start'), p.name).toBeHidden();
        await expect(p.page.locator('#scene-cancel'), p.name).toBeHidden();
        expect((await post(p, 'session/start', { if_version: await version(p) })).status(), p.name).toBe(403);
        expect((await post(p, 'session/end', { if_version: await version(p) })).status(), p.name).toBe(403);
      }
      for (const p of [host, bob]) {
        await p.page.locator('#choose-play').click();
        await expect(p.page.locator('#choose-play'), p.name).toHaveAttribute('aria-pressed', 'true');
      }
      for (const p of [cleo, dee]) await p.page.locator('#choose-watch').click();
      await expect(host.page.locator('#scene-count')).toHaveText('2 playing · 2 watching');
      await host.page.locator('#scene-start').click();
      for (const p of [host, ...guests]) await expect(p.page, p.name).toHaveURL(/\/games\/bluff\//);
      await endForEveryone(host);
      for (const p of [host, ...guests]) await expect(p.page, p.name).toHaveURL(/\/party\//);
      // EXPO keeps its own setup and Gauntlet its direct start: no briefing for either
      for (const [id, url] of [['expo', /\/games\/expo\//], ['arcade-gauntlet2', /\/arcade\//]] as const) {
        await expect(host.page.locator('html'), id).toHaveAttribute('data-ready', 'true');
        await startForEveryone(host.page, id);
        for (const p of [host, ...guests]) await expect(p.page, `${p.name} ${id}`).toHaveURL(url);
        expect((await view(host)).location.at, id).toBe('game');
        await endForEveryone(host);
        for (const p of [host, ...guests]) await expect(p.page, `${p.name} ${id}`).toHaveURL(/\/party\//);
      }
    } finally {
      await dee.context.close();
    }
  });

  test('the Host’s phone goes quiet at home: Away is said, then hosting passes on, and nothing is counted down', async ({ request }) => {
    await goQuiet(host);
    await later(request, 50);                                               // past 45 s: Party Core says Ada is away
    for (const p of [bob, cleo]) {
      await expect(p.page.locator('#party-host'), p.name).toHaveText('Ada is the host, and is away.');
      await expect(p.page.locator('#party-state'), p.name).toHaveText('Hosting passes to someone here if Ada isn’t back soon.');
      await expect(p.page.locator('#party-state svg'), p.name).toBeVisible();                  // a mark and words, not colour
      await expect(p.page.locator('#party-state'), p.name).toHaveAttribute('role', 'status');
    }
    expect(await bob.page.locator('#content').innerText()).not.toMatch(/\d+\s*(s|sec|seconds|min)/i);   // no countdown: the view has none
    expect((await view(bob)).members.find((m: { host: boolean }) => m.host).name).toBe('Ada');            // still hers for now
    await place(bob.page, 'party');
    await expect(bob.page.locator('#people-state')).toHaveText('Hosting passes to someone here if Ada isn’t back soon.');
    await expect(bob.page.locator('#party-members li', { hasText: 'Ada' })).toContainText('Away');
    expect(await sideways(bob.page)).toBeLessThanOrEqual(0);

    await later(request, 30);                                               // 30 s more: the role passes to the earliest here
    await expect(bob.page.locator('#people-state')).toHaveText('You’re hosting now. Ada has been away, so you pick what the Party plays.');
    await place(bob.page, 'home');
    await expect(bob.page.locator('#party-host')).toContainText('You’re the host');
    await expect(bob.page.locator('#party-state')).toBeHidden();            // the notice below says it; not twice
    const note = bob.page.locator('#host-now');
    await expect(note).toBeVisible();
    await expect(note.locator('b')).toHaveText('You’re hosting now');
    await expect(note).toContainText('Ada has been away, so you pick what the Party plays.');
    expect(await smallTargets(bob.page, '#host-now button')).toEqual([]);
    await note.getByRole('button', { name: 'Dismiss' }).click();
    await expect(note).toBeHidden();
    await expect(bob.page.locator('#top-title')).toBeFocused();             // focus is not left on a button that is gone
    await expect(cleo.page.locator('#party-state')).toHaveText('Bob is hosting now. Ada has been away.');
    await expect(cleo.page.locator('#party-host')).toHaveText('Bob is the host and picks the games.');
    // only Bob's button moves the Party now
    await expect((await (async () => { await place(bob.page, 'library'); return openGame(bob.page, 'expo'); })()).getByRole('button', { name: 'Start for everyone' })).toBeVisible();
    // Ada comes back: she is told who hosts, and nothing about what she did not see
    await host.page.goto('/party/');
    await expect(host.page.locator('html')).toHaveAttribute('data-ready', 'true');
    await expect(host.page.locator('#party-host')).toHaveText('Bob is the host and picks the games.');
    await expect(host.page.locator('#party-state')).toBeHidden();
    await expect(host.page.locator('#host-now')).toBeHidden();
  });

  test('the Host goes quiet on a briefing: the game cannot start, everyone reads why, and the new Host gets Start', async ({ request }) => {
    await startForEveryone(host.page, 'bluff');
    for (const p of [host, bob, cleo]) await expect(p.page.locator('#scene')).toBeVisible();
    await bob.page.locator('#choose-play').click();
    await expect(bob.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'true');
    await goQuiet(host);
    await later(request, 50);
    const waiting = 'Ada, the Host, is away, so the game can’t start yet. Hosting passes to someone here if Ada isn’t back soon.';
    for (const p of [bob, cleo]) {
      await expect(p.page.locator('#scene-status'), p.name).toHaveText(waiting);
      await expect(p.page.locator('#scene-roster li', { hasText: 'Ada' }), p.name).toContainText('Away');
      await expect(p.page.locator('#scene-start'), p.name).toBeHidden();
      expect(await sideways(p.page), p.name).toBeLessThanOrEqual(0);
    }
    await expect(bob.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'true');   // an answer already given stays
    await view(bob); await view(cleo);                                      // both have asked since: they are here when the role passes
    await later(request, 30);
    await expect(bob.page.locator('#scene-start')).toBeVisible();
    await expect(bob.page.locator('#scene-status')).toHaveText(/^You’re hosting now\./);
    await expect(bob.page.locator('#scene-cancel')).toBeVisible();
    await expect(cleo.page.locator('#scene-status')).toHaveText('Bob is hosting now. Waiting for Bob to start');
    await expect(cleo.page.locator('#scene-roster li', { hasText: 'Bob' }).locator('.avrana-tag')).toHaveText('Host');
    await expect(bob.page.locator('#scene')).toBeVisible();                 // the briefing is still the place
  });

  test('during a round the Host’s role does not move, however long their phone is quiet', async ({ request }) => {
    await startForEveryone(host.page, 'expo');
    for (const p of [host, bob, cleo]) await expect(p.page).toHaveURL(/\/games\/expo\//);
    await goQuiet(host);
    await later(request, 300);
    const now = await view(bob);
    const ada = now.members.find((m: { name: string }) => m.name === 'Ada');
    expect([ada.host, ada.presence, now.location.at]).toEqual([true, 'playing', 'game']);
    await expect(bob.page).toHaveURL(/\/games\/expo\//);
  });

  test('a phone that loses the Party box says so, keeps what it knew, and comes back to where the Party is', async () => {
    await bob.page.clock.install();
    const restore = await cutOff(bob, cleo);
    const net = bob.page.locator('#net');
    await expect(net).toBeVisible();
    await expect(net).toHaveAttribute('role', 'status');
    await expect(net).toHaveText(/Reconnecting\. What you see may be out of date\./);
    await expect(net.getByRole('button', { name: 'Try again' })).toBeHidden();       // it is trying by itself
    await expect(bob.page.locator('html')).toHaveAttribute('data-link', 'reconnecting');
    await expect(bob.page.locator('#status')).toBeHidden();                          // "Connected" is not said beside it
    await expect(bob.page.locator('#party-lede')).toHaveText('Three of you are here.');   // what was known stays
    await expect(bob.page.locator('#home-games')).toBeVisible();
    for (const where of ['library', 'party', 'system'] as const) {          // said in every place
      await place(bob.page, where);
      await expect(net, where).toBeVisible();
    }
    await place(bob.page, 'home');

    await bob.page.clock.fastForward(11_000);                               // about ten seconds (the owner, 2026-10-06)
    await expect(bob.page.locator('html')).toHaveAttribute('data-link', 'lost');
    await expect(net.locator('b')).toHaveText('This phone lost the Party box');
    await expect(net).toContainText('Check it’s on the Avrana Party Wi-Fi.');
    await expect(net).not.toContainText('Hosting passes');                  // Bob is not the Host
    await expect(net.locator('svg')).toBeVisible();
    const again = net.getByRole('button', { name: 'Try again' });
    expect(await smallTargets(bob.page, '#net button')).toEqual([]);
    expect(await sideways(bob.page)).toBeLessThanOrEqual(0);
    await again.focus();
    await again.click();                                                    // still cut off: it stays honest, and the button stays
    await expect(net.locator('b')).toHaveText('This phone lost the Party box');
    await expect(again).toBeFocused();

    // the Party moves while this phone is away
    await startForEveryone(host.page, 'bluff');
    await expect(cleo.page.locator('#scene')).toBeVisible();
    await expect(bob.page.locator('#scene')).toBeHidden();
    await restore();                                                        // the Wi-Fi is back: no tap is needed
    await expect(bob.page.locator('#scene')).toBeVisible({ timeout: 12_000 });
    await expect(bob.page.locator('html')).toHaveAttribute('data-link', 'ok');
    await expect(net).toBeHidden();
    await expect(bob.page.locator('#scene-live')).toBeVisible();
    await expect(bob.page.locator('#top-title')).toBeFocused();             // never left on the button that went away
  });

  test('the Host’s own phone loses the box: it is told its role passes on, with no time promised', async () => {
    await host.page.clock.install();
    await cutOff(host, cleo);
    await expect(host.page.locator('#net')).toContainText('Reconnecting');
    await host.page.clock.fastForward(11_000);
    await expect(host.page.locator('#net')).toContainText('Check it’s on the Avrana Party Wi-Fi. Hosting passes on if it stays away.');
    expect(await host.page.locator('#net').innerText()).not.toMatch(/\d/);
  });

  test('on a briefing a phone that loses the box keeps its answer, then gets one thing to do, then its choices back', async () => {
    await startForEveryone(host.page, 'bluff');
    for (const p of [host, bob, cleo]) await expect(p.page.locator('#scene')).toBeVisible();
    await cleo.page.locator('#choose-watch').click();
    await expect(cleo.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    await cleo.page.clock.install();
    const restore = await cutOff(cleo, bob);
    await expect(cleo.page.locator('#scene-net')).toHaveText('Reconnecting. Your answer stays as it is for now.');
    await expect(cleo.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    await expect(cleo.page.locator('#scene-lost')).toBeHidden();
    await cleo.page.locator('#choose-watch').focus();
    await cleo.page.clock.fastForward(11_000);
    await expect(cleo.page.locator('#scene-lost')).toContainText('This phone lost the Party box. Check it’s on the Avrana Party Wi-Fi.');
    await expect(cleo.page.locator('#scene-live')).toBeHidden();            // choices that would go nowhere give way
    await expect(cleo.page.locator('#scene-retry')).toBeFocused();          // focus moves to the one thing to do
    expect(await smallTargets(cleo.page, '#scene button')).toEqual([]);
    expect(await sideways(cleo.page)).toBeLessThanOrEqual(0);
    await expect(cleo.page.locator('#nav')).toBeHidden();                   // still a briefing: no way off it
    await restore();                                                        // (nothing changed meanwhile: the box has no news to send)
    // "Try again" asks at once. (Pressed through the page: the phone's own next try may land
    // first and take the button away, which is the same recovery and not a failure.)
    await cleo.page.locator('#scene-retry').evaluate((b: HTMLButtonElement) => b.click());
    await expect(cleo.page.locator('#scene-live')).toBeVisible();
    await expect(cleo.page.locator('#scene-lost')).toBeHidden();
    await expect(cleo.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    await expect(cleo.page.locator('#top-title')).toBeFocused();
  });

  test('trouble on the Party box: the Host is told on Home and may put it away; everyone else sees only what is off', async ({ request }) => {
    try {
      expect((await request.post('/__test__/arcade/down')).status()).toBe(204);
      for (const p of [host, bob]) { await p.page.reload(); await expect(p.page.locator('html')).toHaveAttribute('data-ready', 'true'); }
      const note = host.page.locator('#trouble');
      await expect(note).toBeVisible();
      await expect(note).toHaveAttribute('role', 'status');
      await expect(note.locator('b')).toHaveText('Arcade games are off right now');
      await expect(note).toContainText('Card and party games play as usual.');
      await expect(note.locator('svg').first()).toBeVisible();
      expect(await smallTargets(host.page, '#trouble a, #trouble button')).toEqual([]);
      expect(await sideways(host.page)).toBeLessThanOrEqual(0);
      await expect(bob.page.locator('#home-games')).toBeVisible();
      await expect(bob.page.locator('#trouble')).toBeHidden();              // a guest cannot act on it
      // "What changed" is System, where the Host reads what it means for play
      await note.getByRole('link', { name: 'What changed' }).click();
      await expect(host.page.locator('html')).toHaveAttribute('data-place', 'system');
      const health = host.page.locator('#health [data-health="warn"]');
      await expect(health).toHaveCount(1);
      await expect(health.locator('b')).toHaveText('Arcade games are off right now');
      await expect(health).toContainText('The arcade part of the Party box isn’t answering. Gauntlet II can’t be played. Card and party games are not affected.');
      await expect(host.page.locator('#health [data-health="ok"]')).toHaveCount(0);
      // a guest's System says what their shelf already shows, and no more
      await place(bob.page, 'system');
      await expect(bob.page.locator('#health [data-health="warn"] b')).toHaveText('Gauntlet II is off for now');
      await expect(bob.page.locator('#health')).toContainText('Every other game plays as usual.');
      await expect(bob.page.locator('#health')).not.toContainText('isn’t answering');
      // put away: it stays away through a reload, and the record in System stays
      await place(host.page, 'home');
      await note.getByRole('button', { name: 'Dismiss' }).click();
      await expect(note).toBeHidden();
      await expect(host.page.locator('#top-title')).toBeFocused();
      // a blip is not news: out of touch and back again, it is still put away
      const back = await cutOff(host, bob);
      await expect(host.page.locator('html')).toHaveAttribute('data-link', 'reconnecting');
      await back();
      await expect(host.page.locator('html')).toHaveAttribute('data-link', 'ok', { timeout: 12_000 });
      await expect(note).toHaveAttribute('data-trouble', 'arcade');           // the trouble is still known
      await expect(note).toBeHidden();
      await host.page.reload();
      await expect(host.page.locator('html')).toHaveAttribute('data-ready', 'true');
      await expect(host.page.locator('#home-games')).toBeVisible();
      await expect(note).toBeHidden();
      await place(host.page, 'system');
      await expect(health).toHaveCount(1);
      // all well again: one quiet line, and nothing on Home
      expect((await request.post('/__test__/arcade/up')).status()).toBe(204);
      for (const p of [host, bob]) {
        await p.page.reload();
        await expect(p.page.locator('html')).toHaveAttribute('data-ready', 'true');
        await place(p.page, 'system');
        await expect(p.page.locator('#health [data-health]'), p.name).toHaveCount(1);
        await expect(p.page.locator('#health [data-health="ok"] b'), p.name).toHaveText(/Everything’s working|The Party box is working/);
      }
      // the same trouble, come back, is said again
      expect((await request.post('/__test__/arcade/down')).status()).toBe(204);
      await host.page.reload();
      await expect(host.page.locator('html')).toHaveAttribute('data-ready', 'true');
      await place(host.page, 'home');
      await expect(note).toBeVisible();
    } finally {
      await request.post('/__test__/arcade/up');
    }
  });

  test('the Host’s System never says all is well over a shelf that says a game is off', async ({ request }) => {
    try {
      expect((await request.post('/__test__/arcade/down')).status()).toBe(204);
      // the box's own account names no trouble (a kind it has no word for), yet the shelf marks a title off
      await host.context.route('**/party/api/status*', async (route) => {
        const response = await route.fetch();
        const body = await response.json();
        body.arcade = { ...(body.arcade || {}), ok: true, emulator_running: true, error: null };
        await route.fulfill({ response, json: body });
      });
      await host.page.reload();
      await expect(host.page.locator('html')).toHaveAttribute('data-ready', 'true');
      await expect(host.page.locator('#home-games')).toBeVisible();
      await expect(host.page.locator('#trouble')).toBeHidden();             // no notice: the account gives it nothing to say
      await place(host.page, 'system');
      await expect(host.page.locator('#health [data-health="warn"] b')).toHaveText('Gauntlet II is off for now');
      await expect(host.page.locator('#health [data-health="ok"]')).toHaveCount(0);
    } finally {
      await request.post('/__test__/arcade/up');
    }
  });

  test('a new Party says nothing about who took over hosting in the last one', async ({ request }) => {
    await goQuiet(host);
    await later(request, 50);
    await view(bob); await view(cleo);
    await later(request, 30);
    await expect(bob.page.locator('#host-now')).toBeVisible();
    await expect(cleo.page.locator('#party-state')).toContainText('Bob is hosting now');
    expect((await request.post('/__test__/party/reset')).status()).toBe(204);   // the box starts over; the phones stay where they are
    for (const p of [bob, cleo]) await expect(p.page.locator('#party-lede'), p.name).toHaveText('Two of you are here.', { timeout: 15_000 });
    for (const p of [bob, cleo]) {
      await expect(p.page.locator('#host-now'), p.name).toBeHidden();
      await expect(p.page.locator('#party-state'), p.name).not.toContainText('hosting now');
    }
  });

  test('when the host leaves, the next phone hosts at once and the party goes on', async () => {
    const leave = await post(host, 'leave', {});
    expect(leave.status()).toBe(200);
    await expect(bob.page.locator('#party-host')).toContainText('You’re the host');
    await expect(cleo.page.locator('#party-host')).toContainText('Bob is the host');
    // said to the phones that saw it happen; Ada left, so nobody "has been away"
    await expect(bob.page.locator('#host-now')).toHaveText(/You’re hosting now\s*You pick what the Party plays\./);
    await expect(cleo.page.locator('#party-state')).toHaveText('Bob is hosting now.');
    await startForEveryone(bob.page, 'expo');
    await expect(cleo.page).toHaveURL(/\/games\/expo\//);
    await endForEveryone(bob);
  });
});

test('the status endpoint names the running build for people and agents', async ({ request }) => {
  const res = await request.get('/party/api/status');
  expect(res.ok()).toBeTruthy();
  const doc = await res.json();
  expect(doc.schema).toBe('avrana.status/v0');
  expect(doc.contract.party_games).toBe('avrana.party-games/v0');
  expect(doc.party.checkout_sha).toMatch(/^[0-9a-f]{40}$/);
  expect(['ok', 'unknown']).toContain(doc.summary.state);
  expect(JSON.stringify(doc)).not.toMatch(/token|privkey|cookie/i);
});
