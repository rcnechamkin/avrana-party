import { test, expect, type Page } from '@playwright/test';
import { openGame, place } from '../lib/frame';
import { faintEdges, focusWalk, lowContrast, moving, outline, outOfOrder, unnamed } from '../lib/a11y';

/**
 * The accessibility pass over the shell (UX/UI redesign PR 1.4, docs/design/ACCESSIBILITY.md):
 * every screen a phone reaches without a Party, checked the same way. The screens that need a
 * Party (the briefing, the drawer, the notices) are walked in tests/party/a11y.spec.ts, and
 * Limited Mode's in limited.spec.ts. Chromium at phone sizes: this is not VoiceOver or TalkBack,
 * not Safari, and not a phone's own text size or contrast setting.
 */

async function open(page: Page) {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('#home-games')).toBeVisible();
}

/** Put the page back to a plain place: nothing open over it, no search typed. */
async function clear(page: Page) {
  if (await page.locator('dialog[open]').count()) await page.keyboard.press('Escape');
  await expect(page.locator('dialog[open]')).toHaveCount(0);
}

/** Every screen of the shell without a Party, and how a person gets to it. */
const SCREENS: Array<[string, (page: Page) => Promise<unknown>]> = [
  ['Home', (p) => place(p, 'home')],
  ['Party', (p) => place(p, 'party')],
  ['Party, the profile open', async (p) => { await place(p, 'party'); if (!(await p.locator('#profile-name').isVisible())) await p.locator('#player-chip').click(); await expect(p.locator('#profile-name')).toBeVisible(); }],
  ['Library', async (p) => { await place(p, 'library'); await p.locator('#game-search').fill(''); await expect(p.locator('#games [data-game]').first()).toBeVisible(); }],
  ['Library, as a list', async (p) => { await place(p, 'library'); await p.locator('#lib-view').click(); await p.locator('#view-choices [data-v="list"]').click(); await expect(p.locator('#games .avrana-row').first()).toBeVisible(); }],
  ['Library, the view sheet', async (p) => { await place(p, 'library'); await p.locator('#lib-view').click(); await expect(p.locator('#lib-views')).toBeVisible(); }],
  ['Library, the filter sheet', async (p) => { await place(p, 'library'); await p.locator('#lib-filter').click(); await p.locator('#filter-players [data-players="2"]').click(); await expect(p.locator('#lib-filters')).toBeVisible(); }],
  ['Library, nothing found', async (p) => { await place(p, 'library'); await p.locator('#filters-reset').evaluate((b: HTMLButtonElement) => b.click()); await p.locator('#game-search').fill('zzzz'); await expect(p.locator('#games [data-empty="search"]')).toBeVisible(); }],
  ['Library, no favorites', async (p) => { await place(p, 'library'); await p.locator('#game-search').fill(''); await p.locator('#game-views [data-view="favorites"]').click(); await expect(p.locator('#games [data-empty="favorites"]')).toBeVisible(); }],
  ['Library, nothing recent', async (p) => { await place(p, 'library'); await p.locator('#game-views [data-view="recent"]').click(); await expect(p.locator('#games [data-empty="recent"]')).toBeVisible(); }],
  ['Library, filters that leave nothing', async (p) => { await place(p, 'library'); await p.locator('#game-views [data-view="all"]').click(); await p.locator('#lib-filter').click(); await p.locator('#filter-players [data-players="6"]').click(); await p.locator('#filter-screens [data-screen="tv_required"]').click(); await p.locator('#filters-show').click(); await expect(p.locator('#games [data-empty="filters"]')).toBeVisible(); }],
  ['a game’s page', async (p) => { await place(p, 'library'); await p.locator('#filters-reset').evaluate((b: HTMLButtonElement) => b.click()); await p.locator('#game-views [data-view="all"]').click(); await openGame(p, 'bluff'); }],
  ['a game that is not installed', async (p) => { await openGame(p, 'ps1-worms'); }],
  ['System', (p) => place(p, 'system')],
];

/** Run `check` on every screen in turn; collect what each one found, named by screen. */
async function everyScreen(page: Page, check: (root: string, name: string) => Promise<string[]>) {
  const found: string[] = [];
  for (const [name, goThere] of SCREENS) {
    await clear(page);
    await goThere(page);
    const root = (await page.locator('dialog[open]').count()) ? 'dialog[open]' : '#main';
    for (const line of await check(root, name)) found.push(`${name} · ${line}`);
  }
  await clear(page);
  return found;
}

test('the checks themselves: each one catches a fault planted for it', async ({ page }) => {
  await open(page);
  await place(page, 'system');
  const clean = async () => [...await lowContrast(page, '#main'), ...await faintEdges(page), ...await unnamed(page, '#main'), ...await outOfOrder(page)];
  expect(await clean()).toEqual([]);
  await page.evaluate(() => {
    const view = document.getElementById('view-system')!;
    const p = document.createElement('p'); p.id = 'planted-dim'; p.textContent = 'Hard to read'; p.style.color = '#4a4a4e';
    const icon = document.createElement('button'); icon.id = 'planted-nameless'; icon.type = 'button'; icon.className = 'btn btn-square'; icon.style.borderColor = '#2a2a2e';
    const tip = document.createElement('div'); tip.id = 'planted-label'; tip.setAttribute('aria-labelledby', 'planted-nothing'); tip.textContent = 'x';
    const up = document.createElement('button'); up.id = 'planted-above'; up.type = 'button'; up.className = 'btn'; up.textContent = 'Above'; Object.assign(up.style, { position: 'absolute', top: '4rem', left: '1rem' });
    const dark = document.createElement('button'); dark.id = 'planted-noring'; dark.type = 'button'; dark.className = 'btn'; dark.textContent = 'No ring'; dark.style.outline = 'none';
    view.append(p, icon, tip, up, dark);
  });
  // (planted through the style object: the page's own rules refuse a style written into markup)
  expect(await lowContrast(page, '#main')).toEqual([expect.stringContaining('"Hard to read"')]);
  expect(await faintEdges(page)).toEqual([expect.stringContaining('planted-nameless')]);
  const names = await unnamed(page, '#main');
  expect(names).toEqual(expect.arrayContaining([expect.stringContaining('no name: button#planted-nameless'), expect.stringContaining('aria-labelledby="planted-nothing"')]));
  expect(await outOfOrder(page)).toEqual([expect.stringContaining('planted-above is drawn above')]);
  expect((await focusWalk(page)).bad).toEqual([expect.stringContaining('planted-noring')]);   // of every stop, only the one with its ring taken away
  // motion: something that runs is seen, and the page's own rule stops it when less motion is asked for
  await page.evaluate(() => { document.getElementById('planted-dim')!.animate([{ opacity: 0.2 }, { opacity: 1 }], { duration: 60_000, iterations: Infinity }); });
  expect(await moving(page)).toEqual(expect.arrayContaining([expect.stringContaining('animation on')]));
  expect((await outline(page)).h1).toEqual(['System']);
});

test('contrast: every word, every mark and every outlined control stands out, on every screen', async ({ page }) => {
  await open(page);
  expect(await everyScreen(page, async (root) => [...await lowContrast(page, root), ...await faintEdges(page)])).toEqual([]);
});

test('names and skeleton: every control has a name, one main, one top heading, no skipped level', async ({ page }) => {
  await open(page);
  expect(await everyScreen(page, async (root) => {
    const bad = await unnamed(page, root), o = await outline(page);
    if (o.lang !== 'en') bad.push(`lang is "${o.lang}"`);
    if (!o.title.trim()) bad.push('no document title');
    if (o.unlabelledNavs) bad.push('a nav with no name');
    if (o.unlabelledDialogs.length) bad.push(`dialog with no name: ${o.unlabelledDialogs}`);
    if (root === '#main') {
      if (o.mains !== 1) bad.push(`${o.mains} main landmarks`);
      if (o.h1.length !== 1) bad.push(`top headings: ${JSON.stringify(o.h1)}`);
    }
    o.levels.forEach((level, i) => { if (i && level - o.levels[i - 1] > 1) bad.push(`heading level jumps from ${o.levels[i - 1]} to ${level}`); });
    return bad;
  })).toEqual([]);
});

test('reading order is visual order: nothing later in the page is drawn above what comes before it', async ({ page }) => {
  await open(page);
  expect(await everyScreen(page, (root) => outOfOrder(page, root === '#main' ? undefined : [root]))).toEqual([]);
});

test('the Tab key shows where it is at every stop, in every place and on a game’s page', async ({ page }) => {
  await open(page);
  for (const [name, goThere] of SCREENS.filter(([n]) => !/sheet|nothing|no favorites|list/.test(n))) {
    await clear(page);
    await goThere(page);
    await page.locator('#top-title, #game-title').first().evaluate((el: HTMLElement) => { (document.activeElement as HTMLElement | null)?.blur(); el.ownerDocument.body.focus(); });
    const walk = await focusWalk(page);
    expect(walk.stops, name).toBeGreaterThan(4);
    expect(walk.bad, name).toEqual([]);
  }
});

test('higher contrast asked for: text reaches 7:1 everywhere and the hairlines get stronger', async ({ page }) => {
  await open(page);
  const edge = () => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-control').trim());
  const before = await edge();
  await page.emulateMedia({ contrast: 'more' });
  expect(await edge()).not.toBe(before);
  expect(await everyScreen(page, (root) => lowContrast(page, root, 7))).toEqual([]);
});

test('reduced motion: nothing moves on any screen', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await open(page);
  expect(await everyScreen(page, () => moving(page))).toEqual([]);
});

test('state is never colour alone: what is chosen differs in weight, shape or a mark', async ({ page }) => {
  await open(page);
  const colourOnly = () => page.evaluate(() => {
    const bad: string[] = [];
    const look = (el: Element) => {
      const cs = getComputedStyle(el), mark = el.querySelector('.tick');
      const icon = el.querySelector('.avrana-icon');
      return [cs.fontWeight, getComputedStyle(el, '::after').content, getComputedStyle(el, '::before').content,
        mark ? getComputedStyle(mark).display + getComputedStyle(mark).visibility : '', icon ? getComputedStyle(icon).fill : ''].join('|');
    };
    const groups = new Map<Element, Element[]>();
    for (const el of document.querySelectorAll('[aria-pressed], #nav a')) {
      if (!el.getClientRects().length) continue;
      const key = el.parentElement!;
      groups.set(key, [...(groups.get(key) || []), el]);
    }
    for (const [group, els] of groups) {
      const on = els.filter((el) => el.getAttribute('aria-pressed') === 'true' || el.getAttribute('aria-current') === 'page');
      const offEls = els.filter((el) => !on.includes(el));
      if (!on.length || !offEls.length) continue;
      if (look(on[0]) === look(offEls[0])) bad.push(`${group.id || group.className}: the chosen one differs only in colour`);
    }
    return bad;
  });
  const found: string[] = [];
  for (const [name, goThere] of SCREENS) {
    await clear(page);
    await goThere(page);
    for (const line of await colourOnly()) found.push(`${name} · ${line}`);
  }
  expect(found).toEqual([]);
  // a kept favorite is a filled heart, not a brighter one
  await clear(page);
  await place(page, 'library');
  await page.locator('#game-views [data-view="all"]').click();
  await page.locator('#game-search').fill('');
  const card = await openGame(page, 'bluff');
  const heart = card.locator('[data-fav="bluff"]');
  const fill = () => heart.locator('svg').evaluate((el) => getComputedStyle(el).fill);
  const empty = await fill();
  await heart.click();
  await expect(card.locator('[data-fav="bluff"]')).toHaveAttribute('aria-pressed', 'true');
  expect(await fill()).not.toBe(empty);
});

test('How to play: however long the rules, "Got it" stays in reach and the rules scroll under it', async ({ page }) => {
  const long = { schema: 'avrana.onboarding/v0', premise: 'A long game.', facts: {}, ack: { key: 'test-long-rules', version: '1' },
    rules: Array.from({ length: 9 }, (_, i) => ({ title: `Part ${i + 1}`, points: ['One thing to know, said at some length so that it wraps on a phone.', 'Another thing.', 'And a third.'] })) };
  await page.route('**/games/bluff/onboarding.json', (route) => route.fulfill({ json: long }));
  await page.setViewportSize({ width: 360, height: 560 });
  await open(page);
  await place(page, 'library');
  const card = await openGame(page, 'bluff');
  await card.locator('[data-rules]').click();
  const ok = page.locator('#rules-ok');
  await expect(ok).toBeInViewport({ ratio: 1 });                           // on screen without scrolling (once the sheet has slid in)
  expect(await page.locator('#rules-body').evaluate((el) => el.scrollHeight > el.clientHeight + 20)).toBe(true);   // the rules are what scrolls
  expect(await page.locator('#rules-close').isVisible()).toBe(true);
  await page.evaluate(() => document.documentElement.style.setProperty('font-size', '200%'));
  await expect(ok).toBeInViewport({ ratio: 1 });
  await ok.click();
  await expect(page.locator('#rules')).toBeHidden();
});

test('"Choose your name" is a step the phone’s Back undoes, from Home and from a game’s page', async ({ page }) => {
  await open(page);
  await page.locator('#home-name').click();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'party');
  await expect(page.locator('#profile-name')).toBeFocused();
  await page.goBack();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'home');
  // from a game's page: Back returns to the game, whose own way back still leads where it says
  await page.locator('#home-lead [data-game]').click();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'game');
  await expect(page.locator('#top-back')).toHaveAccessibleName('Home');
  await page.locator('#game-detail').getByRole('link', { name: /^(Play|Watch|Try anyway)$/ }).click();   // no name yet: asked for one first
  await expect(page.locator('html')).toHaveAttribute('data-place', 'party');
  await expect(page.locator('#profile-note')).toContainText('Choose your Party name');
  await page.goBack();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'game');
  await expect(page.locator('#top-back')).toHaveAccessibleName('Home');
  await page.locator('#top-back').click();
  await expect(page.locator('html')).toHaveAttribute('data-place', 'home');
});
