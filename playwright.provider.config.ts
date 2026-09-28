import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';
const games = process.env.AVRANA_GAMES_REPO;
if (!games) throw new Error('Set AVRANA_GAMES_REPO to an explicit local games checkout. Never a Pi path.');
const python = process.env.AVRANA_PROVIDER_PYTHON || 'python3';
export default defineConfig({
  testDir: './tests/provider', testMatch: /.*\.spec\.ts$/, workers: 1,
  fullyParallel: false, retries: 0, timeout: 30000,
  reporter: [['list']], outputDir: 'test-results/provider',
  use: { baseURL: 'http://127.0.0.1:8182', trace: 'retain-on-failure', serviceWorkers: 'allow' },
  webServer: {
    command: `"${python}" tests/provider/server.py --games "${resolve(games)}" --port 8182`,
    url: 'http://127.0.0.1:8182/party/', reuseExistingServer: false, timeout: 20000,
  },
  projects: [
    { name: 'android-size', use: { ...devices['Pixel 7'], launchOptions: { executablePath: process.env.PW_CHROMIUM_EXECUTABLE } } },
    { name: 'iphone-size', use: { ...devices['iPhone 13'], browserName: 'chromium', launchOptions: { executablePath: process.env.PW_CHROMIUM_EXECUTABLE } } },
  ],
});
