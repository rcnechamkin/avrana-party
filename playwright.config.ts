import { defineConfig, devices } from '@playwright/test';

/**
 * Avrana Party end-to-end browser tests.
 *
 * Target is the live appliance on the Avrana Party Wi-Fi, reached at
 * http://party.avrana (-> 10.42.0.1). This machine must be joined to the
 * "Avrana Party" SSID for these tests to reach the Pi. Do NOT use the Pi's
 * home-LAN address (10.0.0.142 on eth0 since 2026-09-24) for client-facing tests — that path does not
 * exercise the AP interface the phones actually use.
 *
 * Two projects, per the testing brief:
 *   - chromium       : general regression + the WebRTC streaming path.
 *   - iphone-safari  : WebKit on an iPhone profile, for iOS-oriented layout /
 *                      touch regression. NOTE: Playwright's WebKit is only a
 *                      proxy for iOS Safari and has limited WebRTC media
 *                      support, so the live streaming test is Chromium-only and
 *                      a real iPhone remains authoritative for iOS + captive.
 */
export default defineConfig({
  testDir: './tests',
  // Offline suites have their own runners (playwright.offline.config.ts, node --test, unittest).
  testIgnore: ['offline/**', 'unit/**', 'rollback/**'],
  fullyParallel: false, // the appliance has MAX_PLAYERS=2; avoid slot contention
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // one client at a time against the single live Pi
  reporter: [['html', { open: 'never' }], ['list']],
  timeout: 45_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: 'http://party.avrana',
    // Capture evidence on failure (see the brief).
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'iphone-safari',
      use: { ...devices['iPhone 13'] },
    },
  ],
});
