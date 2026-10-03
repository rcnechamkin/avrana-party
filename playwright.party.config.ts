import { defineConfig, devices } from '@playwright/test';

/**
 * Multi-client Party tests (Tier 2): several browser contexts, each a "phone", against the dev
 * server running a REAL Party Core (avrana/web/devserver.py --party) with stub game pages.
 * No Pi, no Party Wi-Fi, no games server. 127.0.0.1 is a secure context like the real origin.
 *
 *   npx playwright test -c playwright.party.config.ts
 *
 * Chromium at phone sizes approximates phones; it does not prove iPhone Safari or Android Chrome
 * on real hardware (docs/TESTING.md, Tier 3).
 */
const executablePath = process.env.PW_CHROMIUM_EXECUTABLE || undefined;
const PORT = Number(process.env.AVRANA_PARTY_DEV_PORT || 8184);

export default defineConfig({
  testDir: './tests/party',
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],
  timeout: 45_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    // Three contexts reload a ~90-resource page at the same moment. Full tracing (DOM snapshots and
    // a screencast per context) slowed each page's boot about tenfold and made the suite fail on
    // timing alone; the network and console log is what a failure here needs.
    trace: { mode: 'retain-on-failure', screenshots: false, snapshots: false, sources: false },
    serviceWorkers: 'block',
  },
  webServer: {
    command: `${process.env.AVRANA_PYTHON || 'python3'} -m avrana.web.devserver --port ${PORT} --test-controls --party`,
    url: `http://127.0.0.1:${PORT}/party/`,
    reuseExistingServer: false,
    timeout: 15_000,
  },
  projects: [
    { name: 'phones-chromium', use: { ...devices['Pixel 7'], launchOptions: { executablePath } } },
  ],
});
