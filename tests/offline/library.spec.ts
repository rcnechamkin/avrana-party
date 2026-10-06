import { test, expect, type Page } from '@playwright/test';
import { openGame, place, sideways, smallTargets } from '../lib/frame';

/**
 * The Library and Home's shelves (AVR-285) against the simulated Party (Tier 2), on a phone with
 * no party behind it: the five real titles, four views, two real filters, and a cover that opens
 * the game's own page (AVR-286). What the size of a party does to the shelf is in tests/party/multi-client.spec.ts
 * (it needs a party); the arranging itself is in tests/offline/library.test.mjs.
 * Chromium at phone sizes: not a real phone (docs/TESTING.md, Tier 3).
 */
const ALL = ['bluff', 'expo', 'arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms'];
const VIEWS = ['medium', 'large', 'compact', 'list'] as const;
const CONTROLS = 'a, button, input, select, summary';

async function arcade(page: Page, mode: 'up' | 'down' | 'full') {
  expect((await page.request.post(`/__test__/arcade/${mode}`)).status()).toBe(204);
}

async function h264(page: Page, supported: boolean) {
  await page.addInitScript((ok) => {
    const orig = RTCRtpReceiver.getCapabilities.bind(RTCRtpReceiver);
    RTCRtpReceiver.getCapabilities = (kind: string) => {
      const caps = orig(kind) || { codecs: [], headerExtensions: [] };
      if (kind !== 'video') return caps;
      const others = caps.codecs.filter((c: { mimeType: string }) => !/h264/i.test(c.mimeType));
      return { ...caps, codecs: ok ? [...others, { mimeType: 'video/H264', clockRate: 90000 }] : others };
    };
  }, supported);
}

async function open(page: Page, where: 'home' | 'library' = 'library') {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  if (where === 'library') await place(page, 'library');
  await expect(page.locator('#games')).toHaveAttribute('aria-busy', 'false');
}

async function setView(page: Page, view: string) {
  await page.locator('#lib-view').click();
  await page.locator(`#view-choices [data-v="${view}"]`).click();
  await expect(page.locator('#lib-views')).toBeHidden();
  await expect(page.locator('#games')).toHaveAttribute('data-view', view);
}

async function setFilter(page: Page, { players, screen }: { players?: number; screen?: string }) {
  await page.locator('#lib-filter').click();
  if (players !== undefined) await page.locator(`#filter-players [data-players="${players}"]`).click();
  if (screen) await page.locator(`#filter-screens [data-screen="${screen}"]`).click();
}

const shown = (page: Page) => page.locator('#games [data-game]').evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.game));
const stored = (page: Page, key: string) => page.evaluate((k) => localStorage.getItem(k), key);

test.beforeEach(async ({ page }) => arcade(page, 'up'));

test('the Library lists the five real titles, with no invented facts on any of them', async ({ page }) => {
  await h264(page, true);
  await open(page);
  expect(await shown(page)).toEqual(ALL);
  await expect(page.locator('#game-count')).toHaveText('5 games');
  await expect(page.locator('#games h3')).toHaveText(['All games']);
  await expect(page.locator('#games .avrana-sec .meta')).toHaveText('5');
  const bluff = page.locator('#games [data-game="bluff"]');
  await expect(bluff).toHaveAccessibleName('BLUFF. 2–6 players. Phone only');
  await expect(bluff.locator('.seats')).toHaveText('2–6');
  await expect(page.locator('#games [data-game="ps1-worms"]')).toHaveAccessibleName('Worms Armageddon. 1–4 players. TV optional. Not installed');
  // no length, kind, rating or "quick start": the catalog says none of those
  await expect(page.locator('#view-library')).not.toContainText(/\bmin\b|minutes|Quick Start|★/i);
  // a title with no art of its own gets its kind icon on its own colour, never a made-up cover
  await expect(page.locator('#games [data-game="expo"] .avrana-cover img')).toHaveCount(0);
  await expect(page.locator('#games [data-game="expo"] .avrana-cover > svg')).toHaveCount(1);
  await expect(page.locator('#games [data-game="bluff"] .avrana-cover img')).toHaveAttribute('src', 'art/lan-bluff.svg');
});

test('four views: the choice is one tap, shows at once, and is kept on this phone', async ({ page }) => {
  await open(page);
  const button = page.locator('#lib-view'), shelf = page.locator('#games');
  await expect(shelf).toHaveAttribute('data-view', 'medium');                      // the default
  await expect(button).toHaveAccessibleName('View: medium grid');
  await button.click();
  const sheet = page.locator('#lib-views');
  await expect(sheet).toBeVisible();
  await expect(sheet).toHaveAccessibleName('View');
  await expect(sheet.getByRole('button', { pressed: true })).toHaveText('Medium grid');
  expect(await smallTargets(page, '#lib-views button')).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(sheet).toBeHidden();
  await expect(button).toBeFocused();                                              // focus comes back
  for (const view of ['large', 'compact', 'list', 'medium']) {
    await setView(page, view);
    await expect(button).toBeFocused();
    expect(await shown(page), view).toEqual(ALL);                                  // a view never changes what is listed
    expect(await stored(page, 'avrana-library-view')).toBe(view);
    if (view === 'list') await expect(page.locator('#games ul.avrana-rows > li')).toHaveCount(5);
    else await expect(page.locator(`#games ul.avrana-grid.${view} > li`)).toHaveCount(5);
  }
  await setView(page, 'list');
  await expect(button).toHaveAccessibleName('View: list');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(shelf).toHaveAttribute('data-view', 'list');                        // kept
  await expect(page.locator('#games .avrana-row')).toHaveCount(5);
  await expect(page.locator('#games .avrana-row').first()).toContainText('Claim anything. Get caught, lose a card.');
  await page.locator('#lib-view').click();
  await expect(page.locator('#lib-views').getByRole('button', { pressed: true })).toHaveText('List');
});

test('a stored view this build does not know is the medium grid, not a broken page', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('avrana-library-view', 'carousel'));
  await open(page);
  await expect(page.locator('#games')).toHaveAttribute('data-view', 'medium');
  expect(await shown(page)).toEqual(ALL);
});

test('what a title means on this phone is said the same way in all four views', async ({ page }) => {
  await h264(page, false);                               // the arcade cannot show on this phone
  await open(page);
  const notes = () => page.locator('#games [data-game]').evaluateAll((els) => els.map((el) => {
    const b = el as HTMLElement;
    return [b.dataset.game, b.dataset.note || '', b.querySelector('.warn, .f .no:last-child')?.textContent?.trim() || '',
      /\. (Not installed|Not on this phone|Off for now|Watch only on this phone)$/.exec(b.getAttribute('aria-label') || '')?.[1] || ''];
  }));
  const want = [['bluff', '', '', ''], ['expo', '', '', ''],
    ['arcade-gauntlet2', 'no', 'Not on this phone', 'Not on this phone'],
    ['ps1-bomberman', 'not_installed', 'Not installed', 'Not installed'],
    ['ps1-worms', 'not_installed', 'Not installed', 'Not installed']];
  for (const view of VIEWS) {
    if (view !== 'medium') await setView(page, view);
    expect(await notes(), view).toEqual(want);
    // an icon goes with the words: the state is never colour alone
    await expect(page.locator('#games [data-game="arcade-gauntlet2"] :is(.warn, .f .no) svg').last(), view).toBeVisible();
  }
  // and the opened game agrees with its cover
  const card = await openGame(page, 'arcade-gauntlet2');
  await expect(card).toHaveAttribute('data-outcome', 'unavailable');
  await expect(card).toContainText('Not on this phone');
});

test('a title that is off says so in every view, and stops saying so when it is back', async ({ page }) => {
  await h264(page, true);
  await arcade(page, 'down');
  await open(page);
  const tile = page.locator('#games [data-game="arcade-gauntlet2"]');
  for (const view of VIEWS) {
    if (view !== 'medium') await setView(page, view);
    await expect(tile, view).toHaveAttribute('data-note', 'off');
    await expect(tile, view).toContainText('Off for now');
    await expect(tile, view).toHaveAccessibleName(/\. Off for now$/);
  }
  expect(await shown(page)).toEqual(ALL);                                          // off is not hidden
  await arcade(page, 'up');
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await expect(tile).not.toHaveAttribute('data-note', /.+/);
  await expect(tile).not.toContainText('Off for now');
});

test('no answer is not "off": a phone that cannot ask does not blame the games', async ({ page }) => {
  await h264(page, true);
  await page.route('**/arcade/stats', (route) => route.abort());          // out of range, not a game that is down
  await page.route('**/api/games', (route) => route.abort());
  await open(page);
  expect(await shown(page)).toEqual(ALL);
  for (const id of ['bluff', 'expo', 'arcade-gauntlet2']) {
    await expect(page.locator(`#games [data-game="${id}"]`), id).not.toHaveAttribute('data-note', /.+/);
    await expect(page.locator(`#games [data-game="${id}"]`), id).not.toContainText('Off for now');
  }
  await expect(page.locator('#games [data-game="ps1-worms"]')).toHaveAttribute('data-note', 'not_installed');   // that much is known
  // the opened game is as careful as it has always been: nothing is offered that cannot be reached
  await expect((await openGame(page, 'arcade-gauntlet2')).getByRole('button', { name: 'Play' })).toBeDisabled();
});

test('an answer that is not the game list is an answer: those games are off, and say so', async ({ page }) => {
  await page.route('**/api/games', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<h1>Sign in to Wi-Fi</h1>' }));
  await open(page);
  for (const id of ['bluff', 'expo']) await expect(page.locator(`#games [data-game="${id}"]`), id).toHaveAttribute('data-note', 'off');
  await page.unroute('**/api/games');
  await page.route('**/api/games', (route) => route.fulfill({ status: 502, body: 'bad gateway' }));
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  for (const id of ['bluff', 'expo']) await expect(page.locator(`#games [data-game="${id}"]`), id).toContainText('Off for now');
});

test('filters: the button, the sheet, the heading, the count and the hidden line all agree', async ({ page }) => {
  await open(page);
  const button = page.locator('#lib-filter'), badge = page.locator('#lib-filter-count'), sheet = page.locator('#lib-filters');
  await expect(button).toHaveAccessibleName('Filters');
  await expect(badge).toBeHidden();
  await button.click();
  await expect(sheet).toBeVisible();
  await expect(sheet).toHaveAccessibleName('Filters');
  await expect(page.locator('#filters-show')).toHaveText('Show 5 games');
  await expect(page.locator('#filter-players').getByRole('button', { pressed: true })).toHaveText('Any');
  await expect(page.locator('#filter-screens').getByRole('button', { pressed: true })).toHaveText('Any');
  // only what the catalog really says: how many play, and where it is seen
  await expect(sheet.locator('h3')).toHaveText(['Players', 'Screens']);
  expect(await smallTargets(page, '#lib-filters button')).toEqual([]);
  expect(await sideways(page)).toBeLessThanOrEqual(0);

  await page.locator('#filter-players [data-players="4"]').click();
  await expect(page.locator('#filters-show')).toHaveText('Show 4 games');           // before the sheet is closed
  await expect(page.locator('#filter-players').getByRole('button', { pressed: true })).toHaveText('4');
  await page.locator('#filters-show').click();
  await expect(sheet).toBeHidden();
  await expect(button).toBeFocused();
  await expect(button).toHaveAccessibleName('Filters, 1 on: 4 players');
  await expect(badge).toHaveText('1');
  expect(await shown(page)).toEqual(['bluff', 'expo', 'ps1-bomberman', 'ps1-worms']);
  await expect(page.locator('#games h3')).toHaveText(['4 games for 4 players']);
  await expect(page.locator('#game-count')).toHaveText('4 games of 5');
  await expect(page.locator('#games .avrana-hid')).toContainText('1 game hidden by this filter.');

  await setFilter(page, { screen: 'phone' });                                       // a second filter narrows it further
  await expect(page.locator('#filters-show')).toHaveText('Show 2 games');
  await page.locator('#filters-close').click();
  await expect(button).toHaveAccessibleName('Filters, 2 on: 4 players, Phone only');
  await expect(badge).toHaveText('2');
  expect(await shown(page)).toEqual(['bluff', 'expo']);
  await expect(page.locator('#games h3')).toHaveText(['2 games for 4 players, Phone only']);
  await expect(page.locator('#games .avrana-hid')).toContainText('3 games hidden by these filters.');
  await setView(page, 'list');                                                      // the same in the list
  expect(await shown(page)).toEqual(['bluff', 'expo']);
  await expect(page.locator('#games h3')).toHaveText(['2 games for 4 players, Phone only']);

  await page.locator('#games .avrana-sec').getByRole('button', { name: 'Reset' }).click();
  expect(await shown(page)).toEqual(ALL);
  await expect(button).toBeFocused();                                               // not dropped on the floor
  await expect(button).toHaveAccessibleName('Filters');
  await expect(badge).toBeHidden();
  await expect(page.locator('#games .avrana-hid')).toHaveCount(0);
  await expect(page.locator('#game-count')).toHaveText('5 games');

  await setFilter(page, { players: 1 });
  await page.keyboard.press('Escape');
  await page.locator('#games .avrana-hid').getByRole('button', { name: 'Show all' }).click();
  expect(await shown(page)).toEqual(ALL);
  await setFilter(page, { players: 2, screen: 'tv_optional' });
  await page.locator('#filters-reset').click();                                     // Reset inside the sheet
  await expect(page.locator('#filters-show')).toHaveText('Show 5 games');
  await expect(page.locator('#filter-players').getByRole('button', { pressed: true })).toHaveText('Any');
  await page.mouse.click(180, 20);                                                  // a tap outside closes it
  await expect(sheet).toBeHidden();

  // filters are for now, not for ever: a reload starts with every game on the shelf
  await setFilter(page, { players: 6 });
  await page.keyboard.press('Escape');
  expect(await shown(page)).toEqual(['bluff']);
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('#games')).toHaveAttribute('aria-busy', 'false');
  expect(await shown(page)).toEqual(ALL);
});

test('nothing to show always says why and offers the way back', async ({ page }) => {
  await open(page);
  const blank = page.locator('#games .avrana-blank');
  await setFilter(page, { players: 6, screen: 'tv_required' });
  await expect(page.locator('#filters-show')).toHaveText('Show 0 games');
  await page.locator('#filters-show').click();
  await expect(blank).toHaveAttribute('data-empty', 'filters');
  await expect(blank).toContainText('No games match these filters');
  await expect(blank).toContainText('Room for 6 or more, Needs the TV');
  await expect(page.locator('#game-count')).toHaveText('No games match these filters');
  await blank.getByRole('button', { name: 'Reset filters' }).click();
  expect(await shown(page)).toEqual(ALL);
  await expect(page.locator('#lib-filter')).toBeFocused();

  await page.locator('#game-search').fill('chess');
  await expect(blank).toHaveAttribute('data-empty', 'search');
  await expect(blank).toContainText('Nothing matches “chess”');
  await expect(blank).toContainText('The Library has 5 games.');
  await blank.getByRole('button', { name: 'Clear search' }).click();
  await expect(page.locator('#game-search')).toHaveValue('');
  await expect(page.locator('#game-search')).toBeFocused();
  expect(await shown(page)).toEqual(ALL);
  await page.locator('#game-search').fill('dungeon');                               // a title's own sentence is searched
  expect(await shown(page)).toEqual(['arcade-gauntlet2']);
  await expect(page.locator('#games h3')).toHaveText(['Search results']);
  await expect(page.locator('#game-count')).toHaveText('1 game of 5');
  await page.locator('#game-search').fill('');

  const tab = (name: string) => page.locator('#game-views').getByRole('button', { name, exact: true });
  await tab('Favorites').click();
  await expect(blank).toHaveAttribute('data-empty', 'favorites');
  await expect(blank).toContainText('No favorites yet');
  await expect(blank).toContainText('Tap the heart on any game to keep it here.');
  await blank.getByRole('button', { name: 'See all games' }).click();
  await expect(tab('All')).toHaveAttribute('aria-pressed', 'true');
  await expect(tab('All')).toBeFocused();                                           // the button is gone; focus is not
  expect(await shown(page)).toEqual(ALL);
  await tab('Recent').click();
  await expect(blank).toHaveAttribute('data-empty', 'recent');
  await expect(blank).toContainText('Nothing played yet');
  await blank.getByRole('button', { name: 'See all games' }).click();
  expect(await shown(page)).toEqual(ALL);
  for (const view of ['list', 'compact']) {                                         // the same words whatever the view
    await setView(page, view);
    await tab('Favorites').click();
    await expect(blank, view).toContainText('No favorites yet');
    await tab('All').click();
  }
});

test('a favourite is kept with the heart, from the list or from the opened game, and focus stays on it', async ({ page }) => {
  await open(page);
  await setView(page, 'list');
  const heart = page.locator('#games [data-fav="expo"]');
  await expect(heart).toHaveAccessibleName('Add EXPO to favorites');
  await expect(heart).toHaveAttribute('aria-pressed', 'false');
  await heart.click();
  await expect(heart).toHaveAttribute('aria-pressed', 'true');
  await expect(heart).toHaveAccessibleName('Remove EXPO from favorites');
  await expect(heart).toBeFocused();
  expect(JSON.parse((await stored(page, 'lg-favorites')) || '[]')).toEqual(['avrana:expo']);     // the list the games have always used
  // from the opened game, in the list: the row behind is redrawn, and focus still comes back to it
  const card = await openGame(page, 'bluff');
  await card.getByRole('button', { name: 'Add BLUFF to favorites' }).click();
  await expect(card.getByRole('button', { name: 'Remove BLUFF from favorites' })).toBeFocused();
  await page.locator('#top-back').click();
  await expect(page.locator('#games [data-game="bluff"]')).toBeFocused();
  await page.locator('#game-views').getByRole('button', { name: 'Favorites', exact: true }).click();
  expect(await shown(page)).toEqual(['bluff', 'expo']);
  await expect(page.locator('#games h3')).toHaveText(['Favorites']);
  await page.locator('#games [data-fav="expo"]').click();                           // un-keeping it takes it off this shelf
  expect(await shown(page)).toEqual(['bluff']);
  await expect(page.locator('#game-views').getByRole('button', { name: 'Favorites', exact: true })).toBeFocused();   // its row is gone; focus is not
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await page.locator('#game-views').getByRole('button', { name: 'Favorites', exact: true }).click();
  expect(await shown(page)).toEqual(['bluff']);
});

test('a cover is a link to the game’s own page: its facts, one heading, and its own button', async ({ page }) => {
  await open(page);
  const tile = page.locator('#games [data-game="expo"]');
  await expect(tile).toHaveAttribute('href', '#game/expo');                          // a link, so the phone's Back returns
  await expect(tile).not.toHaveAttribute('aria-haspopup', /.*/);
  await tile.focus();
  await page.keyboard.press('Enter');                                               // by keyboard
  const card = page.locator('#game-detail[data-id="expo"]');
  await expect(card).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'game');
  await expect(page).toHaveTitle('EXPO · Avrana Party');
  await expect(page.locator('#game-title')).toHaveText('EXPO');
  await expect(page.locator('#game-title')).toBeFocused();                          // a move: focus goes to what the page is
  await expect(page.locator('h1:visible')).toHaveCount(1);                          // one heading names the page
  await expect(card).toHaveAccessibleName('EXPO');
  // the way back says where it goes; the bar keeps the place the page was opened from
  await expect(page.locator('#top-back')).toHaveAccessibleName('Library');
  await expect(page.locator('#nav a[aria-current="page"]')).toHaveAttribute('data-go', 'library');
  // the catalog's own facts, nothing invented
  await expect(card).toContainText('One crew. Every card matters.');
  await expect(card.locator('.avrana-game-facts')).toContainText('2–5 players');
  await expect(card.locator('.avrana-game-facts')).toContainText('Phone only');
  await expect(card).toContainText('Works on this phone');
  await expect(card.locator('[data-suits]')).toHaveCount(0);                        // no party here to suit
  await expect(card.getByRole('link', { name: 'Play' })).toHaveAttribute('href', '/games/expo/?avrana=1');   // today's own button
  await expect(card.getByRole('button', { name: 'Add EXPO to favorites' })).toHaveAttribute('aria-pressed', 'false');
  for (const word of ['Quick start', 'minutes', 'Suggest', 'Bring the Party in']) await expect(card).not.toContainText(word);
  expect(await smallTargets(page, `:is(#view-game, #top, #nav) :is(${CONTROLS})`)).toEqual([]);
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  // reading order: the art, the name, what it is, the facts, the button
  const order = await card.evaluate((el) => [...el.children].map((c) => c.id || c.className.split(' ')[0]));
  expect(order.slice(0, 4)).toEqual(['avrana-cover', 'game-title', 'avrana-premise', 'avrana-game-facts']);
  expect(order.indexOf('avrana-act')).toBeGreaterThan(order.indexOf('avrana-game-facts'));
});

test('a game’s rules arriving after its page opened do not take the focus or replace its sentence', async ({ page }) => {
  let answer: () => void = () => {};
  const held = new Promise<void>((resolve) => { answer = resolve; });
  await page.route('**/games/bluff/onboarding.json', async (route) => {
    await held;                                                                     // the game answers late
    await route.fulfill({ json: { schema: 'avrana.onboarding/v0', premise: 'A premise from the game.', rules: [{ title: 'Turns', points: ['Play a card.'] }] } });
  });
  let asked = 0;
  await page.route('**/arcade/onboarding.json', (route) => { asked += 1; return route.fulfill({ status: 404, body: '' }); });
  await open(page);
  const card = await openGame(page, 'bluff');
  await expect(page.locator('#game-title')).toBeFocused();
  await expect(card.locator('.avrana-premise')).toHaveText('Claim anything. Get caught, lose a card.');
  await expect(card.getByRole('button', { name: 'How to play' })).toHaveCount(0);
  answer();
  await expect(card.getByRole('button', { name: 'How to play' })).toBeVisible();
  await expect(page.locator('#game-title')).toBeFocused();                          // still on the name
  await expect(card.locator('.avrana-premise')).toHaveText('Claim anything. Get caught, lose a card.');   // the catalog's sentence stays
  await expect(card.locator('.avrana-about')).toHaveText('A premise from the game.');
  // the heart keeps focus too when a line comes and goes around it
  const heart = card.getByRole('button', { name: 'Add BLUFF to favorites' });
  await heart.click();
  await expect(card.getByRole('button', { name: 'Remove BLUFF from favorites' })).toBeFocused();
  // a title that is not served from /games/ is never asked for rules: nothing is sent to another service
  await openGame(page, 'arcade-gauntlet2');
  await page.waitForTimeout(300);
  expect(asked).toBe(0);
});

test('back from a game’s page returns to the same cover at the same scroll, however it is done', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 480 });                           // short enough for the list to scroll
  await open(page);
  await setView(page, 'list');
  const tile = page.locator('#games [data-game="ps1-worms"]'), content = page.locator('#content');
  const top = () => content.evaluate((el) => el.scrollTop);
  const backs: Array<[string, () => Promise<unknown>]> = [
    ['the way back in the top bar', () => page.locator('#top-back').click()],
    ['the phone’s Back', () => page.goBack()],
    ['the bar’s Library', () => page.locator('#nav a[data-go="library"]').click()],
    ['the keyboard', async () => { await page.locator('#top-back').focus(); await page.keyboard.press('Enter'); }],
  ];
  for (const [how, back] of backs) {
    await tile.scrollIntoViewIfNeeded();
    const was = await top();
    expect(was, how).toBeGreaterThan(0);
    await tile.click();
    await expect(page.locator('#game-detail[data-id="ps1-worms"]'), how).toBeVisible();
    expect(await top(), how).toBe(0);                                                // a new page starts at its top
    await back();
    await expect(page.locator('html'), how).toHaveAttribute('data-place', 'library');
    await expect(tile, how).toBeFocused();
    expect(Math.abs((await top()) - was), how).toBeLessThanOrEqual(1);
    expect(await page.evaluate(() => location.hash), how).toBe('#library');
  }
  // the phone's Forward returns to the game's page, which still knows where it came from
  await tile.click();
  await page.goBack();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'library');
  await page.goForward();
  await expect(page.locator('#game-detail[data-id="ps1-worms"]')).toBeVisible();
  await expect(page.locator('#top-back')).toHaveAccessibleName('Library');
  // a reload stays on the game's page, and Back still lands on its cover
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('#game-detail[data-id="ps1-worms"]')).toBeVisible();
  await page.locator('#top-back').click();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'library');
  await expect(tile).toBeFocused();
  // an address typed by hand has nowhere to return to: Back is a plain link to the Library
  await page.goto('/party/#game/expo');
  await expect(page.locator('#game-detail[data-id="expo"]')).toBeVisible();
  await page.evaluate(() => { location.hash = '#game/bluff'; });                     // and typed again, over another game
  await expect(page.locator('#game-detail[data-id="bluff"]')).toBeVisible();
  await expect(page.locator('#game-title')).toHaveText('BLUFF');
  await expect(page.locator('#top-back')).toHaveAttribute('href', '#library');
  await page.locator('#top-back').click();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'library');
  expect(await page.evaluate(() => location.hash)).toBe('#library');
  await expect(page.locator('#top-title')).toBeFocused();
  // a title that is not on the shelf is the Library, and the address says so
  await page.goto('/party/#game/no-such-game');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('html')).toHaveAttribute('data-place', 'library');
  expect(await page.evaluate(() => location.hash)).toBe('#library');
  await expect(page.locator('#game-detail > *')).toHaveCount(0);
  // from a game's page, the bar goes anywhere
  await page.locator('#games [data-game="bluff"]').click();
  await page.locator('#nav a[data-go="system"]').click();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'system');
  await expect(page.locator('#top-back')).toBeHidden();
  await expect(page.locator('#top-title')).toHaveText('System');
});

test('Home’s shelves: a lead title, the games, and what this phone played, all from the same list', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('wc-name', 'Robin'));         // a phone that has a name can play
  await open(page, 'home');
  const lead = page.locator('#home-lead [data-game]');
  await expect(page.locator('#home-games')).toBeVisible();
  await expect(lead).toHaveAttribute('data-game', 'bluff');                         // the first one that can be played
  await expect(lead).toHaveAccessibleName('BLUFF 2–6 players');
  await expect(page.locator('#home-great-h')).toHaveText('Games');                  // no party: nothing to be "great for"
  expect(await page.locator('#home-great [data-game]').evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.game)))
    .toEqual(['expo', 'arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms']);           // the lead is not repeated
  await expect(page.locator('#home-great [data-game="ps1-worms"]')).toContainText('Not installed');
  await expect(page.locator('#home-recent-sec')).toBeHidden();                      // nothing played here yet
  expect(await smallTargets(page, `#view-home :is(${CONTROLS})`)).toEqual([]);
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  // a cover on Home opens the same game the Library does, and focus comes back to it
  await lead.click();
  await expect(page.locator('#game-detail[data-id="bluff"]')).toBeVisible();
  await expect(page.locator('#top-back')).toHaveAccessibleName('Home');             // back to where it was opened from
  await expect(page.locator('#nav a[aria-current="page"]')).toHaveAttribute('data-go', 'home');
  await page.goBack();                                                              // and Back then Forward still says Home
  await page.goForward();
  await expect(page.locator('#game-detail[data-id="bluff"]')).toBeVisible();
  await expect(page.locator('#top-back')).toHaveAccessibleName('Home');
  await expect(page.locator('#nav a[aria-current="page"]')).toHaveAttribute('data-go', 'home');
  await page.locator('#top-back').click();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'home');
  await expect(lead).toBeFocused();
  await page.locator('#home-games').getByRole('link', { name: 'Library' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'library');
  // playing one is remembered on this phone, and Home then leads with it
  await (await openGame(page, 'arcade-gauntlet2')).getByRole('link', { name: 'Play' }).click();
  await expect(page).toHaveURL(/\/arcade\//);
  await open(page, 'home');
  await expect(lead).toHaveAttribute('data-game', 'arcade-gauntlet2');
  await expect(lead).toContainText('You played this last.');
  await expect(page.locator('#home-recent-sec')).toBeHidden();                      // the lead is not listed a second time
  await expect(page.locator('#home-great [data-game="arcade-gauntlet2"]')).toHaveCount(0);
  await place(page, 'library');
  await (await openGame(page, 'expo')).getByRole('link', { name: 'Play' }).click();
  await expect(page).toHaveURL(/\/games\/expo\//);
  await open(page, 'home');
  await expect(lead).toHaveAttribute('data-game', 'expo');
  await expect(page.locator('#home-recent-sec')).toBeVisible();
  expect(await page.locator('#home-recent [data-game]').evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.game)))
    .toEqual(['arcade-gauntlet2']);                                                 // what was played before that
  // a keyboard's focus ring on a rail's first cover is whole: the rail leaves it room
  const room = await page.locator('#home-great').evaluate((rail) => {
    const a = rail.getBoundingClientRect(), b = rail.querySelector('a')!.getBoundingClientRect();
    return [b.left - a.left, b.top - a.top];
  });
  for (const px of room) expect(px).toBeGreaterThanOrEqual(4);
  await place(page, 'library');
  await page.locator('#game-views').getByRole('button', { name: 'Recent', exact: true }).click();
  expect(await shown(page)).toEqual(['expo', 'arcade-gauntlet2']);                  // newest first
  await expect(page.locator('#games h3')).toHaveText(['Recently played']);
});

test('thumb-sized targets and nothing sideways in every view, at 360 px', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 640 });
  await open(page);
  for (const view of VIEWS) {
    if (view !== 'medium') await setView(page, view);
    expect(await smallTargets(page, `#view-library :is(${CONTROLS})`), view).toEqual([]);
    expect(await sideways(page), view).toBeLessThanOrEqual(0);
  }
  // and with a filter on: "Reset" and "Show all" are short words and still thumb-sized
  for (const view of ['list', 'medium']) {
    await setView(page, view);
    await setFilter(page, { players: 4 });
    await page.keyboard.press('Escape');
    await expect(page.locator('#games .avrana-hid')).toBeVisible();
    expect(await smallTargets(page, `#view-library :is(${CONTROLS})`), view + ', filtered').toEqual([]);
    expect(await sideways(page), view + ', filtered').toBeLessThanOrEqual(0);
    await page.locator('#games .avrana-sec').getByRole('button', { name: 'Reset' }).click();
  }
  // empty states too
  await page.locator('#game-views').getByRole('button', { name: 'Favorites', exact: true }).click();
  expect(await smallTargets(page, `#view-library :is(${CONTROLS})`), 'empty').toEqual([]);
});

test('the Library holds at 200% text on a small phone: every view, both sheets and an opened game', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 640 });
  await open(page);
  await page.evaluate(() => document.documentElement.style.setProperty('font-size', '200%'));
  const wide = (selector: string) => page.locator(selector).evaluate((el) => el.scrollWidth - el.clientWidth);
  for (const view of VIEWS) {
    if (view !== 'medium') await setView(page, view);
    expect(await sideways(page), view).toBeLessThanOrEqual(0);
    expect(await shown(page), view).toEqual(ALL);
    // every title can be reached by scrolling down, and its name is whole
    const last = page.locator('#games [data-game="ps1-worms"]');
    await last.scrollIntoViewIfNeeded();
    await expect(last, view).toBeInViewport();
    await expect(last.locator('.t'), view).toHaveText('Worms Armageddon');
  }
  await page.locator('#lib-filter').scrollIntoViewIfNeeded();
  await page.locator('#lib-filter').click();
  expect(await wide('#lib-filters')).toBeLessThanOrEqual(1);
  await page.locator('#filter-screens [data-screen="tv_required"]').scrollIntoViewIfNeeded();
  await expect(page.locator('#filter-screens [data-screen="tv_required"]')).toBeInViewport();
  await page.locator('#filters-show').scrollIntoViewIfNeeded();
  await expect(page.locator('#filters-show')).toBeInViewport();
  await page.keyboard.press('Escape');
  await page.locator('#lib-view').click();
  expect(await wide('#lib-views')).toBeLessThanOrEqual(1);
  await page.locator('#view-choices [data-v="list"]').scrollIntoViewIfNeeded();
  await expect(page.locator('#view-choices [data-v="list"]')).toBeInViewport();
  await page.keyboard.press('Escape');
  const card = await openGame(page, 'bluff');
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  await expect(page.locator('#top-back')).toBeInViewport();
  await expect(page.locator('#game-title')).toHaveText('BLUFF');
  for (const el of [card.getByRole('link', { name: 'Play' }), card.getByRole('button', { name: /favorites/ })]) {
    await el.scrollIntoViewIfNeeded();
    await expect(el).toBeInViewport();
  }
  expect(await smallTargets(page, `:is(#view-game, #top) :is(${CONTROLS})`)).toEqual([]);
  await place(page, 'home');
  expect(await sideways(page)).toBeLessThanOrEqual(0);
});

test('with reduced motion nothing in the Library animates', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await open(page);
  await page.locator('#lib-filter').click();
  const moving = await page.evaluate(() => [...document.querySelectorAll('#view-library *, dialog[open], dialog[open] *')]
    .filter((el) => { const s = getComputedStyle(el); return s.animationName !== 'none' || parseFloat(s.transitionDuration) > 0; })
    .map((el) => el.id || el.className.toString()));
  expect(moving).toEqual([]);
});

test('reading order: search, filters, view, the tabs, then the shelf; the skip link lands on the games', async ({ page }) => {
  await open(page);
  const order = await page.locator('#view-library').evaluate((root) =>
    [...root.querySelectorAll('input, button, a[data-game]')].filter((el) => el.getClientRects().length)
      .map((el) => el.id || (el as HTMLElement).dataset.view || (el as HTMLElement).dataset.game).slice(0, 8));
  expect(order).toEqual(['game-search', 'lib-filter', 'lib-view', 'all', 'favorites', 'recent', 'bluff', 'expo']);
  await page.locator('#game-search').focus();
  for (const want of ['lib-filter', 'lib-view']) {
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => document.activeElement?.id)).toBe(want);
  }
  // a visible focus mark on a cover
  await page.locator('#games [data-game="bluff"]').focus();
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Tab');
  const ring = await page.locator('#games [data-game="bluff"]').evaluate((el) => {
    const s = getComputedStyle(el); return s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2; });
  expect(ring).toBe(true);
  // the filter segments clip at their edge, so their ring is drawn inside them, where it shows
  await page.locator('#lib-filter').click();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Shift+Tab');
  const seg = await page.locator('#filter-players [data-players="0"]').evaluate((el) => {
    (el as HTMLElement).focus();
    const s = getComputedStyle(el);
    return { on: el.matches(':focus-visible'), style: s.outlineStyle, width: parseFloat(s.outlineWidth), offset: parseFloat(s.outlineOffset) };
  });
  expect(seg.on).toBe(true);
  expect(seg.style).not.toBe('none');
  expect(seg.width).toBeGreaterThanOrEqual(2);
  expect(seg.offset + seg.width).toBeLessThanOrEqual(0);                            // wholly inside the segment
  // the sheet's heading is the word, and the party's size is beside it, not part of its name
  await expect(page.locator('#lib-filters h3').first()).toHaveText('Players');
});
