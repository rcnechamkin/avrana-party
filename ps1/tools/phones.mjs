// Simulated phones for the PS1 shared stream, runnable on the laptop (Node + the repo's
// Playwright; tools/viewers.py is the Python original). One isolated browser context per phone,
// so each has its own localStorage token and WebSocket, like separate devices. Players tap the
// page's real on-screen buttons with pointer events, so input takes the phone's path.
//
//   node ps1/tools/phones.mjs URL --players N [--watchers M] [--seconds S] --control FILE
//
// Append lines to FILE while it runs:
//   1 cross 150        player 1 holds Cross 150 ms ("1+2+3 up 400": simultaneous presses)
//   sleep 500          pause the script
//   shot PATH.png      screenshot the decoded <video> of the last phone (a watcher if any)
//   status             print each phone's role and status line
//   stages PREFIX      screenshot what each phone shows (its viewport crop) to PREFIX-<phone>.png
//   metrics            print each phone's last-second video stats (fps, loss, jitter, ack RTT)
//   leave P            player P presses Disconnect (frees the slot at once)
//   reload I           phone I (0-based, join order) reloads and taps Play (slot-reclaim test)
//   quit
import { chromium } from '@playwright/test';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const opt = (name, dflt) => { const i = argv.indexOf('--' + name); return i < 0 ? dflt : argv[i + 1]; };
const url = argv[0];
const players = +opt('players', 1), watchers = +opt('watchers', 0), seconds = +opt('seconds', 600);
const control = opt('control');
if (!url || !control) { console.error('usage: phones.mjs URL --players N [--watchers M] [--seconds S] --control FILE'); process.exit(2); }
const BITS = Object.fromEntries('up down left right cross circle square triangle l1 r1 l2 r2 start select'.split(' ').map((n, i) => [n, i]));
const log = (...a) => console.log(new Date().toISOString().slice(11, 23), ...a);

const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
const phones = [];
async function join(page, watch) {
  await page.click(watch ? '#watch' : '#connect');
  await page.waitForFunction(() => document.querySelector('video').readyState >= 2, null, { timeout: 25000 });
  return page.textContent('#role');
}
for (let i = 0; i < players + watchers; i++) {   // connect in order -> deterministic slots
  const ctx = await browser.newContext({ viewport: { width: 900, height: 900 } });
  const page = await ctx.newPage();
  const phone = { i, page, watch: i >= players, errors: [] };
  page.on('pageerror', e => phone.errors.push(String(e)));
  await page.goto(url);
  phone.role = await join(page, phone.watch);
  phones.push(phone);
  log(`phone ${i}: ${phone.role}`);
}
const bySlot = n => phones.find(p => p.role === `Player ${n}`);
async function press(page, button, ms) {
  const box = await page.locator(`[data-bit="${BITS[button]}"]`).boundingBox();
  if (!box) throw new Error(`button ${button} not visible`);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await new Promise(r => setTimeout(r, ms));
  await page.mouse.up();
}
fs.writeFileSync(control, '');
let done = 0;
const deadline = Date.now() + seconds * 1000;
while (Date.now() < deadline) {
  const lines = fs.readFileSync(control, 'utf8').split('\n').filter(Boolean);
  let quit = false;
  for (const line of lines.slice(done)) {
    const [cmd, a, b] = line.trim().split(/\s+/);
    try {
      if (cmd === 'quit') { quit = true; break; }
      else if (cmd === 'sleep') await new Promise(r => setTimeout(r, +a || 1000));
      else if (cmd === 'shot') { await phones.at(-1).page.locator('video').screenshot({ path: a }); log('shot', a); }
      else if (cmd === 'status') for (const p of phones) log(`phone ${p.i}`, p.role, '|', await p.page.textContent('#status'), p.errors.slice(0, 2).join(' '));
      else if (cmd === 'stages') for (const p of phones) {   // what each phone actually shows (crops included)
        await p.page.locator('.stage').screenshot({ path: `${a}-${p.i}.png` }); log('stage', `${a}-${p.i}.png`);
      }
      else if (cmd === 'metrics') for (const p of phones) {
        const m = JSON.parse(await p.page.textContent('#metrics').catch(() => 'null') || 'null');
        log(`phone ${p.i}`, p.role, m ? JSON.stringify({ fps: m.video?.fps, decoded: m.video?.decoded, lost: m.video?.pktLostD,
          jitterMs: m.video?.jitterBufMs, freezes: m.video?.freezes, gapP95: m.present?.gapP95, ackP50: m.ackRtt?.p50 }) : 'no metrics');
      }
      else if (cmd === 'leave') { const p = bySlot(+a); await p.page.click('#more'); await p.page.click('#leave'); log(`player ${a} left:`, await p.page.textContent('#status')); p.role = 'left'; }
      else if (cmd === 'reload') { const p = phones[+a]; await p.page.reload(); p.role = await join(p.page, false); log(`phone ${a} reloaded ->`, p.role); }
      else { const ms = +b || 150; await Promise.all(cmd.split('+').map(n => press(bySlot(+n).page, a, ms))); }
    } catch (e) { log('control line failed:', line, '-', e.message.split('\n')[0]); }
  }
  done = lines.length;
  if (quit) break;
  await new Promise(r => setTimeout(r, 100));
}
for (const p of phones) log(`phone ${p.i} final:`, p.role, '|', await p.page.textContent('#status').catch(() => '?'));
await browser.close();
