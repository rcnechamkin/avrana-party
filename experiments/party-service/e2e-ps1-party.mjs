// End to end on the Pi: Party Home -> host starts Bomberman -> phones follow -> seat tickets make
// party seat N = in-game Player N whoever taps Play first; a late joiner gets an open seat; an
// outsider (never joined) only watches; a reload keeps the seat; End game brings everyone home.
//
//   front.py --port 8190 --host <addr>:8190 --ps1 <ps1 dir> --devices ""     (on the Pi, fresh party)
//   PW_FROM=<repo with node_modules> node e2e-ps1-party.mjs http://<addr>:8190
import { createRequire } from 'node:module';
const { chromium } = createRequire(process.env.PW_FROM ? process.env.PW_FROM + '/x.js' : import.meta.url)('@playwright/test');
const BASE = process.argv[2] || 'http://10.0.0.142:8190';
const t0 = Date.now();
const log = (...a) => console.log(((Date.now() - t0) / 1000).toFixed(1).padStart(6), ...a);
const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
async function phone(name) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  page.on('pageerror', e => log(name, 'PAGE ERROR', String(e)));
  return page;
}
async function join(page, name) {
  await page.goto(BASE + '/party/');
  await page.fill('#join-name', name);
  await page.click('#join-form button');
  await page.waitForSelector('#member:not([hidden])');
}
async function play(page) {
  await page.click('#connect');
  await page.waitForFunction(() => document.querySelector('video').readyState >= 2, null, { timeout: 30000 });
  return (await page.textContent('#role')) + ' | ' + (await page.textContent('#status'));
}
const ana = await phone('Ana'), ben = await phone('Ben');
await join(ana, 'Ana');
await join(ben, 'Ben');
log('seats before start:', await ana.textContent('#me-role'), '/', await ben.textContent('#me-role'));
await ana.selectOption('#game', 'ps1-bomberman');
await ana.click('#select-form button');
await ana.waitForSelector('#launch:not([hidden])');
log('host sees:', await ana.textContent('#launch-text'));
await Promise.all([ana, ben].map(p => p.waitForURL('**/ps1/bomberman/', { timeout: 90000 })));
log('both phones followed into the game');
for (const path of ['/ps1/bomberman/stats', '/ps1/worms/']) log('GET', path, '->', (await ana.request.get(BASE + path)).status(), '(want 503)');
log('Ben taps Play FIRST:', await play(ben));
log('Ana taps Play second:', await play(ana));
const cy = await phone('Cy');
await cy.goto(BASE + '/party/');
await cy.fill('#join-name', 'Cy');
await cy.click('#join-form button');
await cy.waitForURL('**/ps1/bomberman/', { timeout: 20000 });   // late_join: supported -> an open seat
log('late joiner Cy followed into the game; taps Play:', await play(cy));
const out = await phone('Outsider');
await out.goto(BASE + '/ps1/bomberman/');
log('outsider (never joined) taps Play:', await play(out));
// Ben reloads (a phone waking up): he must get seat 2 back, not a different one.
await ben.reload();
log('Ben after reload taps Play:', await play(ben));
// Clean up: Ana goes home and ends the game.
await ana.click('#party-bar');
await ana.waitForURL('**/party/');
await ana.waitForSelector('#nav-banner:not([hidden])');
log('host at Party Home gets a banner, not yanked back:', await ana.textContent('#nav-text'));
await ana.click('#end-game');
await ben.waitForURL('**/party/', { timeout: 20000 });
log('game ended; Ben back at', new URL(ben.url()).pathname);
await browser.close();
