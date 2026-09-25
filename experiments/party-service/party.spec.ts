import { test, expect, Page, Browser } from '@playwright/test';

// Two phones on one party through the real page: the first-time path (name → Join), live updates
// over the event stream, host-only game picking, synchronized navigation, Leave — plus checks that
// the page speaks the guest's language (no machinery words) and stays accessible.

test.beforeEach(async ({ request, baseURL }) => {
  const r = await request.post('/party/dev/reset-party', { headers: { Origin: baseURL! }, data: {} });
  expect(r.ok()).toBeTruthy();                                    // each test starts a fresh party
});

async function phone(browser: Browser, name: string, shot?: string): Promise<Page> {
  const ctx = await browser.newContext({ viewport: { width: 375, height: 740 } });
  const page = await ctx.newPage();
  await page.goto('/party/');
  await expect(page.getByRole('button', { name: 'Join the party' })).toBeVisible();
  if (shot) await page.screenshot({ path: shot });
  await page.getByLabel('What should we call you?').fill(name);
  await page.getByRole('button', { name: 'Join the party' }).click();
  await expect(page.getByText(`Hi, ${name}`)).toBeVisible();
  return page;
}

const JARGON = /\b(seat|session|runtime|server|websocket|presence|manifest|launch(ing)?|backend|token|slot)\b/i;
async function visibleText(p: Page) { return p.evaluate(() => document.body.innerText); }

test('two phones: join, live updates, host picks a game, follow the host, leave', async ({ browser }, info) => {
  const a = await phone(browser, 'Ana', info.outputPath('1-welcome.png'));
  await expect(a.getByText('— you’re the host')).toBeVisible();
  await expect(a.getByRole('heading', { name: 'Pick a game' })).toBeVisible();
  const b = await phone(browser, 'Ben');
  await expect(b.getByRole('heading', { name: 'Pick a game' })).toBeHidden();        // host-only
  await expect(b.getByText('Waiting for Ana to pick a game')).toBeVisible();
  await expect(a.getByRole('list', { name: 'Players' }).getByText('Ben')).toBeVisible();   // pushed over SSE, no reload
  await expect(a.locator('#latest')).toHaveText('Ben joined the party.');
  await a.screenshot({ path: info.outputPath('2-host-lobby.png') });
  await b.screenshot({ path: info.outputPath('3-guest-waiting.png') });
  for (const p of [a, b]) expect(await visibleText(p)).not.toMatch(JARGON);

  await a.locator('[data-game="bluff"]').click();
  await a.getByRole('button', { name: 'Start BLUFF' }).click();
  await b.waitForURL('**/games/bluff/');                          // players follow once
  await a.waitForURL('**/games/bluff/');

  await b.goto('/party/');                                        // came back on purpose:
  await expect(b.getByText('BLUFF is on')).toBeVisible();          // a banner, not a yank
  await expect(b).toHaveURL(/\/party\/$/);
  await b.screenshot({ path: info.outputPath('4-game-on.png') });
  await b.getByText('Name, party options and activity').click();
  await b.getByRole('button', { name: 'Leave the party' }).click();
  await expect(b.getByRole('button', { name: 'Join the party' })).toBeVisible();
  await a.goto('/party/');
  await expect(a.getByRole('list', { name: 'Players' }).getByText('Ben')).toBeHidden();
  await a.getByRole('button', { name: 'End the game for everyone' }).click();
  await expect(a.getByRole('heading', { name: 'Pick a game' })).toBeVisible();
  await a.close(); await b.close();
});

test('friendly refusals: a reserved name is explained, not echoed', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 375, height: 740 } });
  const p = await ctx.newPage();
  await p.goto('/party/');
  await p.getByLabel('What should we call you?').fill('Host');
  await p.getByRole('button', { name: 'Join the party' }).click();
  await expect(p.getByRole('alert')).toHaveText('That name is reserved. Please pick another.');
  await ctx.close();
});

test('accessibility smoke: names, labels, targets, no sideways scroll', async ({ browser }) => {
  const a = await phone(browser, 'Ana');
  const problems = await a.evaluate(() => {
    const out: string[] = [];
    for (const el of Array.from(document.querySelectorAll('button, input, select, a[href], summary')) as HTMLElement[]) {
      if (el.offsetParent === null) continue;                        // hidden
      const r = el.getBoundingClientRect();
      const label = (el as HTMLInputElement).labels?.length || el.getAttribute('aria-label') || (el.textContent || '').trim();
      if (!label) out.push('unnamed ' + el.tagName);
      if (r.height < 44 && el.tagName !== 'A') out.push(`small target ${el.tagName} ${Math.round(r.height)}px: ${(el.textContent || el.id).trim()}`);
    }
    if (document.documentElement.scrollWidth > window.innerWidth) out.push('horizontal scroll');
    if (!document.documentElement.lang) out.push('no lang');
    return out;
  });
  expect(problems).toEqual([]);
  await a.close();
});
