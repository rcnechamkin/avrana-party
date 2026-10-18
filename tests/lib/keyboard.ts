import type { BrowserContext, Page } from '@playwright/test';

/**
 * A SIMULATED software keyboard, for the suites that run in desktop Chromium (UX-07, AVR-579).
 *
 * On iPhone Safari and Android Chrome (default) an opened keyboard shrinks window.visualViewport
 * but leaves the layout viewport (innerHeight, 100dvh) alone, so a drawer sized in dvh keeps its
 * composer under the keys. Desktop Chromium cannot do that, so this replaces window.visualViewport
 * in the top page with a stand-in whose height the test sets. It models what a page can read; it
 * does not prove how a real phone scrolls, pans or animates. That stays a real iOS/Android check.
 */
export async function withKeyboardModel(context: BrowserContext) {
  await context.addInitScript(() => {
    const vv = new EventTarget() as EventTarget & Record<string, unknown>;
    let covered = 0;
    Object.defineProperties(vv, {
      width: { get: () => window.innerWidth }, height: { get: () => window.innerHeight - covered },
      offsetTop: { value: 0 }, offsetLeft: { value: 0 }, pageTop: { value: 0 }, pageLeft: { value: 0 }, scale: { value: 1 },
    });
    Object.defineProperty(window, 'visualViewport', { value: vv, configurable: true });
    (window as unknown as { __keyboard: (px: number) => void }).__keyboard = (px) => {
      covered = px;
      vv.dispatchEvent(new Event('resize'));
    };
  });
}

/** Open (px > 0) or close (0) the simulated keyboard, covering px of the layout viewport. */
export async function keyboard(page: Page, px: number) {
  await page.evaluate((n) => (window as unknown as { __keyboard: (n: number) => void }).__keyboard(n), px);
}

/** The visible height the keyboard leaves, as the page reads it. */
export const visibleHeight = (page: Page) => page.evaluate(() => window.visualViewport!.height);
