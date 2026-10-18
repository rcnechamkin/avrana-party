// Screenshots of Party Home and Library in each state, from a running dev server.
//
//   python -m avrana.web.devserver --port 8190 --party --test-controls
//   node docs/design/home-library-slice/capture.mjs http://127.0.0.1:8190 docs/design/home-library-slice/screens/after
//
// The same script, pointed at a dev server started from origin/main, made the "before" set.
// States are produced in the browser (a delayed or failed catalog request, the network switched
// off), so both sets are taken the same way. Fixture data only: the dev server's catalog and a
// memory-only Party with four invented people.
import { createRequire } from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
const require = createRequire(path.join(process.cwd(), 'x.js'));
const { chromium } = require('@playwright/test');

const [base, outdir] = process.argv.slice(2);
if (!base || !outdir) { console.error('usage: capture.mjs <baseUrl> <outdir>'); process.exit(2); }
fs.mkdirSync(outdir, { recursive: true });
const SIZES = [
  { tag: 'phone', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  { tag: 'desktop', viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 },
];
const browser = await chromium.launch();
const errors = [];

async function open(size, name, prepare) {
  const { tag, ...options } = size;
  const context = await browser.newContext({ ...options, baseURL: base, serviceWorkers: 'block', reducedMotion: 'reduce' });
  if (name) await context.addInitScript((who) => window.localStorage.setItem('wc-name', who), name);
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(`${tag}: ${e.message}`));
  if (prepare) await prepare(page, context);
  return { context, page };
}
async function settle(page) { await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(350); }
async function shot(page, size, name) {
  await settle(page);
  await page.screenshot({ path: path.join(outdir, `${name}-${size.tag}.png`) });
  const wide = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  console.log(`${name}-${size.tag}${wide ? '  SIDEWAYS SCROLL' : ''}`);
}

try {
  for (const size of SIZES) {
    await (await browser.newContext({ baseURL: base })).request.post('/__test__/party/reset');
    // three more phones, so the Party has people in it
    const others = [];
    for (const who of ['Bao', 'Chidi', 'Dana']) {
      const o = await open(size, who);
      await o.page.goto('/party/');
      await o.page.waitForSelector('html[data-ready="true"]');
      others.push(o);
    }
    let s = await open(size, 'Ada');
    await s.page.goto('/party/');
    await s.page.waitForSelector('html[data-ready="true"]');
    await s.page.waitForTimeout(1200);
    await shot(s.page, size, '01-home');
    await s.page.goto('/party/#library');
    await shot(s.page, size, '02-library');
    await s.page.locator('#lib-filter').click();
    await shot(s.page, size, '03-library-filters');
    await s.page.keyboard.press('Escape');
    await s.page.locator('#lib-view').click();
    await shot(s.page, size, '04-library-view-sheet');
    await s.page.keyboard.press('Escape');
    await s.page.locator('#game-search').fill('zzzz');
    await shot(s.page, size, '05-library-empty');
    await s.page.locator('#game-search').fill('');
    await s.page.goto('/party/#game/bluff');
    await settle(s.page);
    const rules = s.page.getByRole('button', { name: 'How to play' });
    if (await rules.count()) { await rules.first().click(); await shot(s.page, size, '06-how-to-play'); await s.page.keyboard.press('Escape'); }
    await s.page.goto('/party/#home');
    await settle(s.page);
    await s.context.setOffline(true);
    // the long poll in flight has to end first, so this takes up to 20 seconds
    await s.page.locator('#net').waitFor({ state: 'visible', timeout: 60000 });
    await shot(s.page, size, '07-home-reconnecting');
    await s.page.locator('#net-retry').waitFor({ state: 'visible', timeout: 60000 });
    await shot(s.page, size, '08-home-disconnected');
    await s.context.close();

    s = await open(size, 'Ada', (page) => page.route('**/party/catalog.json', () => { /* never answered */ }));
    await s.page.goto('/party/#library', { waitUntil: 'domcontentloaded' });
    await s.page.waitForTimeout(900);
    await shot(s.page, size, '09-library-loading');
    await s.context.close();

    s = await open(size, 'Ada', (page) => page.route('**/party/catalog.json', (route) => route.fulfill({ status: 500, body: 'no' })));
    await s.page.goto('/party/#library');
    await s.page.waitForSelector('html[data-ready="true"]');
    await shot(s.page, size, '10-library-error');
    await s.context.close();
    for (const o of others) await o.context.close();
  }
} finally { await browser.close(); }
if (errors.length) { console.error('page errors:\n' + errors.join('\n')); process.exit(1); }
