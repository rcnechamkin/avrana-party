import { defineConfig, devices } from '@playwright/test';

// Laptop-only browser tests for the dev party service. Starts the stdlib front door on :8191
// (no games upstream, memory-only device store). Nothing here touches the Pi.
// With a different pre-installed Chromium (e.g. Claude Code Cloud), point PW_CHROMIUM_EXECUTABLE at it
// and run --project=chromium; WebKit on Linux is not iPhone Safari either way.
const executablePath = process.env.PW_CHROMIUM_EXECUTABLE || undefined;

export default defineConfig({
  testDir: '.',
  testMatch: ['party.spec.ts', 'reconnect.spec.ts'],
  workers: 1,
  reporter: [['list']],
  timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:8191' },
  webServer: {
    command: 'python -B front.py --port 8191 --devices "" --dev-commands',
    cwd: __dirname,
    url: 'http://127.0.0.1:8191/party/state',
    reuseExistingServer: false,
    timeout: 15_000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Pixel 7'], launchOptions: { executablePath } } },
    { name: 'webkit', use: { ...devices['iPhone 13'] } },
  ],
});
