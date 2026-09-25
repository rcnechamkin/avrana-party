// PS1 phone page layout, without a Pi: the page is served statically and put into each state.
//   npx playwright test -c ps1/tests/playwright.config.ts
// The picture is a generated 4:3 test pattern (never a game frame: ROMs and their output stay out
// of Git). Real-phone safe areas (notch, home bar) cannot be emulated here; see the real-phone runbook.
import { test, expect, Page } from '@playwright/test';

async function pattern(page: Page) {
  await page.evaluate(() => {
    const c = document.createElement('canvas'); c.width = 320; c.height = 240;
    const g = c.getContext('2d')!;
    for (let y = 0; y < 240; y += 20) for (let x = 0; x < 320; x += 20) {
      g.fillStyle = (x + y) % 40 ? '#3a6' : '#274'; g.fillRect(x, y, 20, 20);
    }
    g.strokeStyle = '#ff0'; g.lineWidth = 4; g.strokeRect(2, 2, 316, 236);
    (document.querySelector('video') as HTMLVideoElement).poster = c.toDataURL();
  });
}

async function state(page: Page, which: 'start' | 'playing' | 'watching') {
  await page.goto('/');
  await pattern(page);
  if (which === 'start') return;
  await page.evaluate((w) => {
    document.querySelector<HTMLElement>('#start-overlay')!.hidden = true;
    document.querySelector<HTMLElement>('#controls')!.hidden = w !== 'playing';
    document.getElementById('app')!.classList.add(w);
    const role = document.querySelector<HTMLElement>('#role')!;
    role.textContent = w === 'playing' ? 'Player 2' : 'Spectator'; role.hidden = false;
    document.querySelector<HTMLElement>('#sound')!.hidden = false;
  }, which);
}

type Box = { x: number; y: number; width: number; height: number; name: string };
async function boxes(page: Page, sel: string): Promise<Box[]> {
  return page.$$eval(sel, (els) => els.filter((e) => (e as HTMLElement).offsetParent !== null || getComputedStyle(e).position === 'fixed')
    .map((e) => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height,
      name: (e.getAttribute('aria-label') || e.textContent || '').trim() }; })
    .filter((b) => b.width > 0 && b.height > 0));
}
const overlap = (a: Box, b: Box) =>
  Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)) *
  Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));

for (const [label, vp] of [['iPhone 13 portrait', { width: 390, height: 844 }], ['iPhone 13 landscape', { width: 844, height: 390 }],
                           ['iPhone SE portrait', { width: 375, height: 667 }], ['iPhone SE landscape', { width: 667, height: 375 }]] as const) {
  test.describe(label, () => {
    test.use({ viewport: vp, hasTouch: true, isMobile: true });
    const landscape = vp.width > vp.height;

    test('playing: controls never cover the picture, all on screen, comfortable targets', async ({ page }, info) => {
      await state(page, 'playing');
      await page.screenshot({ path: info.outputPath('playing.png') });
      const stage = (await boxes(page, '.stage'))[0];
      const controls = await boxes(page, '#controls [data-bit], .bar .icon, #role');
      expect(controls.length).toBeGreaterThanOrEqual(17);
      for (const c of controls) {
        expect(overlap(c, stage), `${c.name} overlaps the picture`).toBeLessThanOrEqual(1);
        expect(c.x, c.name).toBeGreaterThanOrEqual(0);
        expect(c.y, c.name).toBeGreaterThanOrEqual(0);
        expect(c.x + c.width, c.name).toBeLessThanOrEqual(vp.width + 0.5);
        expect(c.y + c.height, c.name).toBeLessThanOrEqual(vp.height + 0.5);
      }
      for (const c of await boxes(page, '#controls [data-bit], .bar .icon')) {
        expect(Math.min(c.width, c.height), `${c.name} is too small to tap`).toBeGreaterThanOrEqual(40);
      }
      for (let i = 0; i < controls.length; i++) for (let j = i + 1; j < controls.length; j++) {
        expect(overlap(controls[i], controls[j]), `${controls[i].name} overlaps ${controls[j].name}`).toBeLessThanOrEqual(1);
      }
      if (landscape) expect(stage.height).toBeGreaterThanOrEqual(0.75 * vp.height);
      else expect(stage.width).toBeGreaterThanOrEqual(0.97 * vp.width);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(vp.width);
    });

    test('watching: no controller, the picture gets the room', async ({ page }, info) => {
      await state(page, 'watching');
      const stage = (await boxes(page, '.stage'))[0];
      expect(await boxes(page, '#controls [data-bit]')).toHaveLength(0);
      if (landscape) expect(stage.height).toBeGreaterThanOrEqual(0.9 * vp.height);
      else expect(stage.width).toBeGreaterThanOrEqual(0.97 * vp.width);
      await page.screenshot({ path: info.outputPath('watching.png') });
    });

    test('start: one obvious action, named controls, menu opens and closes', async ({ page }, info) => {
      await state(page, 'start');
      const play = page.getByRole('button', { name: 'Play' });
      await expect(play).toBeVisible();
      const pb = (await play.boundingBox())!;
      expect(pb.height).toBeGreaterThanOrEqual(44);
      for (const name of await page.$$eval('button, a', (els) => els.map((e) => (e.getAttribute('aria-label') || e.textContent || '').trim())))
        expect(name.length, 'every control has a name').toBeGreaterThan(0);
      await expect(page.locator('#metrics')).toBeHidden();              // no debug text in the play view
      await expect(page.locator('#party-bar')).toBeHidden();            // standalone: no party to go back to
      await expect(page.locator('#sound')).toBeHidden();                // nothing to hear yet
      await expect(page.locator('#diag')).toBeHidden();
      await page.screenshot({ path: info.outputPath('start.png') });
      await page.getByRole('button', { name: 'Menu' }).click();
      await expect(page.getByRole('button', { name: 'Give up my controller' })).toBeVisible();
      await page.getByRole('button', { name: 'Back to the game' }).click();
      await expect(page.locator('#menu')).toBeHidden();
    });
  });
}

test('diagnostics appear only when asked for (#diag)', async ({ page }) => {
  await page.goto('/#diag');
  await expect(page.locator('#diag')).toBeVisible();
});
