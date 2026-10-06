import { test, expect, type Page } from '@playwright/test';
import { openGame, place, sideways, smallTargets, startForEveryone } from '../lib/frame';
import { faintEdges, focusWalk, lowContrast, moving, outline, outOfOrder, unnamed } from '../lib/a11y';
import { cutOff, goQuiet, later, phone, type Phone } from '../lib/phones';

/**
 * The accessibility pass over the screens that need a Party (UX/UI redesign PR 1.4): Home with
 * people on it, the drawer, a game's page as the Host and as a guest, the briefing, and every
 * state this pull request adds (the Host away, hosting passed on, this phone losing the box,
 * trouble on the box). The same checks as tests/offline/a11y.spec.ts, and what each state must
 * also keep: thumb-sized targets and nothing sideways. Each state is checked as it is drawn, then
 * as a phone that asks for less motion and more contrast draws it, then walked with Tab.
 * Chromium at phone sizes: not a screen reader, not Safari, not a phone's own settings.
 */

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
  expect((await request.post('/__test__/arcade/up')).status()).toBe(204);
});
test.afterEach(async ({ request }) => { await request.post('/__test__/arcade/up'); });

test.describe('three phones at one party', () => {
  let host: Phone, bob: Phone, cleo: Phone;
  const found: string[] = [];

  test.beforeEach(async ({ browser }) => {
    found.length = 0;
    host = await phone(browser, 'Ada');
    bob = await phone(browser, 'Bob');
    cleo = await phone(browser, 'Cleo');
  });
  test.afterEach(async () => { for (const p of [host, bob, cleo]) await p.context.close(); });

  /** Everything a browser can check, on what this phone shows now: as it is drawn; as a phone
   * that asks for more contrast and less motion draws it; and a walk with Tab, which must show
   * where it is at every stop and must reach each control named in `reach`. */
  async function audit(p: Phone, screen: string, reach: string[] = []) {
    const page: Page = p.page;
    const over = (await page.locator('dialog[open]').count()) > 0;
    const root = over ? 'dialog[open]' : '#main';
    const bad = [...await lowContrast(page, root), ...await faintEdges(page), ...await unnamed(page, root),
      ...await outOfOrder(page, over ? [root] : undefined)];
    const o = await outline(page);
    if (o.unlabelledDialogs.length) bad.push(`dialog with no name: ${o.unlabelledDialogs}`);
    if (!over && o.h1.length !== 1) bad.push(`top headings: ${JSON.stringify(o.h1)}`);
    o.levels.forEach((level, i) => { if (i && level - o.levels[i - 1] > 1) bad.push(`heading level jumps from ${o.levels[i - 1]} to ${level}`); });
    for (const t of await smallTargets(page, `${root} a, ${root} button, ${root} summary, ${root} input:not([type="range"])`)) bad.push(`small target: ${t}`);
    if (await sideways(page) > 0) bad.push('scrolls sideways');
    await page.emulateMedia({ contrast: 'more', reducedMotion: 'reduce' });
    for (const line of [...await lowContrast(page, root, 7), ...await faintEdges(page)]) bad.push(`more contrast asked for: ${line}`);
    for (const m of await moving(page)) bad.push(`less motion asked for: ${m}`);
    await page.emulateMedia({ contrast: null, reducedMotion: null });
    const walk = await focusWalk(page);
    bad.push(...walk.bad);
    for (const key of reach) if (!walk.keys.includes(key)) bad.push(`Tab never reached ${key} (it reached ${walk.keys.length} stops)`);
    for (const line of bad) found.push(`${screen} (${p.name}) · ${line}`);
  }
  const everyone = async (screen: string, phones = [host, bob, cleo], reach: string[] = []) => { for (const p of phones) await audit(p, screen, reach); };

  test('with people here: Home, the Party page, the drawer, a game’s page, the briefing and its rules', async () => {
    await everyone('Home');
    for (const p of [host, bob, cleo]) await place(p.page, 'party');
    await everyone('Party');
    for (const p of [bob, cleo]) { await p.page.locator('#hud').click(); await expect(p.page.locator('#social')).toBeVisible(); }
    await everyone('the drawer', [bob, cleo]);
    for (const p of [bob, cleo]) await p.page.keyboard.press('Escape');
    for (const p of [host, bob, cleo]) { await place(p.page, 'library'); await openGame(p.page, 'bluff'); }
    await everyone('a game’s page');
    await startForEveryone(host.page, 'bluff');
    for (const p of [host, bob, cleo]) await expect(p.page.locator('#scene')).toBeVisible();
    await everyone('the briefing, nobody has answered');
    await bob.page.locator('#choose-play').click();
    await cleo.page.locator('#choose-watch').click();
    await expect(host.page.locator('#scene-count')).toHaveText('1 playing · 1 watching');
    await everyone('the briefing, answers in');
    for (const p of [bob, cleo]) { await p.page.locator('#scene-rules').click(); await expect(p.page.locator('#rules')).toBeVisible(); await expect(p.page.locator('#rules-ok')).toBeInViewport({ ratio: 1 }); }
    await everyone('How to play', [bob, cleo]);
    expect(found).toEqual([]);
  });

  test('the Host away and hosting passed on: at home, on the Party page and on a briefing', async ({ request }) => {
    await goQuiet(host);
    await later(request, 50);
    for (const p of [bob, cleo]) await expect(p.page.locator('#party-state')).toBeVisible();
    await everyone('Home, the Host away', [bob, cleo]);
    for (const p of [bob, cleo]) await place(p.page, 'party');
    await everyone('Party, the Host away', [bob, cleo]);
    for (const p of [bob, cleo]) await place(p.page, 'home');
    await later(request, 30);
    await expect(bob.page.locator('#host-now')).toBeVisible();
    await expect(cleo.page.locator('#party-state')).toContainText('Bob is hosting now');
    await audit(bob, 'Home, hosting passed to this phone', ['button#host-now-x']);
    await audit(cleo, 'Home, hosting passed');
    // the same on a briefing: Bob hosts now, starts one, and goes quiet in turn
    await startForEveryone(bob.page, 'bluff');
    await expect(cleo.page.locator('#scene')).toBeVisible();
    await goQuiet(bob);
    await later(request, 50);
    await expect(cleo.page.locator('#scene-status')).toContainText('is away');
    await audit(cleo, 'the briefing, the Host away');
    await later(request, 30);
    await expect(cleo.page.locator('#scene-start')).toBeVisible();
    await audit(cleo, 'the briefing, hosting passed to this phone');
    expect(found).toEqual([]);
  });

  test('this phone losing the Party box, at home and on a briefing; trouble on the box for the Host', async ({ request }) => {
    for (const p of [bob, cleo]) await p.page.clock.install();
    const backBob = await cutOff(bob, host), backCleo = await cutOff(cleo, host);
    for (const p of [bob, cleo]) await expect(p.page.locator('html')).toHaveAttribute('data-link', 'reconnecting');
    await everyone('Home, reconnecting', [bob, cleo]);
    for (const p of [bob, cleo]) { await p.page.clock.fastForward(11_000); await expect(p.page.locator('html')).toHaveAttribute('data-link', 'lost'); }
    await everyone('Home, lost the box', [bob, cleo], ['button#net-retry']);
    await backBob(); await backCleo();
    await startForEveryone(host.page, 'bluff');
    for (const p of [bob, cleo]) await expect(p.page.locator('#scene')).toBeVisible({ timeout: 12_000 });
    await cutOff(bob, host); await cutOff(cleo, host);
    for (const p of [bob, cleo]) await expect(p.page.locator('#scene-net')).toBeVisible();
    await everyone('the briefing, reconnecting', [bob, cleo]);
    for (const p of [bob, cleo]) { await p.page.clock.fastForward(11_000); await expect(p.page.locator('#scene-lost')).toBeVisible(); }
    await everyone('the briefing, lost the box', [bob, cleo], ['button#scene-retry']);
    // trouble on the box: the Host's notice and System, a guest's System; then all well
    expect((await request.post('/__test__/party/reset')).status()).toBe(204);
    expect((await request.post('/__test__/arcade/down')).status()).toBe(204);
    for (const p of [host, bob]) { await p.context.unroute('**/party/api/state**'); await p.page.goto('/party/'); await expect(p.page.locator('html')).toHaveAttribute('data-ready', 'true'); }
    const hosting = (await host.page.locator('#party-host').innerText()).includes('You’re the host') ? host : bob, guest = hosting === host ? bob : host;
    await expect(hosting.page.locator('#trouble')).toBeVisible();
    await audit(hosting, 'Home, the Host’s notice', ['button#trouble-x']);
    for (const p of [hosting, guest]) { await place(p.page, 'system'); await expect(p.page.locator('#health [data-health="warn"]')).toBeVisible(); }
    await everyone('System, something is off', [hosting, guest]);
    expect((await request.post('/__test__/arcade/up')).status()).toBe(204);
    for (const p of [hosting, guest]) { await p.page.reload(); await expect(p.page.locator('#health [data-health="ok"]')).toBeVisible(); }
    await everyone('System, all well', [hosting, guest]);
    expect(found).toEqual([]);
  });
});
