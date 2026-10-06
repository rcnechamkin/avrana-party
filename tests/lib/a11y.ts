import type { Page } from '@playwright/test';

/**
 * What a browser can check of docs/design/ACCESSIBILITY.md, on whatever is on screen: contrast
 * (MUST 9), names (MUST 2), landmarks and headings, reading order, visible focus, motion (MUST 8).
 * Each returns a list of what is wrong, empty when nothing is, so a failure names the element.
 * Chromium's own rendering only: none of this is a screen reader, and none of it is a phone.
 */

/** Text and marks that do not stand out from what is behind them. Text needs 4.5:1, large text
 * (24 px, or 18.66 px bold) and icons 3:1; `floor` raises the bar for text (higher contrast).
 * A colour is composited over every translucent surface under it down to the page's ground.
 * Not judged: text over a picture (covers), and a control that says it is unavailable. */
export async function lowContrast(page: Page, root = 'body', floor = 4.5) {
  return page.evaluate(([sel, min]) => {
    const cv = document.createElement('canvas');
    cv.width = cv.height = 1;
    const cx = cv.getContext('2d', { willReadFrequently: true })!;
    const cache = new Map<string, number[]>();
    // any CSS colour (oklch, color-mix, rgb with alpha) as [r, g, b, a]: painted on black and on white
    const rgba = (css: string) => {
      const hit = cache.get(css);
      if (hit) return hit;
      const on = (ground: string) => { cx.fillStyle = ground; cx.fillRect(0, 0, 1, 1); cx.fillStyle = css; cx.fillRect(0, 0, 1, 1); return cx.getImageData(0, 0, 1, 1).data; };
      const b = on('#000'), w = on('#fff');
      const a = 1 - (w[0] - b[0]) / 255;
      const out = a <= 0.004 ? [0, 0, 0, 0] : [b[0] / a, b[1] / a, b[2] / a, Math.min(1, a)];
      cache.set(css, out);
      return out;
    };
    const over = (top: number[], under: number[]) => [0, 1, 2].map((i) => top[i] * top[3] + under[i] * (1 - top[3])).concat(1);
    const lum = (c: number[]) => { const f = (v: number) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
    const ratio = (a: number[], b: number[]) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };
    const ground = rgba(getComputedStyle(document.documentElement).backgroundColor);
    /** What is behind an element, or null when a picture is. Also the opacity it is drawn at. */
    const behind = (el: Element) => {
      const layers: number[][] = [];
      let opacity = 1, solid = false;
      for (let at: Element | null = el; at; at = at.parentElement) {
        const cs = getComputedStyle(at);
        opacity *= Number(cs.opacity);
        if (solid) continue;
        if (cs.backgroundImage !== 'none' || at.matches('.avrana-cover, .avrana-cover *')) return null;
        const bg = rgba(cs.backgroundColor);
        if (bg[3] > 0) layers.push(bg);
        if (bg[3] >= 0.999) solid = true;
      }
      let bg = ground[3] ? ground : [13, 13, 15, 1];
      for (const layer of layers.reverse()) bg = over(layer, bg);
      return { bg, opacity };
    };
    const shown = (el: Element) => el.getClientRects().length > 0 && getComputedStyle(el).visibility === 'visible';
    const off = (el: Element) => Boolean(el.closest(':disabled, [aria-disabled="true"], [aria-hidden="true"], .sr-only'));
    const bad: string[] = [];
    const judge = (el: Element, colour: string, need: number, what: string) => {
      const back = behind(el);
      if (!back) return;
      const fg = rgba(colour);
      const seen = over([fg[0], fg[1], fg[2], fg[3] * back.opacity], back.bg);
      const r = ratio(seen, back.bg);
      if (r + 0.005 < need) bad.push(`${what}: ${r.toFixed(2)} of ${need} (${colour} on rgb(${back.bg.slice(0, 3).map(Math.round).join(' ')}))`);
    };
    const scope = document.querySelector(sel);
    if (!scope) return [`no ${sel}`];
    for (const el of scope.querySelectorAll('*')) {
      if (!shown(el) || off(el)) continue;
      const cs = getComputedStyle(el);
      if (el instanceof SVGSVGElement) {
        if (el.matches('.avrana-icon')) judge(el, cs.color, 3, `icon in ${(el.parentElement?.id || el.parentElement?.className || '').toString().slice(0, 40)}`);
        continue;
      }
      const words = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent || '').join('').trim();
      if (!words || el.closest('svg')) continue;
      const size = parseFloat(cs.fontSize), large = size >= 24 || (size >= 18.66 && Number(cs.fontWeight) >= 700);
      judge(el, cs.color, large ? 3 : min, `"${words.slice(0, 32)}"`);
    }
    return [...new Set(bad)];
  }, [root, floor] as const);
}

/** The edge of a control that is only an outline: 3:1 against what it sits on (MUST 9). */
export async function faintEdges(page: Page, selector = '.btn:not(.btn-primary, .btn-ghost, :disabled), .input, .avrana-choice:not(:disabled), .avrana-seg') {
  return page.$$eval(selector, (els) => {
    const cv = document.createElement('canvas');
    cv.width = cv.height = 1;
    const cx = cv.getContext('2d', { willReadFrequently: true })!;
    const rgb = (css: string, ground: string) => { cx.fillStyle = ground; cx.fillRect(0, 0, 1, 1); cx.fillStyle = css; cx.fillRect(0, 0, 1, 1); return [...cx.getImageData(0, 0, 1, 1).data].slice(0, 3); };
    const lum = (c: number[]) => { const f = (v: number) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
    const out: string[] = [];
    for (const el of els) {
      if (!el.getClientRects().length || el.closest('[aria-disabled="true"]')) continue;
      const cs = getComputedStyle(el);
      if (parseFloat(cs.borderTopWidth) < 1 || cs.borderTopStyle === 'none') continue;
      let host: Element | null = el.parentElement, ground = 'rgb(13, 13, 15)';
      for (; host; host = host.parentElement) { const bg = getComputedStyle(host).backgroundColor; if (!/, 0\)$|transparent/.test(bg)) { ground = bg; break; } }
      const under = rgb(ground, '#0d0d0f'), edge = rgb(cs.borderTopColor, `rgb(${under.join(',')})`);
      const [hi, lo] = [lum(edge), lum(under)].sort((a, b) => b - a), r = (hi + 0.05) / (lo + 0.05);
      if (r + 0.005 < 3) out.push(`${el.id || el.className.toString().slice(0, 30)}: edge ${r.toFixed(2)} of 3`);
    }
    return [...new Set(out)];
  });
}

/** Controls a screen reader would announce with no name, and names that point at nothing. */
export async function unnamed(page: Page, root = 'body') {
  return page.evaluate((sel) => {
    const scope = document.querySelector(sel);
    if (!scope) return [`no ${sel}`];
    const text = (ids: string | null) => (ids || '').split(/\s+/).filter(Boolean).map((id) => document.getElementById(id)?.textContent || '').join(' ').trim();
    const bad: string[] = [];
    for (const el of scope.querySelectorAll('a[href], button, input, select, textarea, summary, [role="button"], [tabindex]:not([tabindex="-1"])')) {
      if (!el.getClientRects().length) continue;
      const name = (el.getAttribute('aria-label') || text(el.getAttribute('aria-labelledby'))
        || [...((el as HTMLInputElement).labels || [])].map((l) => l.textContent).join(' ')
        || (el.matches('input, select, textarea') ? '' : el.textContent)
        || [...el.querySelectorAll('img[alt], svg[aria-label]')].map((i) => i.getAttribute('alt') || i.getAttribute('aria-label')).join(' ') || '').trim();
      if (!name) bad.push(`no name: ${el.tagName.toLowerCase()}#${el.id || '?'} ${el.className.toString().slice(0, 30)}`);
    }
    for (const el of scope.querySelectorAll('[aria-labelledby], [aria-controls], [aria-describedby]')) {
      if (!el.getClientRects().length) continue;            // not drawn: nothing reads it
      for (const attr of ['aria-labelledby', 'aria-controls', 'aria-describedby']) {
        for (const id of (el.getAttribute(attr) || '').split(/\s+/).filter(Boolean))
          if (!document.getElementById(id)) bad.push(`${attr}="${id}" on #${el.id || el.tagName.toLowerCase()} points at nothing`);
      }
      if (el.hasAttribute('aria-labelledby') && !text(el.getAttribute('aria-labelledby')))
        bad.push(`#${el.id || el.tagName.toLowerCase()} is labelled by something empty`);
    }
    return bad;
  }, root);
}

/** The page's skeleton, as a screen reader's rotor would list it. */
export async function outline(page: Page) {
  return page.evaluate(() => {
    const shown = (el: Element) => el.getClientRects().length > 0 && !el.closest('[aria-hidden="true"]');
    const open = document.querySelector('dialog[open]');
    const within = (el: Element) => (open ? open.contains(el) : !el.closest('dialog'));
    const heads = [...document.querySelectorAll('h1, h2, h3, h4')].filter((h) => shown(h) && within(h));
    return {
      lang: document.documentElement.lang,
      title: document.title,
      mains: [...document.querySelectorAll('main')].filter(shown).length,
      h1: heads.filter((h) => h.tagName === 'H1').map((h) => (h.textContent || '').trim()),
      levels: heads.map((h) => Number(h.tagName[1])),
      unlabelledNavs: [...document.querySelectorAll('nav')].filter((n) => shown(n) && !n.getAttribute('aria-label')).length,
      unlabelledDialogs: [...document.querySelectorAll('dialog[open]')].filter((d) => !(document.getElementById(d.getAttribute('aria-labelledby') || '')?.textContent || '').trim()).map((d) => d.id),
      statuses: [...document.querySelectorAll('[role="status"]')].filter(shown).length,
    };
  });
}

/** Controls that come later in the page than something drawn below them: where reading order
 * (the order of the page) and visual order disagree. Each region is judged by itself, because
 * the frame's bars stay put while its middle scrolls under them; and the regions must stand in
 * the page in the order they are drawn. */
export async function outOfOrder(page: Page, regions = ['#top', '#content', '#scene-scroll', '#scene .avrana-dock', '#nav']) {
  return page.evaluate((sels) => {
    const bad: string[] = [];
    const drawn = sels.map((sel) => document.querySelector(sel)).filter((el): el is Element => Boolean(el && el.getClientRects().length));
    for (let i = 1; i < drawn.length; i++) {
      if (!(drawn[i - 1].compareDocumentPosition(drawn[i]) & Node.DOCUMENT_POSITION_FOLLOWING)) bad.push(`region ${drawn[i].id || drawn[i].className} comes before ${drawn[i - 1].id || drawn[i - 1].className} in the page`);
      if (drawn[i].getBoundingClientRect().top + 1 < drawn[i - 1].getBoundingClientRect().top) bad.push(`region ${drawn[i].id || drawn[i].className} is drawn above ${drawn[i - 1].id || drawn[i - 1].className}`);
    }
    const label = (el: Element) => el.id || (el.textContent || '').trim().slice(0, 24);
    for (const region of drawn) {
      const els = [...region.querySelectorAll('a[href], button, input, select, summary')]
        .filter((el) => el.getClientRects().length > 0 && !(el as HTMLButtonElement).disabled && !el.matches('.sr-only'));
      for (let i = 1; i < els.length; i++) {
        const a = els[i - 1].getBoundingClientRect(), b = els[i].getBoundingClientRect();
        // sideways shelves scroll inside themselves: only what is drawn wholly above counts
        if (b.bottom <= a.top + 1) bad.push(`${label(els[i])} is drawn above ${label(els[i - 1])}`);
      }
    }
    return bad;
  }, regions);
}

/** Walk the page with Tab and report every stop that shows no focus ring (MUST 9). Returns the
 * number of stops too, so a walk that went nowhere cannot pass. */
export async function focusWalk(page: Page, max = 60) {
  const bad: string[] = [], seen: string[] = [];
  for (let i = 0; i < max; i++) {
    await page.keyboard.press('Tab');
    const at = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return null;
      const ring = (node: Element) => { const cs = getComputedStyle(node); return cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 2; };
      const host = el.closest('.input, .file-input');
      const key = `${el.tagName.toLowerCase()}#${el.id || (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 24)}`;
      return { key, ok: ring(el) || Boolean(host && ring(host)) };
    });
    if (!at) break;
    if (seen.includes(at.key)) break;                      // came round again
    seen.push(at.key);
    if (!at.ok) bad.push(`no focus ring: ${at.key}`);
  }
  return { stops: seen.length, bad };
}

/** Anything still moving: running animations, and transitions that take time (MUST 8, with
 * `prefers-reduced-motion: reduce` emulated). */
export async function moving(page: Page) {
  return page.evaluate(() => {
    const running = document.getAnimations().filter((a) => a.playState === 'running').map((a) => `animation on ${((a.effect as KeyframeEffect)?.target as Element)?.className || '?'}`);
    const slow = [...document.querySelectorAll('*')].filter((el) => el.getClientRects().length > 0)
      .filter((el) => getComputedStyle(el).transitionDuration.split(',').some((d) => parseFloat(d) > 0))
      .map((el) => `transition on ${el.id || el.className.toString().slice(0, 30)}`);
    return [...new Set([...running, ...slow])];
  });
}
