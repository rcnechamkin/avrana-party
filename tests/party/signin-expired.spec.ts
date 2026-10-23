import { test, expect } from '@playwright/test';
import { phone, type Phone } from '../lib/phones';

// Hosted staging (docs/design/HOSTED-STAGING.md): when the access gateway in front of the Party ends a
// person's sign-in, every Party API request is answered with a redirect to its login page. The page
// must not mistake that for a lost Party box and retry forever; it says so once and reloads on request.
// On the appliance Party Core never redirects, so this path never fires there.
test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

test('a sign-in redirect on the Party API says "Sign in again", and its button loads the page again', async ({ browser }) => {
  const ada: Phone = await phone(browser, 'Ada');
  try {
    await expect(ada.page.locator('html')).toHaveAttribute('data-link', 'ok');
    let redirect = true;
    await ada.page.route('**/party/api/**', (route) => {
      const url = new URL(route.request().url());
      if (!redirect || url.pathname.endsWith('/origin.json')) return route.continue();
      return route.fulfill({ status: 302, headers: { Location: 'https://example.cloudflareaccess.com/cdn-cgi/access/login' } });
    });
    await ada.page.evaluate(() => window.dispatchEvent(new Event('online')));   // the next poll goes now
    await expect(ada.page.locator('html')).toHaveAttribute('data-link', 'signin', { timeout: 40_000 });
    await expect(ada.page.locator('#net')).toBeVisible();
    await expect(ada.page.locator('#net-title')).toHaveText(/sign in again/i);
    await expect(ada.page.locator('#net-text')).not.toContainText('Wi-Fi');
    await expect(ada.page.locator('#net-retry')).toBeVisible();

    redirect = false;                          // signed in again: the reload finds the Party as it was
    await Promise.all([ada.page.waitForEvent('load'), ada.page.locator('#net-retry').click()]);
    await expect(ada.page.locator('html')).toHaveAttribute('data-ready', 'true');
    await expect(ada.page.locator('html')).toHaveAttribute('data-link', 'ok');
  } finally {
    await ada.context.close();
  }
});
