import { test, expect, Page, Browser } from '@playwright/test';

// Two phones on one party through the real page: explicit Join, live updates over the event
// stream, host-only controls, synchronized navigation, Leave — plus accessibility smoke checks.

test.beforeEach(async ({ request, baseURL }) => {
  const r = await request.post('/party/dev/reset-party', { headers: { Origin: baseURL! }, data: {} });
  expect(r.ok()).toBeTruthy();                                    // each test starts a fresh party
});

async function phone(browser: Browser, name: string): Promise<Page> {
  const ctx = await browser.newContext({ viewport: { width: 375, height: 740 } });
  const page = await ctx.newPage();
  await page.goto('/party/');
  await expect(page.getByRole('heading', { name: 'A party is running' })).toBeVisible();
  await page.getByLabel(/Your name/).fill(name);
  await page.getByRole('button', { name: 'Join the party' }).click();
  await expect(page.getByRole('heading', { name: 'You', exact: true })).toBeVisible();
  return page;
}

test('two phones: join, live updates, host controls, follow the host into a game, leave', async ({ browser }) => {
  const a = await phone(browser, 'Ana');
  await expect(a.getByText('— you are the host')).toBeVisible();
  const b = await phone(browser, 'Ben');
  await expect(b.getByRole('heading', { name: 'Host controls' })).toBeHidden();
  const people = a.getByRole('list', { name: 'People here' });
  await expect(people.getByText('Ben')).toBeVisible();            // pushed over SSE, no reload
  await expect(a.getByRole('list', { name: 'Party messages' })).toContainText('Ben joined the party.');

  await a.getByLabel('Game').selectOption('bluff');
  await a.getByRole('button', { name: 'Start for everyone' }).click();
  await b.waitForURL('**/games/bluff/');                          // seated phones follow once
  await a.waitForURL('**/games/bluff/');

  await b.goto('/party/');                                        // came back on purpose:
  await expect(b.getByText('The party is playing bluff.')).toBeVisible();   // a banner, not a yank
  await expect(b).toHaveURL(/\/party\/$/);
  await b.getByRole('button', { name: 'Leave party' }).click();
  await expect(b.getByRole('heading', { name: 'A party is running' })).toBeVisible();
  await a.goto('/party/');
  await expect(a.getByRole('list', { name: 'People here' }).getByText('Ben')).toBeHidden();
  await a.getByRole('button', { name: 'End game (everyone home)' }).click();
  await a.close(); await b.close();
});

test('accessibility smoke: names, labels, targets, no sideways scroll', async ({ browser }) => {
  const a = await phone(browser, 'Ana');
  const problems = await a.evaluate(() => {
    const out: string[] = [];
    for (const el of Array.from(document.querySelectorAll('button, input, select, a[href]')) as HTMLElement[]) {
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
