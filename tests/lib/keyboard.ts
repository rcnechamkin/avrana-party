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
    let covered = 0, panned = 0;
    Object.defineProperties(vv, {
      width: { get: () => window.innerWidth }, height: { get: () => window.innerHeight - covered },
      offsetTop: { get: () => panned }, offsetLeft: { value: 0 }, pageTop: { get: () => panned }, pageLeft: { value: 0 }, scale: { value: 1 },
    });
    Object.defineProperty(window, 'visualViewport', { value: vv, configurable: true });
    (window as unknown as { __keyboard: (px: number, pan: number) => void }).__keyboard = (px, pan) => {
      covered = px; panned = pan;
      vv.dispatchEvent(new Event('resize'));
      if (pan) vv.dispatchEvent(new Event('scroll'));
    };
    // Rotating the phone resizes the layout viewport; a real visualViewport reports that too.
    window.addEventListener('resize', () => vv.dispatchEvent(new Event('resize')));
  });
}

/**
 * Open (px > 0) or close (0) the simulated keyboard, covering px of the layout viewport. `pan` is how far
 * iPhone Safari has scrolled the visual viewport down inside the layout viewport to keep the focused field
 * in view (visualViewport.offsetTop); position:fixed boxes stay anchored to the layout viewport, not to it.
 */
export async function keyboard(page: Page, px: number, pan = 0) {
  await page.evaluate(([n, o]) => (window as unknown as { __keyboard: (n: number, o: number) => void }).__keyboard(n, o), [px, pan]);
}

/** The visible height the keyboard leaves, as the page reads it. */
export const visibleHeight = (page: Page) => page.evaluate(() => window.visualViewport!.height);

/** Where the visible region starts, as the page reads it (visualViewport.offsetTop). */
export const visibleTop = (page: Page) => page.evaluate(() => window.visualViewport!.offsetTop);
