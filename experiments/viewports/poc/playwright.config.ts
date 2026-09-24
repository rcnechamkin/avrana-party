import { defineConfig, devices } from '@playwright/test';

// Laptop-only tests for the Personal Viewports PoC. Starts the stdlib PoC server locally;
// nothing here touches the Pi.
export default defineConfig({
  testDir: '.',
  testMatch: 'viewport.spec.ts',
  workers: 1,
  reporter: [['list']],
  timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:8765' },
  webServer: {
    command: 'python serve.py --host 127.0.0.1 --port 8765',
    cwd: __dirname,
    url: 'http://127.0.0.1:8765/layouts',
    reuseExistingServer: false,
    timeout: 15_000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
});
