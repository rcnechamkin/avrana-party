import { test, expect } from '@playwright/test';

/** /party/diag/ with a real Party Core behind the dev server: the running build is shown and a
 * field report can be copied. Nothing is uploaded; the person pastes it. (The diagnostics JSON
 * report keeps excluding the user agent; the field report is the explicit human-submitted one.) */
test('the diagnostics page shows the running build and prepares a field report', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/party/diag/');
  await expect(page.locator('#build')).toContainText('Summary');
  await expect(page.locator('#build')).toContainText('avrana.party-games/v0');
  await expect(page.locator('#build')).toContainText('no deployment manifest');   // the dev server never deploys
  const report = await page.locator('#field-report').textContent();
  expect(report).toMatch(/^Avrana field report \d{4}-\d{2}-\d{2}T/);
  expect(report).toMatch(/party: [0-9a-f]{40}/);
  expect(report).toContain('contract: avrana.party-games/v0');
  expect(report).toContain('browser: Mozilla/');
  expect(report).toContain('what happened:');
  // The machine-readable diagnostics report still never carries the user agent.
  await expect.poll(async () => page.locator('#report').textContent()).not.toContain('Mozilla/');
  await page.locator('#copy-field').click();
  await expect(page.locator('#copy-field')).toHaveText(/Copied|Selected/);
  const requests: string[] = [];
  page.on('request', (r) => requests.push(r.url()));
  await page.waitForTimeout(500);
  expect(requests.filter((u) => !u.includes('/party/api/state'))).toEqual([]);   // nothing uploaded
});
