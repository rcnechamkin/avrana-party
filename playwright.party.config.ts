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
// AVR-307: a second dev server whose games are registered to a game origin (ADR 0013), for follow-origin.spec.ts
const ORIGIN_PORT = Number(process.env.AVRANA_PARTY_ORIGIN_DEV_PORT || PORT + 1);
// AVR-468: a third dev server with the owner-gated home_in_round proposal on (AVR-703), for home-in-round.spec.ts
const VISIT_PORT = Number(process.env.AVRANA_PARTY_VISIT_DEV_PORT || PORT + 2);
const python = process.env.AVRANA_PYTHON || 'python3';

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
  webServer: [{
    command: `${python} -m avrana.web.devserver --port ${PORT} --test-controls --party`,
    url: `http://127.0.0.1:${PORT}/party/`,
    reuseExistingServer: false,
    timeout: 15_000,
  }, {
    command: `${python} -m avrana.web.devserver --port ${ORIGIN_PORT} --test-controls --party --game-origin`,
    url: `http://127.0.0.1:${ORIGIN_PORT}/party/`,
    reuseExistingServer: false,
    timeout: 15_000,
  }, {
    command: `${python} -m avrana.web.devserver --port ${VISIT_PORT} --test-controls --party`,
    env: { ...process.env, AVRANA_DEV_PROPOSALS: 'home_in_round' },
    url: `http://127.0.0.1:${VISIT_PORT}/party/`,
    reuseExistingServer: false,
    timeout: 15_000,
  }],
  projects: [
    { name: 'phones-chromium', testIgnore: /(follow-origin|guest-journey-origins|home-in-round)\.spec\.ts$/, use: { ...devices['Pixel 7'], launchOptions: { executablePath } } },
    {
      // ADR 0013: games registered to a game origin, which Chromium resolves to the dev server.
      // Plain HTTP on two host names of one site; real Safari and HTTPS are Tier 3 (the owner's).
      name: 'two-origins-chromium',
      testMatch: /(follow-origin|guest-journey-origins)\.spec\.ts$/,
      use: {
        ...devices['Pixel 7'], baseURL: `http://127.0.0.1:${ORIGIN_PORT}`,
        launchOptions: { executablePath, args: ['--host-resolver-rules=MAP *.avrana.test 127.0.0.1'] },
      },
    },
    {
      // AVR-468: Party Home during a round is an owner-gated proposal (AVR-703), on only for this server.
      name: 'home-in-round-chromium',
      testMatch: /home-in-round\.spec\.ts$/,
      use: { ...devices['Pixel 7'], baseURL: `http://127.0.0.1:${VISIT_PORT}`, launchOptions: { executablePath } },
    },
  ],
});
