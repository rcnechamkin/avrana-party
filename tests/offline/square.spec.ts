import { test, expect, type Page } from '@playwright/test';
import { openGame, place, sideways, smallTargets } from '../lib/frame';
import { inReach, tabWalk } from '../lib/a11y';

/**
 * AVR-332 evidence: the shell on small SQUARE screens, such as an RG Rotate-like 720x720 physical
 * panel. Synthetic Chromium only: a square CSS viewport (480x480 at DPR 1.5, 360x360 at DPR 2) and,
 * for 200% text, `html { font-size: 200% !important }` injected after load (the same lever as the
 * "How to play" test in a11y.spec.ts; it scales every rem, it is not browser page zoom and not a
 * handheld's own text-size setting). No real handheld, no input hardware, no Safari: nothing here
 * proves a device. The keyboard stands in for d-pad and buttons only as Tab, Enter and Escape.
 *
 * A check that fails today carries `test.fail()` via KNOWN, naming the finding in
 * docs/findings/2026-10-14-square-viewport-evidence.md. No UI is changed by this file; when a
 * finding is fixed its test starts passing, `test.fail()` then reports it, and the entry goes.
 */

const CONDITIONS = [
  { name: '480x480', size: 480, dpr: 1.5, text: false },
  { name: '360x360', size: 360, dpr: 2, text: false },
  { name: '480x480 at 200% text', size: 480, dpr: 1.5, text: true },
  { name: '360x360 at 200% text', size: 360, dpr: 2, text: true },
];

/** `<condition>|<check>` -> finding id in the findings note. */
const KNOWN: Record<string, string> = {
  '360x360 at 200% text|room': 'F1',
};

const SCREENS: Array<[string, (page: Page) => Promise<unknown>]> = [
  ['Home', (p) => place(p, 'home')],
  ['Party', (p) => place(p, 'party')],
  ['Library', async (p) => { await place(p, 'library'); await p.locator('#game-search').fill(''); await expect(p.locator('#games [data-game]').first()).toBeVisible(); }],
  ['a game page', async (p) => { await place(p, 'library'); await openGame(p, 'bluff'); }],
  ['Me', (p) => place(p, 'me')],
];

const SHEETS: Array<[string, (page: Page) => Promise<string>]> = [
  ['Library view sheet', async (p) => { await place(p, 'library'); await p.locator('#lib-view').click(); await expect(p.locator('#lib-views')).toBeVisible(); return '#lib-views'; }],
  ['Library filter sheet', async (p) => { await place(p, 'library'); await p.locator('#lib-filter').click(); await expect(p.locator('#lib-filters')).toBeVisible(); return '#lib-filters'; }],
  ['How to play sheet', async (p) => { await place(p, 'library'); await (await openGame(p, 'bluff')).locator('[data-rules]').click(); await expect(p.locator('#rules')).toBeVisible(); return '#rules'; }],
];

/** Bluff has no rules file on the dev server; a long one (as a11y.spec.ts plants) gives the sheet. */
const LONG_RULES = { schema: 'avrana.onboarding/v0', premise: 'A long game.', facts: {}, ack: { key: 'test-long-rules', version: '1' },
  rules: Array.from({ length: 9 }, (_, i) => ({ title: `Part ${i + 1}`, points: ['One thing to know, said at some length so that it wraps on a phone.', 'Another thing.', 'And a third.'] })) };

async function open(page: Page, text: boolean) {
  await page.route('**/games/bluff/onboarding.json', (route) => route.fulfill({ json: LONG_RULES }));
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('#home-games')).toBeVisible();
  // the page's CSP refuses an injected <style>; the CSSOM route (as a11y.spec.ts uses) is allowed
  if (text) await page.evaluate(() => document.documentElement.style.setProperty('font-size', '200%', 'important'));
}

async function clear(page: Page) {
  if (await page.locator('dialog[open]').count()) await page.keyboard.press('Escape');
  await expect(page.locator('dialog[open]')).toHaveCount(0);
}

for (const c of CONDITIONS) {
  test.describe(`square ${c.name}`, () => {
    test.use({ viewport: { width: c.size, height: c.size }, deviceScaleFactor: c.dpr });
    test.beforeEach(({}, info) => { test.skip(info.project.name !== 'android-chromium', 'one phone project is enough for a viewport check'); });

    /** Mark the check as an expected failure when a finding is recorded for it. */
    const known = (key: string) => { const k = `${c.name}|${key}`; test.fail(k in KNOWN, KNOWN[k] || ''); };

    test('no horizontal overflow on any screen', async ({ page }, info) => {
      known('overflow');
      await open(page, c.text);
      const bad: string[] = [];
      for (const [name, go] of SCREENS) { await clear(page); await go(page); const w = await sideways(page); if (w > 0) bad.push(`${name}: ${w}px sideways`); }
      await page.screenshot({ path: info.outputPath('overflow.png') });
      expect(bad).toEqual([]);
    });

    test('the frame leaves room: nav inside the viewport and the scrolling middle keeps half the screen', async ({ page }, info) => {
      known('room');
      await open(page, c.text);
      const bad: string[] = [];
      for (const [name, go] of SCREENS) {
        await clear(page); await go(page);
        const r = await page.evaluate(() => {
          const box = (s: string) => document.querySelector(s)?.getBoundingClientRect();
          // Concept K (AVR-707): the page scrolls under the floating top edge and bar, so the room is
          // what lies between them, not the scroll container's own box (the whole screen).
          const nav = box('#nav'), top = box('#top');
          return { content: (nav?.top ?? window.innerHeight) - (top?.bottom ?? 0), navBottom: nav?.bottom ?? 0, navTop: nav?.top ?? 0, topH: top?.height ?? 0, vh: window.innerHeight };
        });
        if (r.navBottom > r.vh + 1 || r.navTop < 0) bad.push(`${name}: nav outside the viewport`);
        // 50% is an evidence threshold chosen for this note, not a product rule
        if (r.content < r.vh / 2) bad.push(`${name}: the scrolling middle is only ${Math.round(r.content)}px of ${r.vh} (top bar ${Math.round(r.topH)}px, nav ${Math.round(r.navBottom - r.navTop)}px)`);
      }
      await page.screenshot({ path: info.outputPath('room.png') });
      expect(bad).toEqual([]);
    });

    test('primary actions are reachable by scrolling and not covered', async ({ page }, info) => {
      known('primary');
      await open(page, c.text);
      const bad: string[] = [];
      const reachable = async (name: string, loc: ReturnType<Page['locator']>) => { bad.push(...await inReach(name, loc)); };
      await place(page, 'home');
      // Concept K (AVR-708): the stage is art, taller than a square screen at 200%; its action is what must be in reach
      await reachable('Home: the stage’s action', page.locator('#home-actions button').first());
      await place(page, 'library');
      await page.locator('#game-search').fill('');
      await reachable('Library: search', page.locator('#game-search'));
      await reachable('Library: a game', page.locator('#games [data-game="bluff"]'));
      const card = await openGame(page, 'bluff');
      await reachable('Game page: Play/Watch', card.getByRole('link', { name: /^(Play|Watch|Try anyway)$/ }).or(card.getByRole('button', { name: /^(Play|Watch|Start for everyone)$/ })));
      for (const nav of ['home', 'party', 'library', 'me']) await reachable(`Nav: ${nav}`, page.locator(`#nav a[data-go="${nav}"]`));
      await page.screenshot({ path: info.outputPath('primary.png') });
      expect(bad).toEqual([]);
    });

    test('hit targets are at least 44 CSS px on every screen', async ({ page }, info) => {
      known('targets');
      await open(page, c.text);
      const bad: string[] = [];
      for (const [name, go] of SCREENS) {
        await clear(page); await go(page);
        for (const t of await smallTargets(page, '#main a, #main button, #main summary, #main input:not([type="range"]), #nav a')) bad.push(`${name}: ${t}`);
      }
      await page.screenshot({ path: info.outputPath('targets.png') });
      expect(bad).toEqual([]);
    });

    test('Tab reaches every control with a visible focus ring, on every screen', async ({ page }, info) => {
      known('tab');
      await open(page, c.text);
      const bad: string[] = [];
      for (const [name, go] of SCREENS) {
        await clear(page); await go(page);
        await page.locator('#top-title, #game-title').first().evaluate((el: HTMLElement) => { (document.activeElement as HTMLElement | null)?.blur(); el.ownerDocument.body.focus(); });
        const walk = await tabWalk(page);
        if (walk.stops < 4) bad.push(`${name}: Tab reached only ${walk.stops} stops`);
        bad.push(...walk.bad.map((l) => `${name}: ${l}`));
        const missed = await page.evaluate((keys) => [...document.querySelectorAll('#main a[href], #main button, #main input, #main summary, #nav a')]
          .filter((el) => el.getClientRects().length > 0 && !(el as HTMLButtonElement).disabled && !el.closest('[inert],[aria-hidden="true"]') && (el as HTMLElement).tabIndex >= 0)
          .map((el) => `${el.tagName.toLowerCase()}#${el.id || (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 24)}`)
          .filter((k) => !keys.includes(k)), walk.keys);
        if (missed.length) bad.push(`${name}: never reached by Tab (of ${walk.stops} stops): ${missed.slice(0, 5).join(', ')}`);
      }
      await page.screenshot({ path: info.outputPath('tab.png') });
      expect(bad).toEqual([]);
    });

    test('sheets: a button in view, Tab stays inside, Escape closes and returns focus', async ({ page }, info) => {
      known('sheets');
      await open(page, c.text);
      const bad: string[] = [];
      for (const [name, go] of SHEETS) {
        await clear(page);
        const sel = await go(page);
        await page.waitForTimeout(400);   // the sheet slides in
        const inView = await page.locator(sel).locator('button').evaluateAll((bs) => bs.filter((b) => b.getClientRects().length).some((b) => { const r = b.getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight; }));
        if (!inView) bad.push(`${name}: no button of the sheet is fully in view`);
        if (await sideways(page) > 0) bad.push(`${name}: sideways overflow`);
        for (let i = 0; i < 40; i++) {
          await page.keyboard.press('Tab');
          // focus on <body> is the browser's own chrome (a modal dialog wraps through it): fine.
          // Focus on a control of the page behind the sheet is a leak.
          const at = await page.evaluate((s) => { const a = document.activeElement; return !a || a === document.body || a.closest(s) ? '' : `${a.tagName.toLowerCase()}#${a.id}`; }, sel);
          if (at) { bad.push(`${name}: Tab left the sheet for ${at}`); break; }
        }
        await page.keyboard.press('Escape');
        if (await page.locator('dialog[open]').count()) bad.push(`${name}: Escape did not close it`);
        else if (await page.evaluate(() => !document.activeElement || document.activeElement === document.body)) bad.push(`${name}: focus was dropped on close`);
      }
      await page.screenshot({ path: info.outputPath('sheets.png') });
      expect(bad).toEqual([]);
    });
  });
}
