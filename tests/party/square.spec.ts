import { test, expect, type Page } from '@playwright/test';
import { openGame, place, sideways, smallTargets, startForEveryone } from '../lib/frame';
import { inReach, tabWalk } from '../lib/a11y';
import { endForEveryone, phone, type Phone } from '../lib/phones';

/**
 * AVR-332 evidence, Party suite: the screens that need a Party, on small SQUARE screens (see
 * tests/offline/square.spec.ts for the method and its limits). Synthetic Chromium only: a square
 * CSS viewport, 200% text as `font-size: 200% !important` on <html>, Tab/Enter/Escape for a d-pad.
 * Not a handheld, not its input hardware, not Safari.
 *
 * Covered: the Host's game page, the briefing, the Play/Watch choice, How to play over it, and the
 * Host's controls while a round is on (Party Home's "going" panel, reached the way follow-origin.spec.ts
 * reaches it). A check that fails today carries `test.fail()` via KNOWN and a finding id from
 * docs/findings/2026-10-14-square-viewport-evidence.md. No UI is changed here.
 */

const CONDITIONS = [
  { name: '480x480', size: 480, dpr: 1.5, text: false },
  { name: '360x360', size: 360, dpr: 2, text: false },
  { name: '480x480 at 200% text', size: 480, dpr: 1.5, text: true },
  { name: '360x360 at 200% text', size: 360, dpr: 2, text: true },
];

/** condition name -> finding id in the findings note (none today: every check passes). */
const KNOWN: Record<string, string> = {};

const ONBOARDING = { schema: 'avrana.onboarding/v0', premise: 'A test premise: claim anything.', facts: { cards: 5 }, ack: { key: 'test-bluff-rules', version: '2' },
  rules: Array.from({ length: 6 }, (_, i) => ({ title: `Part ${i + 1}`, points: ['Play a card and claim what it is, said at some length so that it wraps.', 'You start with {cards} cards.'] })) };

test.beforeEach(async ({ request }, info) => {
  test.skip(info.project.name !== 'phones-chromium', 'one phone project is enough for a viewport check');
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
  expect((await request.post('/__test__/arcade/up')).status()).toBe(204);
});

for (const c of CONDITIONS) {
  test(`square ${c.name}: Host game page, briefing, Play/Watch, How to play, Host controls`, async ({ browser }, info) => {
    test.fail(c.name in KNOWN, KNOWN[c.name] || '');
    const options = { viewport: { width: c.size, height: c.size }, deviceScaleFactor: c.dpr, hasTouch: true, isMobile: true };
    const host: Phone = await phone(browser, 'Ada', options), bob: Phone = await phone(browser, 'Bob', options);
    const found: string[] = [];
    try {
      for (const p of [host, bob]) {
        await p.context.route('**/games/bluff/onboarding.json', (route) => route.fulfill({ json: ONBOARDING }));
        if (c.text) await p.page.evaluate(() => document.documentElement.style.setProperty('font-size', '200%', 'important'));
      }
      /** A sheet that is open on this phone: a button in view, Tab stays inside it, then it is closed
       * (`how`: Escape, or the button that acknowledges it) and focus is not dropped. */
      const sheet = async (p: Phone, screen: string, how: 'Escape' | 'Got it') => {
        await expect(p.page.locator('#rules')).toBeVisible();
        await p.page.waitForTimeout(400);   // slides in
        found.push(...(await inReach('Got it', p.page.locator('#rules-ok'))).map((l) => `${screen} (${p.name}) · ${l}`));
        if (await sideways(p.page) > 0) found.push(`${screen} (${p.name}) · scrolls sideways`);
        for (let i = 0; i < 40; i++) {
          await p.page.keyboard.press('Tab');
          const at = await p.page.evaluate(() => { const a = document.activeElement; return !a || a === document.body || a.closest('#rules') ? '' : `${a.tagName.toLowerCase()}#${a.id}`; });
          if (at) { found.push(`${screen} (${p.name}) · Tab left the sheet for ${at}`); break; }
        }
        if (how === 'Escape') await p.page.keyboard.press('Escape'); else await p.page.locator('#rules-ok').click();
        if (await p.page.locator('dialog[open]').count()) found.push(`${screen} (${p.name}) · ${how} did not close it`);
        else if (await p.page.evaluate(() => document.activeElement === document.body)) found.push(`${screen} (${p.name}) · focus was dropped on close`);
      };
      /** Everything this evidence slice asks of the screen a phone shows now. */
      const audit = async (p: Phone, screen: string, root: string, primary: Array<[string, string]>, reach: string[]) => {
        const page: Page = p.page, bad: string[] = [];
        if (await sideways(page) > 0) bad.push('scrolls sideways');
        for (const [name, sel] of primary) bad.push(...await inReach(name, page.locator(sel)));
        for (const t of await smallTargets(page, `${root} a, ${root} button, ${root} summary, ${root} input:not([type="range"])`)) bad.push(`small target: ${t}`);
        const walk = await tabWalk(page);
        bad.push(...walk.bad);
        for (const key of reach) if (!walk.keys.includes(key)) bad.push(`Tab never reached ${key} (${walk.stops} stops)`);
        for (const line of bad) found.push(`${screen} (${p.name}) · ${line}`);
      };

      // the Host's game page
      for (const p of [host, bob]) { await place(p.page, 'library'); await openGame(p.page, 'bluff'); }
      await audit(host, 'Host game page', '#main', [['Start for everyone', '#game-detail button:has-text("Start for everyone")']], []);
      await audit(bob, 'guest game page', '#main', [], []);

      // the briefing
      await startForEveryone(host.page, 'bluff');
      for (const p of [host, bob]) await expect(p.page.locator('#scene')).toBeVisible();
      const choice: Array<[string, string]> = [['Play this round', '#choose-play'], ['Watch this round', '#choose-watch']];
      // (Start is disabled, so not a Tab stop, until someone has answered: it is audited below)
      await audit(host, 'briefing', '#scene', choice, ['button#scene-rules', 'button#choose-play', 'button#choose-watch']);
      await audit(bob, 'briefing', '#scene', choice, ['button#scene-rules', 'button#choose-play', 'button#choose-watch']);

      // the Play/Watch choice: pressed, announced, and the Host can then start
      // Watch is one tap; Play asks a first-timer to read the rules first (Got it then makes the choice)
      await bob.page.locator('#choose-watch').click();
      await expect(bob.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
      for (const p of [bob, host]) {
        await p.page.locator('#choose-play').click();
        await sheet(p, 'first-time rules after Play', 'Got it');
        await expect(p.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'true');
      }
      await expect(host.page.locator('#scene-count')).toHaveText('2 playing · 0 watching');
      await expect(host.page.locator('#scene-start')).toBeEnabled();
      await audit(host, 'briefing, answers in', '#scene', [...choice, ['Start game', '#scene-start']], ['button#choose-play', 'button#choose-watch', 'button#scene-start']);

      // How to play, opened by hand over the briefing
      await bob.page.locator('#scene-rules').scrollIntoViewIfNeeded();
      await bob.page.locator('#scene-rules').click();
      await sheet(bob, 'How to play, opened', 'Escape');

      // the Host's controls while a round is on: the Host's way back to Party Home from the game
      await host.page.locator('#scene-start').click();
      await expect(host.page).toHaveURL(/\/games\/bluff\//);
      await host.page.goto('/party/');
      if (c.text) await host.page.evaluate(() => document.documentElement.style.setProperty('font-size', '200%', 'important'));
      await expect(host.page.locator('#going-host')).toBeVisible();
      await audit(host, 'Host controls during play', '#going', [['Return', '#going-return'], ['Bring everyone back', '#going-lobby']], ['button#going-return', 'button#going-lobby']);
      await host.page.locator('#going-lobby').click();
      await expect(host.page.locator('#going-confirm')).toBeVisible();
      await audit(host, 'Host controls, confirm ending', '#going', [['End the round', '#going-lobby-yes'], ['Keep playing', '#going-lobby-no']], ['button#going-lobby-yes', 'button#going-lobby-no']);
      await host.page.screenshot({ path: info.outputPath('host-controls.png') });
      await endForEveryone(host);
    } finally {
      await host.context.close(); await bob.context.close();
    }
    expect(found).toEqual([]);
  });
}
