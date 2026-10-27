import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';

/** The diagnostics page (/party/diag/) against the simulated Party (Tier 2). */
const catalog = JSON.parse(readFileSync(path.join(__dirname, '../../web/party/catalog.json'), 'utf8'));
const vocabulary = JSON.parse(readFileSync(path.join(__dirname, '../../contracts/capabilities.v0.json'), 'utf8'));

async function report(page) {
  const text = await page.locator('#report').textContent();
  return JSON.parse(text ?? '{}');
}

test('shows every capability and a machine-readable report', async ({ page }) => {
  await page.goto('/party/diag/');
  await expect.poll(async () => (await report(page).catch(() => ({}))).schema).toBe('avrana.diagnostics/v0');
  const names = await page.locator('#caps tbody tr td:first-child').allTextContents();
  expect(names.sort()).toEqual(Object.keys(vocabulary.device).sort());
  const r = await report(page);
  expect(r.capabilities.schema).toBe('avrana.capabilities/v0');
  expect(r.appliance.id).toBe('avrana-pi4');
  expect(r.origin.serverAddr).toBe('127.0.0.1');
  expect(r.evaluations.map((e: { game: string }) => e.game).sort()).toEqual(catalog.games.map((g: { id: string }) => g.id).sort());
  expect(r.evaluations).toHaveLength(6);
  expect(r.evaluations.find((e: { game: string }) => e.game === 'checkers').installed).toBe(true);
  expect(JSON.stringify(r)).not.toContain('Mozilla/');  // the user agent is shown to people, never reported
  await expect(page.locator('#summary')).toContainText('reached the Pi at 127.0.0.1');
  await expect(page.locator('#providers')).toContainText('uinput-gamepad');
  expect(r.evaluations.find((e: { game: string }) => e.game === 'bluff').installed).toBe(true);
  await expect(page.locator('#games tbody tr', { hasText: 'BLUFF' })).not.toContainText('not installed');
});

test('deep checks and the keep-awake test', async ({ page }) => {
  await page.addInitScript(() => {
    (window as any).__wake = { requests: 0, releases: 0 };
    Object.defineProperty(navigator, 'wakeLock', {
      configurable: true,
      value: {
        request: async () => {
          (window as any).__wake.requests += 1;
          const handlers: Array<() => void> = [];
          return {
            released: false,
            addEventListener: (_: string, fn: () => void) => handlers.push(fn),
            async release() {
              if (!this.released) { this.released = true; (window as any).__wake.releases += 1; handlers.forEach((f) => f()); }
            },
          };
        },
      },
    });
  });
  await page.goto('/party/diag/');
  await expect.poll(async () => (await report(page).catch(() => ({}))).schema).toBe('avrana.diagnostics/v0');
  await page.getByRole('button', { name: 'Run deep checks' }).click();
  await expect(page.getByRole('button', { name: 'Deep checks done' })).toBeVisible({ timeout: 10_000 });
  expect((await report(page)).capabilities.depth).toBe('deep');
  await page.getByRole('button', { name: 'Test keep-awake' }).click();
  await expect(page.locator('#awake-state')).toHaveText('Keep-awake: on');
  await page.getByRole('button', { name: 'Release keep-awake' }).click();
  await expect(page.locator('#awake-state')).toHaveText('Keep-awake: off');
  expect(await page.evaluate(() => (window as any).__wake)).toEqual({ requests: 1, releases: 1 });
});

test('remove offline copy unregisters the worker and its caches', async ({ page }) => {
  await page.goto('/party/');
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.goto('/party/diag/');
  await expect(page.locator('#shell')).toContainText('/party/');
  await page.getByRole('button', { name: 'Remove offline copy' }).click();
  await expect(page.locator('#shell')).toContainText('removed (1 worker');
  const left = await page.evaluate(async () => ({
    registrations: (await navigator.serviceWorker.getRegistrations()).length,
    caches: (await caches.keys()).filter((k) => k.startsWith('avrana-party-shell-')).length,
  }));
  expect(left).toEqual({ registrations: 0, caches: 0 });
});

test('the input probe starts only on request, observes a synthetic controller and records no id or text', async ({ page }) => {
  await page.addInitScript(() => {
    (window as any).__pads = [null, null, null, null];
    Object.defineProperty(navigator, 'getGamepads', { configurable: true, value: () => (window as any).__pads });
  });
  await page.goto('/party/diag/');
  await expect.poll(async () => (await report(page).catch(() => ({}))).schema).toBe('avrana.diagnostics/v0');
  expect((await report(page)).input).toBe('not tested');
  await expect(page.locator('#input')).toBeEmpty();

  await page.locator('#input-start').click();
  await expect(page.locator('#input')).toContainText('none reported yet');
  await page.evaluate(() => {
    const pad = {
      index: 0, mapping: '', connected: true, id: 'Secret Pad (Vendor: 2dc8 Product: 6006)',
      buttons: Array.from({ length: 11 }, (_, i) => ({ pressed: i === 3, value: i === 3 ? 1 : 0 })), axes: [0, 0, 0, 0, 0, 0, -1, 0],
    };
    (window as any).__pads = [pad, null, null, null];
    window.dispatchEvent(Object.assign(new Event('gamepadconnected'), { gamepad: pad }));
  });
  await page.keyboard.type('pw');
  await page.keyboard.press('ArrowDown');
  await expect(page.locator('#input')).toContainText('gamepad-nonstandard');
  await expect(page.locator('#input')).toContainText('pressed [3], moved [6]');

  await page.locator('#input-start').click();
  await expect(page.locator('#input-start')).toHaveText('Probe stopped: start again');
  const r = await report(page);
  expect(r.input.schema).toBe('avrana.input-probe/v0');
  expect(r.input.path).toBe('gamepad-nonstandard');
  expect(r.input.keys).toEqual(expect.arrayContaining([{ key: 'character', code: 'character', count: 2 },
    { key: 'ArrowDown', code: 'ArrowDown', count: 1 }]));
  const text = JSON.stringify(r.input);
  for (const leak of ['Secret', '2dc8', '6006', 'KeyP', 'KeyW']) expect(text).not.toContain(leak);
  expect(r.input.keys.map((k: { key: string }) => k.key)).not.toEqual(expect.arrayContaining(['p']));
  expect(r.input.keys.map((k: { key: string }) => k.key)).not.toEqual(expect.arrayContaining(['w']));
});
