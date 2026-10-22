import { defineConfig, devices } from '@playwright/test';

// Hosted staging acceptance (H3, docs/design/HOSTED-STAGING.md, docs/runbooks/hosted-staging.md step 6).
// It drives a DEPLOYED Party through its real pages and API: no dev server, no /__test__/ control, no
// mocked lifecycle. The same specs run against any deployment of the Party that has a game origin:
//
//   HOSTED_BASE_URL=https://avrana.party  HOSTED_GAME_ORIGIN=https://games.avrana.party   (defaults: games.<host>)
//   HOSTED_ACCESS_CLIENT_ID / HOSTED_ACCESS_CLIENT_SECRET   a Cloudflare Access service token, from the
//       environment only (never a file in a repository); without it the run is an unauthenticated visitor
//   HOSTED_EXPECT_ACCESS=1      the deployment must be behind Access (edge.spec.ts checks it refuses strangers)
//   HOSTED_GAMES=bestguess,checkers,tanks    games to play end to end, each with HOSTED_GAMES_REPO/<id>/party-driver.mjs
//   HOSTED_GAMES_REPO=../avrana-party-games  the Games checkout whose drivers play the games
//   HOSTED_RESOLVE_LOOPBACK=1   map *.avrana.test to 127.0.0.1 (a local two-origin harness, e.g. the provider server)
//   HOSTED_OWNER_ASSIST=1       also run the cases that need the owner at the VM (killing a game process)
//
// `npm run test:hosted`. Results: test-results/hosted/ (traces, screenshots) and hosted-run.json (the deployed
// commits the run saw at /party/api/status, written by tests/hosted/hosted.ts).
const base = process.env.HOSTED_BASE_URL;
if (!base) throw new Error('Set HOSTED_BASE_URL to the deployment under test, e.g. https://avrana.party');
const args = process.env.HOSTED_RESOLVE_LOOPBACK === '1' ? ['--host-resolver-rules=MAP *.avrana.test 127.0.0.1'] : [];
const launchOptions = { executablePath: process.env.PW_CHROMIUM_EXECUTABLE, args };

export default defineConfig({
  testDir: './tests/hosted',
  testMatch: /.*\.spec\.ts$/,
  // One Party per deployment: specs that use it run one after another.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 20_000 },
  reporter: [['list'], ['json', { outputFile: 'test-results/hosted/results.json' }]],
  outputDir: 'test-results/hosted',
  use: {
    baseURL: base,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    serviceWorkers: 'allow',
    navigationTimeout: 30_000,
  },
  projects: [
    { name: 'android-size', use: { ...devices['Pixel 7'], launchOptions } },
    { name: 'iphone-size', use: { ...devices['iPhone 13'], browserName: 'chromium', launchOptions } },
  ],
});
