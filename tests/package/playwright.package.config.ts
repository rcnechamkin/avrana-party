import { defineConfig, devices } from '@playwright/test';

/**
 * AVR-338 (run from the repository root: npx playwright test -c tests/package/playwright.package.config.ts): real browsers (Tier 2, a CI runner) against an INSTALLED .avrgame package, through the
 * intended Party experience. Nothing here starts a server: experiments/native-game/package-browser-proof.sh
 * builds a disposable appliance (real systemd, Party Core, the installed Hello Party, the committed
 * nginx site on https://party.avrana.net and https://games.avrana.net with a throwaway certificate) and
 * then runs this config. Linux CI only; the specs skip themselves unless that script set
 * AVRANA_PACKAGE_BROWSER_PROOF.
 *
 *   sudo env "PATH=$PATH" AVRANA_PACKAGE_BROWSER_PROOF=1 AVRANA_GAMES_REPO=<games checkout> \
 *        bash experiments/native-game/package-browser-proof.sh
 *
 * Chromium and WebKit at phone sizes are not phones: iPhone Safari and Android Chrome stay Tier 3
 * (docs/TESTING.md). The Party cookie is Secure and HTTPS-only as in production; only the certificate
 * error is ignored.
 */
const executablePath = process.env.PW_CHROMIUM_EXECUTABLE || undefined;

export default defineConfig({
  testDir: '.',
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],
  timeout: 150_000,
  expect: { timeout: 15_000 },
  outputDir: process.env.AVRANA_BROWSER_OUT || 'test-results/package-browser',
  use: {
    baseURL: 'https://party.avrana.net',
    ignoreHTTPSErrors: true,
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium-pixel', use: { ...devices['Pixel 7'], launchOptions: { executablePath } } },
    { name: 'webkit-iphone', use: { ...devices['iPhone 13'] } },
  ],
});
