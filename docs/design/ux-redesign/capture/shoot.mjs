// usage: node shoot.mjs <outdir> name=page.html?x=y@390x844 ...
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
const require = createRequire(path.join(process.cwd(), 'x.js'));
const { chromium } = require('@playwright/test');
const [outdir, ...jobs] = process.argv.slice(2);
const base = pathToFileURL(path.resolve('docs/design/ux-redesign/prototypes') + path.sep).href;
const browser = await chromium.launch();
try {
  for (const j of jobs) {
    // optional ^end or ^<px> after the size scrolls the tallest scrollable element before the shot
    const m = j.match(/^(.+?)=(.+)@(\d+)x(\d+)(?:\^(end|\d+))?$/);
    const [, name, page, w, h, scroll] = m;
    const ctx = await browser.newContext({ viewport: { width: +w, height: +h }, deviceScaleFactor: +(process.env.DPR || 2), isMobile: true, hasTouch: true });
    const p = await ctx.newPage();
    const errs = [];
    p.on('console', (msg) => { if (msg.type() === 'error') errs.push(msg.text()); });
    await p.goto(base + page);
    await p.waitForTimeout(250);
    await p.evaluate(() => document.fonts.ready);
    const info = await p.evaluate(() => { const m = document.querySelector('.main, [data-scroll]'); return { sw: document.documentElement.scrollWidth, iw: innerWidth, mainScroll: m ? m.scrollHeight - m.clientHeight : null }; });
    const scrollers = await p.evaluate((to) => {
      const out = []; let best = null;
      document.querySelectorAll('*').forEach((el) => {
        const cs = getComputedStyle(el); const over = el.scrollHeight - el.clientHeight;
        if (over > 1 && /(auto|scroll)/.test(cs.overflowY) && el.clientHeight > 0 && cs.visibility !== 'hidden') {
          out.push((el.id ? '#' + el.id : '.' + String(el.className).split(' ')[0]) + ':' + over);
          if (!best || over > best.scrollHeight - best.clientHeight) best = el;
        }
      });
      if (to && best) best.scrollTop = to === 'end' ? best.scrollHeight : +to;
      return out;
    }, scroll || null);
    info.scrollers = scrollers; info.docOverflowY = await p.evaluate(() => document.documentElement.scrollHeight - innerHeight);
    if (scroll) await p.waitForTimeout(120);
    await p.screenshot({ path: path.join(outdir, `${name}-${w}x${h}.png`) });
    console.log(name, `${w}x${h}`, JSON.stringify(info), errs.length ? 'ERR ' + errs.join('|') : '');
    await ctx.close();
  }
} finally { await browser.close(); }
