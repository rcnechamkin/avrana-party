import { expect, type Browser, type BrowserContext, type Page, type TestInfo } from '@playwright/test';

/**
 * Phones for the installed-package suite (AVR-338): one browser context each (its own Secure cookie
 * jar, its own storage), with a recorder of everything that phone RECEIVED over HTTP and WebSocket, so
 * a test can say "this phone was never told that secret".
 */
export const PARTY = 'https://party.avrana.net';
export const GAMES = 'https://games.avrana.net';

export type Phone = {
  name: string; context: BrowserContext; page: Page;
  bodies: string[];           // every text/JSON response body this phone received (any origin)
  frames: string[];           // every WebSocket frame it received
  gameMainFrameCalls: string[]; // requests the game page's own frame made to the Party API (must stay empty)
};

export async function phone(browser: Browser, info: TestInfo, name: string): Promise<Phone> {
  const { viewport, userAgent, isMobile, hasTouch, deviceScaleFactor } = info.project.use as any;
  const context = await browser.newContext({
    baseURL: PARTY, ignoreHTTPSErrors: true, serviceWorkers: 'block',
    viewport, userAgent, isMobile, hasTouch, deviceScaleFactor,
  });
  // A saved profile is who this phone is at the party; presence then follows (ADR 0011). Only on the
  // Party origin: the game origin keeps no storage of ours.
  await context.addInitScript((who) => {
    if (location.hostname === 'party.avrana.net') { try { localStorage.setItem('wc-name', who); } catch { /* private */ } }
  }, name);
  const page = await context.newPage();
  const p: Phone = { name, context, page, bodies: [], frames: [], gameMainFrameCalls: [] };
  context.on('response', async (res) => {
    try {
      const type = res.headers()['content-type'] || '';
      if (/json|text|javascript/.test(type)) p.bodies.push(await res.text());
    } catch { /* aborted long poll, redirect, closed context */ }
  });
  page.on('websocket', (ws) => ws.on('framereceived', (f) => p.frames.push(String(f.payload))));
  page.on('request', (r) => {
    if (r.frame() === page.mainFrame() && page.url().startsWith(GAMES) && r.url().includes('/party/api/')) p.gameMainFrameCalls.push(r.url());
  });
  page.on('pageerror', (e) => console.log(`[${name}] pageerror: ${e.message}`));
  return p;
}

/** Open Party Home as this phone: the real shell, which joins the party by itself once it has a name. */
export async function joinParty(p: Phone, { intoRound = false } = {}) {
  await p.page.goto('/party/');
  // A phone that arrives while a round is on is taken straight to the game: it never settles on Party Home.
  if (!intoRound) await expect(p.page.locator('html')).toHaveAttribute('data-ready', 'true');
}

/** The Party's own JSON, as this phone's page asks it (cookie and Origin included). */
export async function partyState(p: Phone) {
  const res = await p.page.request.get(`${PARTY}/party/api/state`);
  expect(res.ok()).toBeTruthy();
  return res.json();
}

export async function post(p: Phone, path: string, body: Record<string, unknown>) {
  return p.page.request.post(`${PARTY}/party/api/${path}`, { data: body, headers: { 'Content-Type': 'application/json', Origin: PARTY } });
}

/** Leave the party as a failed or finished test should: a round still on is ended by the Host first, so the
 * next test (and the script's `install-game remove`) never finds a live session. The Host is the first phone. */
export async function leaveAll(phones: Phone[]) {
  const [host] = phones;
  try {
    const state = await partyState(host);
    if (state.session && !['ended'].includes(state.session.state)) await post(host, 'session/end', { if_version: state.version });
  } catch { /* nothing to end, or the context is gone */ }
  for (const p of [...phones].reverse()) { try { await post(p, 'leave', {}); } catch { /* the context may be gone */ } }
}
