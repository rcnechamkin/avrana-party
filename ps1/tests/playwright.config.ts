import { defineConfig, devices } from '@playwright/test';

// Static layout tests for ps1/index.html (no Pi, no stream). Run from the repo root:
//   npx playwright test -c ps1/tests/playwright.config.ts
export default defineConfig({
  testDir: '.',
  testMatch: /layout\.spec\.ts/,
  reporter: [['list']],
  outputDir: '../../test-results/ps1-layout',
  use: { baseURL: 'http://127.0.0.1:8199' },
  webServer: { command: 'python -m http.server 8199 --bind 127.0.0.1 --directory ps1', url: 'http://127.0.0.1:8199/',
               cwd: '../..', reuseExistingServer: false },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
});
