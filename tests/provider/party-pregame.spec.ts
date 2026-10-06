import { test, expect as baseExpect, devices, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { place, startForEveryone } from '../lib/frame';

/**
 * ADR 0011, the console model, with BLUFF configured as in production (Party pregame on; harness
 * reset with ?pregame=1). One party, one place: a phone with a profile is in the party on its own;
 * the Party Host moves everyone (setup, round, end); a member's page is always where the party is,
 * whatever it opens or reloads. The setup is Party Home's own full-screen scene, not the table.
 * Real Party service, real games server, real BLUFF page, real /party/ shell, phone-sized (390x844).
 * Laptop only: TESTED here, not a phone measurement. Screenshots land in test-results/.
 */
const BASE = 'http://127.0.0.1:8183';
test.use({ baseURL: BASE });
test.beforeEach(({}, info) => test.skip(info.project.name !== 'android-size', 'runs once, phone-sized'));
test.setTimeout(180_000);
const expect = baseExpect.configure({ timeout: 20_000 });

const PHONE = devices['iPhone 13'];               // 390 x 844
type Phone = { context: BrowserContext; page: Page };
const IN_BLUFF = /\/games\/bluff\/\?avrana=1$/;
const AT_HOME = /\/party\/(#(home|party|library|system))?$/;   // the shell, in whichever of its places

function record() {
  const Native = window.WebSocket;
  const log = { rx: [] as any[] };
  (window as any).__avr = log;
  class Recorded extends Native {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      this.addEventListener('message', (e) => { try { log.rx.push(JSON.parse(e.data)); } catch {} });
    }
  }
  (window as any).WebSocket = Recorded;
}

async function phone(browser: Browser, briefed = true): Promise<Phone> {
  const { defaultBrowserType, ...device } = PHONE as any;
  const context = await browser.newContext({ ...device, baseURL: BASE, serviceWorkers: 'block' });
  if (briefed) await context.addInitScript(() => { try { localStorage.setItem('bluff-briefed', '1'); } catch { /* private */ } });
  const page = await context.newPage();
  await page.addInitScript(record);
  return { context, page };
}

/** The only gate: a profile. Saving it is being in the party (no Join button exists). */
async function arrive(page: Page, name: string) {
  await page.goto('/party/');
  await expect(page.locator('html')).toHaveAttribute('data-party', 'on');
  await place(page, 'party');
  await page.locator('#player-chip').click();
  await page.locator('#profile-name').fill(name);
  await page.getByRole('button', { name: 'Save profile' }).click();
  await expect(page.locator('#party-members')).toContainText(`${name} (you)`);
}

const rx = (page: Page) => page.evaluate(() => (window as any).__avr?.rx ?? []);
const welcomeOf = async (page: Page) => (await rx(page)).filter((m: any) => m.type === 'welcome').at(-1);
const lastGame = async (page: Page) => (await rx(page)).filter((m: any) => m.type === 'state' && m.game).at(-1)?.game;
const partyState = (page: Page) => page.evaluate(async () => (await fetch('/party/api/state', { cache: 'no-store' })).json());
const api = (page: Page, path: string, body: any) => page.evaluate(async ({ path, body }) => {
  const r = await fetch('/party/api/' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json() };
}, { path, body });

/** Phone layout: nothing wider than the screen, these controls fully on screen, none overlapping,
 * and no label spilling out of its button. */
async function assertPhoneLayout(page: Page, selectors: string[]) {
  const report = await page.evaluate((sels) => {
    const w = innerWidth, hgt = innerHeight;
    const boxes = sels.map((s) => {
      const el = document.querySelector(s) as HTMLElement | null;
      if (!el || el.hidden || !el.offsetParent) return { s, visible: false } as any;
      const r = el.getBoundingClientRect();
      return { s, visible: true, l: r.left, t: r.top, r: r.right, b: r.bottom,
        spills: el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1 };
    });
    const overlaps: string[] = [];
    const vis = boxes.filter((b: any) => b.visible);
    for (let i = 0; i < vis.length; i++) for (let j = i + 1; j < vis.length; j++) {
      const a = vis[i], b = vis[j];
      if (a.l < b.r - 1 && b.l < a.r - 1 && a.t < b.b - 1 && b.t < a.b - 1) overlaps.push(`${a.s} x ${b.s}`);
    }
    return { scroll: document.documentElement.scrollWidth - w, hgt, w, boxes, overlaps };
  }, selectors);
  expect(report.scroll, 'no horizontal scrolling').toBeLessThanOrEqual(0);
  expect(report.overlaps, 'no overlapping controls').toEqual([]);
  for (const b of report.boxes.filter((x: any) => x.visible)) {
    expect(b.l >= -1 && b.r <= report.w + 1, `${b.s} within the width`).toBe(true);
    expect(b.b <= report.hgt + 1, `${b.s} on screen without scrolling`).toBe(true);
    expect(b.spills, `${b.s} label fits`).toBe(false);
  }
}

async function setUp(browser: Browser, request: any, names: string[], briefed: boolean[] = []) {
  expect((await request.post('/__harness__/party/reset?pregame=1')).ok()).toBe(true);
  const phones: Phone[] = [];
  for (const [i, name] of names.entries()) {
    const p = await phone(browser, briefed[i] ?? true);
    await arrive(p.page, name);
    phones.push(p);
  }
  return phones;
}

async function pickBluff(host: Page, phones: Phone[]) {
  await startForEveryone(host, 'bluff');
  for (const p of phones) {
    await expect(p.page).toHaveURL(AT_HOME);
    await expect(p.page.locator('#scene')).toBeVisible();
    await expect(p.page.locator('#main')).toBeHidden();
  }
}

test('presence is automatic: a profile is membership, there is no Join, a reopened page is still in', async ({ browser, request }, info) => {
  const [ana] = await setUp(browser, request, ['Ana']);
  await ana.page.screenshot({ path: info.outputPath('home-390x844.png') });
  await expect(ana.page.getByRole('button', { name: /Join the party/ })).toHaveCount(0);
  await expect(ana.page.getByRole('button', { name: /Leave the party/ })).toHaveCount(0);
  await ana.page.reload();
  await expect(ana.page.locator('#party-members')).toContainText('Ana (you)');
  // a new party (Party Core restarted: nobody is a member any more): the profile rejoins alone
  await request.post('/__harness__/party/reset?pregame=1');
  await ana.page.reload();
  await expect(ana.page.locator('#party-members')).toContainText('Ana (you)');
  expect((await partyState(ana.page)).me.name).toBe('Ana');
  await ana.context.close();
});

test('the host picks BLUFF: a full-screen setup scene on every phone, host-only Start, then everyone is in the round', async ({ browser, request }, info) => {
  const phones = await setUp(browser, request, ['Ana', 'Ben', 'Cy'], [false, true, true]);
  const [ana, ben, cy] = phones;
  await pickBluff(ana.page, phones);
  // the scene: identity, premise, roster with Gaze avatars, the decision; no table behind it
  for (const p of phones) {
    await expect(p.page.locator('#scene-title')).toHaveText('BLUFF');
    await expect(p.page.locator('#scene-premise')).toContainText('secret roles');
    await expect(p.page.locator('#scene-roster li')).toHaveCount(3);
    await expect(p.page.locator('#scene-roster img[src*="gaze-"]')).toHaveCount(3);
    expect(await welcomeOf(p.page)).toBeUndefined();                 // no game socket, no table
  }
  await expect(ana.page.locator('#scene-host-name')).toHaveText('You’re the host');
  await expect(ben.page.locator('#scene-host-name')).toHaveText('Hosted by Ana');
  // only the host has Start; it says why it waits; followers see who they wait for, once
  await expect(ben.page.locator('#scene-start')).toBeHidden();
  await expect(ben.page.locator('#scene-status')).toHaveText('Waiting for Ana to start');
  await expect(ana.page.locator('#scene-start')).toBeDisabled();
  await expect(ana.page.locator('#scene-status')).toContainText('Waiting for Ana, Ben, Cy');
  await ana.page.screenshot({ path: info.outputPath('setup-host-390x844.png'), fullPage: true });
  await assertPhoneLayout(ana.page, ['#scene-title', '#scene-rules', '#choose-play', '#choose-watch', '#scene-start', '#scene-status']);
  let v = await partyState(ben.page);
  expect(await api(ben.page, 'session/start', { if_version: v.version })).toMatchObject({ status: 403, body: { error: 'not_host' } });

  // How to play: one sheet, in and out, and the setup is untouched
  await ben.page.locator('#scene-rules').click();
  await expect(ben.page.locator('#rules')).toBeVisible();
  await expect(ben.page.locator('#rules-body section')).toHaveCount(5);
  await ben.page.screenshot({ path: info.outputPath('rules-390x844.png') });
  await ben.page.locator('#rules-close').click();
  await expect(ben.page.locator('#rules')).toBeHidden();
  await expect(ben.page.locator('#scene')).toBeVisible();

  // a first-timer's Play asks for the rules first; "Got it, I'll play" is the Play
  await ana.page.locator('#choose-play').click();
  await expect(ana.page.locator('#rules')).toBeVisible();
  expect((await partyState(ana.page)).session.setup.mine).toBeNull();
  await ana.page.getByRole('button', { name: 'Got it, I’ll play' }).click();
  await expect(ana.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'true');
  await ben.page.locator('#choose-play').click();
  await cy.page.locator('#choose-watch').click();
  await expect(cy.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
  await expect(ana.page.getByRole('img', { name: 'Watching' })).toHaveCount(1);          // Cy's badge, in words for assistive tech
  await expect(ana.page.locator('#scene-start')).toBeEnabled();
  await cy.page.screenshot({ path: info.outputPath('setup-follower-390x844.png'), fullPage: true });
  await assertPhoneLayout(cy.page, ['#scene-title', '#scene-rules', '#choose-play', '#choose-watch', '#scene-status']);
  await ana.page.locator('#scene-start').click();

  // the host started: every phone is in the round; players are dealt; the spectator sees all
  for (const p of phones) await expect(p.page).toHaveURL(IN_BLUFF, { timeout: 30_000 });
  await expect.poll(async () => (await lastGame(ana.page))?.me?.cards?.length ?? 0, { timeout: 30_000 }).toBe(2);
  await expect.poll(async () => (await lastGame(ben.page))?.me?.cards?.length ?? 0).toBe(2);
  expect(await welcomeOf(cy.page)).toMatchObject({ watch: true, spectator: true });
  await expect.poll(async () => (await lastGame(cy.page))?.omniscient ?? false).toBe(true);
  const spectator = await lastGame(cy.page);
  expect(spectator.seats.map((s: any) => s.cards)).toEqual([(await lastGame(ana.page)).me.cards, (await lastGame(ben.page)).me.cards]);
  for (const p of [ana, ben]) {
    for (const m of (await rx(p.page)).filter((x: any) => x.type === 'state' && x.game)) {
      expect(m.game.seats.every((s: any) => !('cards' in s))).toBe(true);
    }
  }
  // the game owns the viewport: no Party bar, no Back to Party, no Party prose
  for (const p of phones) {
    await expect(p.page.locator('#avrana-navigation')).toBeHidden();
    await expect(p.page.locator(':is(a, button):visible', { hasText: 'Back to Party' })).toHaveCount(0);
    await expect(p.page.locator('body :visible', { hasText: /playing ·|watching ·|Setting up/ })).toHaveCount(0);
  }
  await expect(ana.page.locator('#party-end')).toBeVisible();            // the host's End, in the table
  await expect(ben.page.locator('#party-end')).toBeHidden();
  await ana.page.screenshot({ path: info.outputPath('round-host-390x844.png') });
  await assertPhoneLayout(ana.page, ['#rules', '#party-end', '#timer', '#history']);   // host chrome clear of the table's
  await cy.page.screenshot({ path: info.outputPath('round-spectator-390x844.png') });
  v = await partyState(cy.page);
  expect(await api(cy.page, 'session/choice', { choice: 'player' })).toMatchObject({ status: 409, body: { error: 'round_on' } });

  // a follower cannot leave the round: Party Home and other games bring it straight back
  await ben.page.goto('/party/');
  await expect(ben.page).toHaveURL(IN_BLUFF);
  await ben.page.goto('/games/backgammon/?avrana=1');
  await expect(ben.page).toHaveURL(IN_BLUFF);
  const pid = (await lastGame(ana.page)).seats[1].pid;
  await expect.poll(async () => (await welcomeOf(ben.page))?.pid).toBe(pid);          // same seat
  // reload: the same seat and hand
  await ana.page.reload();
  await expect.poll(async () => (await lastGame(ana.page))?.me?.cards?.length ?? 0).toBe(2);

  // the host ends it from the table: everyone goes home together
  await ana.page.locator('#party-end').click();
  await ana.page.locator('#confirm-yes').click();                       // the table's own confirmation
  for (const p of phones) {
    await expect(p.page).toHaveURL(AT_HOME);
    await expect(p.page.locator('#main')).toBeVisible();
  }
  for (const p of phones) await p.context.close();
});

test('too few players: Start stays off with the reason; a change of mind turns it on', async ({ browser, request }) => {
  const [ana, ben] = await setUp(browser, request, ['Ana', 'Ben']);
  await pickBluff(ana.page, [ana, ben]);
  await ana.page.locator('#choose-play').click();
  await ben.page.locator('#choose-watch').click();
  await expect(ana.page.locator('#scene-status')).toContainText('2 players needed');
  await expect(ana.page.locator('#scene-start')).toBeDisabled();
  const v = await partyState(ana.page);
  expect(await api(ana.page, 'session/start', { if_version: v.version })).toMatchObject({ status: 409, body: { error: 'player_count' } });
  await ben.page.locator('#choose-play').click();
  await expect(ana.page.locator('#scene-start')).toBeEnabled();
  await ana.context.close(); await ben.context.close();
});

test('a reopened or late phone lands where the party is: the setup scene, then the round', async ({ browser, request }) => {
  const [ana, ben] = await setUp(browser, request, ['Ana', 'Ben']);
  await pickBluff(ana.page, [ana, ben]);
  // Ben opens another game while the party sets up: straight back to the setup
  await ben.page.goto('/games/backgammon/?avrana=1');
  await expect(ben.page).toHaveURL(AT_HOME);
  await expect(ben.page.locator('#scene')).toBeVisible();
  await ana.page.locator('#choose-play').click();
  await ben.page.locator('#choose-play').click();
  // a late phone arrives during setup: it must choose too, on the same scene
  const cy = await phone(browser);
  await cy.page.goto('/party/');
  await cy.page.locator('#home-name').click();                         // Home asks a nameless phone for its name
  await expect(cy.page.locator('html')).toHaveAttribute('data-place', 'party');
  await cy.page.locator('#profile-name').fill('Cy');
  await cy.page.getByRole('button', { name: 'Save profile' }).click();  // the profile is presence
  await expect(cy.page.locator('#scene')).toBeVisible();              // and the party is here
  await expect(ana.page.locator('#scene-start')).toBeDisabled();
  await cy.page.locator('#choose-watch').click();
  await ana.page.locator('#scene-start').click();
  for (const p of [ana, ben, cy]) await expect(p.page).toHaveURL(IN_BLUFF, { timeout: 30_000 });
  // someone reopening Party Home mid-round is taken back into it
  const again = await ben.context.newPage();
  await again.goto('/party/');
  await expect(again).toHaveURL(IN_BLUFF);
  await ana.context.close(); await ben.context.close(); await cy.context.close();
});

test('the host can take the party back home from the setup', async ({ browser, request }) => {
  const [ana, ben] = await setUp(browser, request, ['Ana', 'Ben']);
  await pickBluff(ana.page, [ana, ben]);
  await expect(ben.page.locator('#scene-cancel')).toBeHidden();
  await ana.page.locator('#scene-cancel').click();
  for (const p of [ana, ben]) await expect(p.page.locator('#main')).toBeVisible();
  expect((await partyState(ben.page)).location.at).toBe('home');
  await ana.context.close(); await ben.context.close();
});

/** Play a round to its end: Ben leaves the game (his own forfeit), Ana takes Income until she wins. */
async function finishRound(ana: Page, ben: Page) {
  await ben.locator('#history').click();
  await ben.getByRole('button', { name: 'Leave game' }).click();
  await ben.locator('#confirm-yes').click();
  await ben.locator('#drawer-close').click();
  await expect.poll(async () => {
    const g = await lastGame(ana);
    if (g?.winner) return true;
    const income = ana.getByRole('button', { name: /Income/ });
    if (await income.isVisible() && await income.isEnabled()) await income.click().catch(() => {});
    return false;
  }, { timeout: 60_000, intervals: [500] }).toBe(true);
}

async function startRound(ana: Phone, ben: Phone) {
  await ana.page.locator('#choose-play').click();
  await ben.page.locator('#choose-play').click();
  await ana.page.locator('#scene-start').click();
  for (const p of [ana, ben]) await expect(p.page).toHaveURL(IN_BLUFF, { timeout: 30_000 });
  await expect.poll(async () => (await lastGame(ana.page))?.me?.cards?.length ?? 0, { timeout: 30_000 }).toBe(2);
}

test('results are held for the host: Play again takes everyone to a new setup, Party Home takes everyone home', async ({ browser, request }, info) => {
  const [ana, ben] = await setUp(browser, request, ['Ana', 'Ben']);
  await pickBluff(ana.page, [ana, ben]);
  await startRound(ana, ben);
  await finishRound(ana.page, ben.page);
  // the results stay (no timer); only the host has the next move
  await expect.poll(async () => (await partyState(ben.page)).location.at).toBe('results');
  await expect(ana.page.getByRole('button', { name: 'Play again' })).toBeVisible();
  await expect(ana.page.getByRole('button', { name: 'Party Home' })).toBeVisible();
  for (const label of ['Play again', 'Party Home']) {                 // icons, never icon names as text
    await expect(ana.page.locator('#bar button', { hasText: label })).toHaveText(label);
  }
  await expect(ben.page.locator('#bar')).toContainText('Waiting for Ana');
  await expect(ben.page.getByRole('button', { name: /Play again|Party Home/ })).toHaveCount(0);
  await ana.page.screenshot({ path: info.outputPath('results-host-390x844.png') });
  await ana.page.waitForTimeout(1_500);
  await expect(ben.page).toHaveURL(IN_BLUFF);                         // nobody walks away on their own
  let v = await partyState(ben.page);
  expect(await api(ben.page, 'home', { if_version: v.version })).toMatchObject({ status: 403, body: { error: 'not_host' } });
  // Play again: a fresh setup, for everyone
  await ana.page.getByRole('button', { name: 'Play again' }).click();
  for (const p of [ana, ben]) {
    await expect(p.page).toHaveURL(AT_HOME);
    await expect(p.page.locator('#scene')).toBeVisible();
    await expect(p.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'false');   // choose again
  }
  // a second round, then Party Home: everyone home
  await startRound(ana, ben);
  await finishRound(ana.page, ben.page);
  await ana.page.getByRole('button', { name: 'Party Home' }).click();
  for (const p of [ana, ben]) {
    await expect(p.page).toHaveURL(AT_HOME);
    await expect(p.page.locator('#main')).toBeVisible();
  }
  v = await partyState(ana.page);
  expect(v.location.at).toBe('home');
  await ana.context.close(); await ben.context.close();
});
