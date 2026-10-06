import { test, expect, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { place, sideways, smallTargets, startForEveryone } from '../lib/frame';
import { faintEdges, lowContrast, outOfOrder, unnamed } from '../lib/a11y';

/**
 * ADR 0012 / AVR-225 (Tier 2): Limited Mode with a simulated second scheme. Real Chromium, the
 * real Party Core behind the dev server with its Limited listener. `limited.avrana.test` is a
 * plain-HTTP origin that is NOT a secure context (as http://10.42.0.1 is on the appliance), and
 * 127.0.0.1 stands for the Full Mode origin (a secure context, as https://party.avrana.net is).
 *
 * What this cannot show: a real expired certificate or a wrong clock, a phone's Private DNS or
 * Private Relay, Safari, the `Secure` flag (the dev server's Full Mode is plain HTTP on loopback)
 * and nginx's port-80 server. Those are Tier 3 and the owner's.
 */
const PORT = Number(process.env.AVRANA_DEV_PORT || 8181) + 1;      // the dev server with a real Party Core
const FULL = `http://127.0.0.1:${PORT}`;
const LIMITED = `http://limited.avrana.test:${PORT}`;
const OTHER = `http://party.avrana.test:${PORT}`;                  // another HTTP name for the same box

async function control(page: Page, path: string) {
  // Playwright's own client does not use the browser's resolver, so it talks to 127.0.0.1.
  expect((await page.request.post(`${FULL}/__test__/${path}`)).status()).toBe(204);
}

async function named(context: BrowserContext, name: string) {
  await context.addInitScript((n) => { try { localStorage.setItem('wc-name', n); } catch { /* no storage */ } }, name);
}

async function home(page: Page, origin: string) {
  await page.goto(`${origin}/party/`);
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
}

const person = (page: Page, name: string) => page.locator('#party-members li', { hasText: name });

test.beforeEach(async ({ page }) => {
  await control(page, 'party/reset');
  await control(page, 'full/up');
});
test.afterEach(async ({ page }) => { await control(page, 'full/up'); });

test('a phone on the plain-HTTP origin is in the party, in Limited Mode, and is told so', async ({ page, context }) => {
  await named(context, 'Lena');
  await home(page, LIMITED);
  expect(await page.evaluate(() => window.isSecureContext)).toBe(false);
  await expect(page.locator('html')).toHaveAttribute('data-mode', 'limited');
  await expect(page.locator('#status-text')).toHaveText('Connected in Limited Mode');
  await expect(page.locator('#secure')).toBeHidden();                       // never a padlock here
  const banner = page.locator('#limited');
  await expect(banner).toBeVisible();
  await expect(banner).toContainText('Limited Mode');
  await expect(banner).toContainText('not private');
  await expect(banner).toContainText('screen may dim');
  await expect(banner).toContainText('not saved on this phone');
  await expect(banner).toContainText('renews its certificate');
  await expect(banner.getByRole('link', { name: 'Check for the full version' })).toHaveAttribute('href', 'doorway/');
  // Home says it in full, so the mark in the top bar is not doubled there.
  const mark = page.locator('#limited-mark');
  await expect(mark).toBeHidden();
  // The same party model: present on its own, and the first one in is the host.
  await place(page, 'party');
  await expect(person(page, 'Lena (you)')).toBeVisible();
  await expect(person(page, 'Lena (you)').locator('.mode')).toHaveText('Limited');
  await expect(page.locator('#party-host')).toContainText('You’re the host');
  // Its identity is the Limited credential only: HttpOnly, not Secure, and never the device cookie.
  const cookies = await context.cookies(`${LIMITED}/party/`);
  expect(cookies.map((c) => c.name)).toEqual(['avrana_limited']);
  expect(cookies[0]).toMatchObject({ httpOnly: true, secure: false, sameSite: 'Lax', path: '/party/' });
  expect(await page.evaluate(() => document.cookie)).toBe('');
  // No offline copy on a plain-HTTP origin.
  expect(await page.evaluate(() => 'serviceWorker' in navigator)).toBe(false);
});

test('away from Home the mode stays marked: the mark opens the same words over the page, and gives the page back', async ({ page, context }) => {
  await named(context, 'Lena');
  await home(page, LIMITED);
  const mark = page.locator('#limited-mark'), sheet = page.locator('#about-limited');
  for (const name of ['party', 'library', 'system'] as const) {
    await place(page, name);
    await expect(mark, name).toBeVisible();
    await expect(mark).toHaveAccessibleName('Limited Mode on this phone. What this means');
    expect(await smallTargets(page, '#top button'), name).toEqual([]);
    expect(await sideways(page), name).toBeLessThanOrEqual(0);
  }
  await place(page, 'library');
  await page.locator('#game-search').fill('bluff');                         // something the page would lose on a reload
  await mark.click();
  await expect(sheet).toBeVisible();
  for (const fact of ['not private', 'screen may dim', 'not saved on this phone', 'renews its certificate'])
    await expect(sheet).toContainText(fact);
  await expect(sheet.getByRole('link', { name: 'Check for the full version' })).toHaveAttribute('href', 'doorway/');
  expect(await page.evaluate(() => document.activeElement?.closest('dialog')?.id)).toBe('about-limited');
  expect(await smallTargets(page, '#about-limited a, #about-limited button')).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(sheet).toBeHidden();
  await expect(mark).toBeFocused();                                         // focus returns to what opened it
  await expect(page.locator('html')).toHaveAttribute('data-place', 'library');
  await expect(page.locator('#game-search')).toHaveValue('bluff');          // the page underneath never moved
  await mark.click();
  await page.getByRole('button', { name: 'Done' }).click();
  await expect(sheet).toBeHidden();
  // back on Home the full notice is there and the mark is not
  await place(page, 'home');
  await expect(page.locator('#limited')).toBeVisible();
  await expect(mark).toBeHidden();
});

test('the notice on Home folds into the mark: said once in full, then always marked, and kept in System', async ({ page, context }) => {
  await named(context, 'Lena');
  await home(page, LIMITED);
  const banner = page.locator('#limited'), mark = page.locator('#limited-mark'), sheet = page.locator('#about-limited');
  const audit = async () => [...await lowContrast(page, '#main'), ...await faintEdges(page), ...await unnamed(page, '#main'), ...await outOfOrder(page)];
  await expect(banner).toBeVisible();
  await expect(mark).toBeHidden();                                          // never both at once
  const fold = banner.getByRole('button', { name: 'Fold this notice away' });
  expect(await smallTargets(page, '#limited a, #limited button')).toEqual([]);
  expect(await audit()).toEqual([]);
  await fold.focus();
  await page.keyboard.press('Enter');
  await expect(banner).toBeHidden();
  await expect(mark).toBeVisible();                                         // Home is now marked like every other page
  await expect(mark).toBeFocused();                                         // focus goes to what stands in for the notice
  await expect(page.locator('html')).toHaveAttribute('data-mode', 'limited');
  await expect(page.locator('#status-text')).toHaveText('Connected in Limited Mode');
  expect(await audit()).toEqual([]);
  // the mark gives the same words back over Home, with the way to the full version
  await mark.click();
  for (const fact of ['not private', 'screen may dim', 'not saved on this phone', 'renews its certificate'])
    await expect(sheet).toContainText(fact);
  await expect(sheet.getByRole('link', { name: 'Check for the full version' })).toHaveAttribute('href', 'doorway/');
  await page.keyboard.press('Escape');
  await expect(mark).toBeFocused();
  // System keeps the facts in full for as long as the phone is in Limited Mode, folded or not
  await place(page, 'system');
  const record = page.locator('#health [data-health="warn"]');
  await expect(record.locator('b')).toHaveText('This phone is in Limited Mode');
  for (const fact of ['not private', 'screen may dim', 'not saved on this phone', 'renews its certificate'])
    await expect(record).toContainText(fact);
  await expect(page.locator('#health [data-health="ok"]')).toHaveCount(0);  // "everything's working" is not said beside it
  expect(await audit()).toEqual([]);
  expect(await sideways(page)).toBeLessThanOrEqual(0);
  // everyone still sees how this phone reaches the Party
  await place(page, 'party');
  await expect(person(page, 'Lena (you)').locator('.mode')).toHaveText('Limited');
  // folded for this visit: a reload, and a game and back, keep it folded
  await place(page, 'home');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(banner).toBeHidden();
  await expect(mark).toBeVisible();
  // the next time the phone opens the Party in Limited Mode, it is told once more
  const again = await context.newPage();
  await home(again, LIMITED);
  await expect(again.locator('#limited')).toBeVisible();
  await expect(again.locator('#limited-mark')).toBeHidden();
  await again.close();
});

test('a phone that keeps nothing cannot fold the notice away: it stays said in full', async ({ page, context }) => {
  await context.addInitScript(() => {
    const deny = () => { throw new DOMException('denied', 'SecurityError'); };
    Object.defineProperty(window, 'sessionStorage', { configurable: true, get: deny });
  });
  await named(context, 'Lena');
  await home(page, LIMITED);
  await page.locator('#limited-fold').click();
  await expect(page.locator('#limited')).toBeVisible();                     // never hidden with nothing in its place
  await expect(page.locator('#limited-mark')).toBeHidden();
});

async function secondPhone(browser: Browser, name: string) {
  const context = await browser.newContext();
  await named(context, name);
  return { context, page: await context.newPage() };
}

test('one party in two modes: each phone sees who is in Limited Mode, and only the Limited phone gets the banner', async ({ page, context, browser }) => {
  await named(context, 'Lena');
  await home(page, LIMITED);
  await place(page, 'party');
  await expect(person(page, 'Lena (you)')).toBeVisible();
  const fay = await secondPhone(browser, 'Fay');
  try {
    await home(fay.page, FULL);
    await expect(fay.page.locator('html')).toHaveAttribute('data-mode', 'full');
    await expect(fay.page.locator('#limited')).toBeHidden();
    await place(fay.page, 'party');
    await expect(fay.page.locator('#limited-mark')).toBeHidden();             // a Full Mode phone is never marked
    await expect(fay.page.locator('#status-text')).toHaveText('Connected to the party');
    await expect(person(fay.page, 'Fay (you)')).toBeVisible();
    await expect(person(fay.page, 'Fay (you)').locator('.mode')).toHaveCount(0);
    await expect(person(fay.page, 'Lena').locator('.mode')).toHaveText('Limited');
    await expect(fay.page.locator('#party-host')).toContainText('Lena is the host');   // a Limited host who is here stays host
    // and the Limited phone sees the Full Mode member arrive
    await expect(person(page, 'Fay')).toBeVisible();
    await expect(person(page, 'Fay').locator('.mode')).toHaveCount(0);
    // the drawer says the same of everyone, in words
    await fay.page.locator('#hud').click();
    await fay.page.getByRole('button', { name: 'People', exact: true }).click();
    await expect(fay.page.locator('#social-people li', { hasText: 'Lena' }).locator('.mode')).toHaveText('Limited');
    await expect(fay.page.locator('#social-people li', { hasText: 'Fay (you)' }).locator('.mode')).toHaveCount(0);
    await fay.page.keyboard.press('Escape');
    // the two credentials never cross: the Full phone holds no Limited cookie and the reverse
    expect((await fay.context.cookies(`${FULL}/party/`)).map((c) => c.name)).toEqual(['avrana_device']);
    expect((await context.cookies(`${LIMITED}/party/`)).map((c) => c.name)).toEqual(['avrana_limited']);
  } finally {
    await fay.context.close();
  }
});

test('on a briefing the mark opens the explanation over it, with no way off the page, and gives the briefing back', async ({ page, context, browser }) => {
  await named(context, 'Lena');
  await page.setViewportSize({ width: 360, height: 500 });                    // short: the dock un-pins and the whole briefing scrolls
  await home(page, LIMITED);
  await expect(page.locator('#party-members')).toContainText('Lena (you)');
  const fay = await secondPhone(browser, 'Fay');
  try {
    await home(fay.page, FULL);
    await expect(page.locator('#party-members li')).toHaveCount(2);
    await startForEveryone(page, 'bluff');                                    // Lena hosts: a Limited phone can
    for (const p of [page, fay.page]) await expect(p.locator('#scene')).toBeVisible();
    const mark = page.locator('#limited-mark'), sheet = page.locator('#about-limited');
    await expect(fay.page.locator('#limited-mark')).toBeHidden();             // a Full Mode phone is never marked
    await expect(mark).toBeVisible();                                         // the briefing has no Home to say it on
    await expect(mark).toHaveAccessibleName('Limited Mode on this phone. What this means');
    expect(await smallTargets(page, '#top button')).toEqual([]);
    expect(await sideways(page)).toBeLessThanOrEqual(0);
    await page.locator('#choose-watch').click();
    await expect(page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
    const scroll = (to?: number) => page.evaluate((y) => {
      const all = document.getElementById('scene')!, mid = document.getElementById('scene-scroll')!;
      const el = all.scrollHeight > all.clientHeight + 1 ? all : mid;
      if (typeof y === 'number') el.scrollTop = y;
      return Math.round(el.scrollTop);
    }, to);
    await scroll(80);
    const was = await scroll();
    expect(was).toBeGreaterThan(0);
    const closers: Array<[string, () => Promise<unknown>]> = [
      ['Escape', () => page.keyboard.press('Escape')],
      ['Close', () => page.locator('#about-close').click()],
      ['Done', () => page.getByRole('button', { name: 'Done' }).click()],
      ['a tap outside', () => page.mouse.click(180, 12)],
    ];
    for (const [how, close] of closers) {
      await mark.click();
      await expect(sheet, how).toBeVisible();
      for (const fact of ['not private', 'screen may dim', 'renews its certificate']) await expect(sheet, how).toContainText(fact);
      await expect(sheet.getByRole('link'), how).toHaveCount(0);              // nothing here leaves the briefing
      await expect(page.locator('#about-leave'), how).toBeHidden();
      expect(await page.evaluate(() => document.activeElement?.closest('dialog')?.id), how).toBe('about-limited');
      expect(await page.evaluate(() => { const b = document.getElementById('choose-play')!; b.focus(); return document.activeElement === b; }), how).toBe(false);
      expect(await smallTargets(page, '#about-limited button'), how).toEqual([]);
      await close();
      await expect(sheet, how).toBeHidden();
      await expect(page.locator('#scene'), how).toBeVisible();
      await expect(mark, how).toBeFocused();                                  // focus returns to what opened it
      expect(await scroll(), how).toBe(was);                                  // the briefing never moved
      await expect(page.locator('#choose-watch'), how).toHaveAttribute('aria-pressed', 'true');
    }
    // the people, over the same briefing, say who is in Limited Mode in words
    await fay.page.locator('#hud').click();
    await expect(fay.page.locator('#social-people li', { hasText: 'Lena' }).locator('.mode')).toHaveText('Limited');
    await expect(fay.page.locator('#social-tabs')).toBeHidden();
    // the sheet is open when the Party moves: it closes, and at home it has its way out again
    await mark.click();
    await expect(sheet).toBeVisible();
    await page.keyboard.press('Escape');
    await fay.page.keyboard.press('Escape');
    await mark.click();
    await fay.page.locator('#hud').click();
    // (the Host's own call, from her page: Playwright's client cannot resolve the Limited name)
    expect(await page.evaluate(async () => {
      const version = (await (await fetch('/party/api/state')).json()).version;
      return (await fetch('/party/api/session/end', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ if_version: version }) })).status;
    })).toBe(200);
    await expect(page.locator('#scene')).toBeHidden();
    await expect(sheet).toBeHidden();
    await expect(fay.page.locator('#social')).toBeHidden();
    await expect(page.locator('html')).toHaveAttribute('data-place', 'game');  // where Lena started it from
    await expect(mark).toBeVisible();
    await mark.click();
    await expect(sheet.getByRole('link', { name: 'Check for the full version' })).toHaveAttribute('href', 'doorway/');
  } finally {
    await fay.context.close();
  }
});

test('the same phone on the other origin is a new member: nothing carries across a mode switch', async ({ page, context }) => {
  await named(context, 'Lena');
  await home(page, LIMITED);
  await place(page, 'party');
  await expect(person(page, 'Lena (you)')).toBeVisible();
  await home(page, FULL);
  await expect(page.locator('#limited')).toBeHidden();
  await place(page, 'party');
  // Joined again as a new device: the earlier member still holds the name, so this one is "Lena 2".
  await expect(person(page, 'Lena 2 (you)')).toBeVisible();
  await expect(page.locator('#party-members li')).toHaveCount(2);           // the Limited member is still listed
  await expect(page.locator('#party-members li .mode')).toHaveCount(1);
});

test('the doorway opens the full version when it works', async ({ page }) => {
  await page.goto(`${LIMITED}/party/doorway/`);
  await page.waitForURL(`${FULL}/party/`);
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('#limited')).toBeHidden();
});

test('the doorway opens Limited Mode on the canonical origin when the full version does not answer', async ({ page }) => {
  await control(page, 'full/down');
  // from any HTTP name of the box, a phone lands on the one canonical Limited origin (ADR 0012 D1)
  for (const start of [LIMITED, OTHER]) {
    await page.goto(`${start}/party/doorway/`);
    await page.waitForURL(`${LIMITED}/party/`);
    await expect(page.locator('html')).toHaveAttribute('data-ready', 'true');
    await expect(page.locator('#limited')).toBeVisible();
  }
});

test('the doorway takes no destination from its address', async ({ page }) => {
  await control(page, 'full/down');
  await page.goto(`${LIMITED}/party/doorway/?limited=http://evil.test/&full=http://evil.test/#http://evil.test/`);
  await page.waitForURL(`${LIMITED}/party/`);
});
