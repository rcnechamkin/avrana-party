import { defineConfig, devices } from '@playwright/test';

/**
 * The rollback rehearsal (Tier 2): two stamped builds of the shell, a `current` link that is
 * flipped between them under a running dev server, and one phone that stays open through it.
 * The spec builds both releases and starts its own server, so there is no webServer here.
 *
 *   AVRANA_ROLLBACK_FROM=<git ref of the release to go back to, default origin/main> \
 *   npx playwright test -c playwright.rollback.config.ts
 *
 * It needs that ref in the local repository, so it is not part of CI's shallow checkout: it is
 * run by hand before a release and its result recorded (docs/design/ux-redesign/ACCEPTANCE.md).
 * Chromium on a laptop: it does not prove the flip on the Pi, nginx, or a real phone's cache.
 */
export default defineConfig({
  testDir: './tests/rollback',
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],
  outputDir: 'test-results/rollback',
  timeout: 120_000,
  expect: { timeout: 10_000 },
  use: { trace: 'retain-on-failure', serviceWorkers: 'allow' },
  projects: [
    { name: 'phone-chromium', use: { ...devices['Pixel 7'], launchOptions: { executablePath: process.env.PW_CHROMIUM_EXECUTABLE || undefined } } },
  ],
});
