import { defineConfig, devices } from '@playwright/test';

/**
 * Offline browser tests (Tier 2): real Chromium against a simulated Party on 127.0.0.1
 * (avrana/web/devserver.py). No Pi, no Party Wi-Fi, no phones. 127.0.0.1 is a secure context,
 * so service workers and Wake Lock behave as on https://party.avrana.net.
 *
 *   npx playwright install chromium          # once (CI does this)
 *   npx playwright test -c playwright.offline.config.ts
 *
 * In an environment with a different pre-installed Chromium (e.g. Claude Code Cloud), point
 * PW_CHROMIUM_EXECUTABLE at it instead of downloading. WebKit on Linux is not iPhone Safari, so it
 * is not used here; real iPhones stay Tier 3 (docs/TESTING.md).
 */
const executablePath = process.env.PW_CHROMIUM_EXECUTABLE || undefined;
const PORT = Number(process.env.AVRANA_DEV_PORT || 8181);

export default defineConfig({
  testDir: './tests/offline',
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],
  timeout: 30_000,
  expect: { timeout: 7_000 },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    serviceWorkers: 'allow',
  },
  webServer: {
    command: `${process.env.AVRANA_PYTHON || 'python3'} -m avrana.web.devserver --port ${PORT} --test-controls`,
    url: `http://127.0.0.1:${PORT}/party/`,
    reuseExistingServer: false,
    timeout: 15_000,
  },
  projects: [
    { name: 'android-chromium', use: { ...devices['Pixel 7'], launchOptions: { executablePath } } },
    {
      name: 'iphone-size-chromium',
      use: { ...devices['iPhone 13'], browserName: 'chromium', launchOptions: { executablePath } },
    },
  ],
});
