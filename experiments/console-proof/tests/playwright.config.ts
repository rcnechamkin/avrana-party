import { defineConfig, devices } from '@playwright/test';

/**
 * AVR-762 console proof. Own servers on 127.0.0.1:8370 (Party origin), :8371 (game origin) and
 * :8372 (name-mapping proxy for WebKit); never the repo's 8182–8188.
 *
 *   npx playwright test -c tests/playwright.config.ts                 (all projects)
 *   npx playwright test -c tests/playwright.config.ts --project=chromium-svelte-R
 *
 * Phone: 390x844, DPR 3, isMobile + hasTouch. On Chromium Playwright applies this with CDP
 * Emulation.setDeviceMetricsOverride / setTouchEmulationEnabled (not a window size). WebKit
 * desktop with the same settings only approximates iOS Safari.
 */
const phone = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true };
const chromium = { ...devices['Desktop Chrome'], ...phone, launchOptions: { args: ['--host-resolver-rules=MAP *.cp.test 127.0.0.1'] } };
const webkit = { ...devices['Desktop Safari'], ...phone, proxy: { server: 'http://127.0.0.1:8372', bypass: '127.0.0.1' } };

const projects = [];
for (const [engine, use] of [['chromium', chromium], ['webkit', webkit]] as const) {
  for (const fw of ['vanilla', 'svelte']) {
    for (const strategy of ['M', 'R']) {
      projects.push({ name: `${engine}-${fw}-${strategy}`, use: { ...use, fw, strategy }, testIgnore: /probes\.spec\.ts$/, timeout: engine === 'webkit' ? 90_000 : 45_000 });
    }
  }
}
projects.push({ name: 'chromium-probes', use: { ...chromium, fw: 'vanilla', strategy: 'M' }, testMatch: /probes\.spec\.ts$/ });
projects.push({ name: 'webkit-probes', use: { ...webkit, fw: 'vanilla', strategy: 'M' }, testMatch: /probes\.spec\.ts$/ });

export default defineConfig({
  testDir: '.',
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  timeout: 45_000,
  expect: { timeout: 8_000 },
  use: { trace: 'retain-on-failure', serviceWorkers: 'block' },
  webServer: {
    command: 'npm run build && node server/start.mjs',
    cwd: '..',
    url: 'http://127.0.0.1:8370/party/styles.css',
    reuseExistingServer: false,
    timeout: 60_000,
    env: { CP_TURN_MS: '5000' },
  },
  projects,
});
