import { test, expect, Page } from '@playwright/test';

// Party Home keeps its event stream alive (index.html, "Staying live"). Two kinds of test:
//  - scripted: a stand-in EventSource with browser semantics plus Playwright's clock make every
//    failure exact and every timer deterministic, while the real page code runs in a real browser;
//  - real: the real front door and the browser's own EventSource, with the failure put on the wire
//    (a stream that ends, then 502s as nginx answers while the party restarts).
// Page visibility and bfcache returns are simulated events here. A real phone locking, sleeping and
// waking on the Party Wi-Fi is not, and still needs a phone.

// Mirrors of index.html's timings.
const PING = 10_000, SILENT = 25_000, OPEN = 10_000, STALL = 15_000;
const AWAY = 'Can’t reach the party. Are you on the Avrana Party Wi-Fi?';
const STILL_AWAY = 'Still can’t reach the party. Are you on the Avrana Party Wi-Fi?';
const JARGON = /\b(seat|session|runtime|server|websocket|presence|manifest|launch(ing)?|backend|token|slot)\b/i;
const VIEW = JSON.stringify({ party: { id: 'p', state: 'lobby', version: 1, launching: null,
  nav: { seq: 0, target: 'home', href: null } }, me: null, host: null, players: 2 });

test.beforeEach(async ({ request, baseURL }) => {
  const r = await request.post('/party/dev/reset-party', { headers: { Origin: baseURL! }, data: {} });
  expect(r.ok()).toBeTruthy();                                    // each test starts a fresh party
});

// ---- scripted ------------------------------------------------------------------------------------
// A stand-in EventSource with the browser's semantics: CONNECTING, then OPEN; a closed stream
// delivers nothing; an error leaves it CONNECTING (a network error: the browser would retry by
// itself) or CLOSED (an HTTP error or wrong type: the browser never retries). With __failNew set,
// every new stream fails like a party that answers 502.
function fakeEventSource() {
  const w = window as any;
  w.__streams = [];
  w.__failNew = false;
  class FakeEventSource extends EventTarget {
    url: string;
    readyState = 0;
    onerror: ((e: Event) => void) | null = null;
    onopen: ((e: Event) => void) | null = null;
    onmessage: ((e: Event) => void) | null = null;
    constructor(url: string) {
      super();
      this.url = url;
      w.__streams.push(this);
      if (w.__failNew) queueMicrotask(() => this.fail(true));
    }
    close() { this.readyState = 2; }
    fire(ev: Event) {
      this.dispatchEvent(ev);
      const handler = (this as any)['on' + ev.type];
      if (typeof handler === 'function') handler.call(this, ev);
    }
    open() { if (this.readyState === 0) { this.readyState = 1; this.fire(new Event('open')); } }
    send(type: string, data: string) { if (this.readyState === 1) this.fire(new MessageEvent(type, { data })); }
    fail(closed: boolean) { if (this.readyState !== 2) { this.readyState = closed ? 2 : 0; this.fire(new Event('error')); } }
  }
  w.EventSource = FakeEventSource;
}

/** readyState of every stream the page has made, oldest first (0 opening, 1 open, 2 closed). */
const streams = (p: Page) => p.evaluate(() => (window as any).__streams.map((s: any) => s.readyState) as number[]);
const notClosed = async (p: Page) => (await streams(p)).filter((s) => s !== 2).length;

/** Drive the newest stream: 'live' = open + a state event; 'ping'; 'http-error'; 'network-error'. */
async function newest(p: Page, what: 'live' | 'ping' | 'http-error' | 'network-error') {
  await p.evaluate(([what, view]) => {
    const all = (window as any).__streams, s = all[all.length - 1];
    if (what === 'live') { s.open(); s.send('state', view); }
    else if (what === 'ping') s.send('ping', '{}');
    else s.fail(what === 'http-error');
  }, [what, VIEW] as const);
}

async function failNew(p: Page, on: boolean) { await p.evaluate((v) => { (window as any).__failNew = v; }, on); }

async function setVisible(p: Page, visible: boolean) {
  await p.evaluate((v) => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (v ? 'visible' : 'hidden') });
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => !v });
    document.dispatchEvent(new Event('visibilitychange'));
  }, visible);
}

const backFromCache = (p: Page) => p.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
const backOnline = (p: Page) => p.evaluate(() => window.dispatchEvent(new Event('online')));

async function scripted(p: Page) {
  await p.addInitScript(fakeEventSource);
  await p.clock.install();
  await p.goto('/party/');
  await expect.poll(() => streams(p)).toEqual([0]);            // opened after the first /party/state
  await p.clock.pauseAt(await p.evaluate(() => Date.now() + 50));   // from here, time moves on request
}

test('normal connect: one stream, live once the party answers, kept live by pings', async ({ page }) => {
  await scripted(page);
  await expect(page.locator('#conn')).toHaveText('Connecting…');
  await newest(page, 'live');
  await expect(page.locator('#conn')).toHaveText('');
  await expect(page.locator('#reconnect')).toBeHidden();
  await expect(page.getByText('2 people are here.')).toBeVisible();      // the stream's view is shown
  for (let i = 0; i < 6; i++) {                                           // a quiet minute in the lobby
    await page.clock.runFor(PING);
    await newest(page, 'ping');
  }
  expect(await streams(page)).toEqual([1]);                               // never replaced
  await expect(page.locator('#conn')).toHaveText('');
});

test('a server error: Reconnecting…, retries on a bounded backoff, then live again', async ({ page }) => {
  await scripted(page);
  await newest(page, 'live');
  await newest(page, 'http-error');                  // e.g. a 502: EventSource is CLOSED for good
  await expect(page.locator('#conn')).toHaveText('Reconnecting…');
  for (const wait of [1000, 2000, 4000, 8000, 15000, 15000]) {           // capped, never faster
    const made = (await streams(page)).length;
    await page.clock.runFor(wait - 1);
    expect((await streams(page)).length, `no retry before ${wait} ms`).toBe(made);
    await page.clock.runFor(1);
    expect((await streams(page)).length, `a retry after ${wait} ms`).toBe(made + 1);
    await newest(page, 'http-error');
  }
  await page.clock.runFor(15000);
  await newest(page, 'live');
  await expect(page.locator('#conn')).toHaveText('');
  await expect(page.locator('#reconnect')).toBeHidden();
  expect(await notClosed(page)).toBe(1);
  // Recovered means a fresh start: the next failure is retried after 1 s again.
  await newest(page, 'http-error');
  const made = (await streams(page)).length;
  await page.clock.runFor(1000);
  expect((await streams(page)).length).toBe(made + 1);
});

test('waking the phone replaces a stream that died in its sleep; a quick look away does not', async ({ page }) => {
  await scripted(page);
  await newest(page, 'live');
  await setVisible(page, false);                     // a quick look at another app
  await page.clock.runFor(4000);
  await setVisible(page, true);
  expect(await streams(page)).toEqual([1]);          // still fresh: left alone

  await setVisible(page, false);                     // locked for five minutes: the page is frozen
  await page.clock.setSystemTime(await page.evaluate(() => Date.now() + 5 * 60_000));   // (no timers ran)
  await setVisible(page, true);
  expect(await streams(page)).toEqual([2, 0]);       // replaced at once, without waiting for a timer
  await expect(page.locator('#conn')).toHaveText('Reconnecting…');
  await newest(page, 'live');
  await expect(page.locator('#conn')).toHaveText('');

  await backFromCache(page);                         // back from the bfcache: always a fresh stream
  expect(await streams(page)).toEqual([2, 2, 0]);
  await newest(page, 'live');
  await backOnline(page);                            // back online with a fresh stream: left alone
  expect(await streams(page)).toEqual([2, 2, 1]);
  await setVisible(page, false);                     // hidden past a ping, then back: rebuilt
  await page.clock.setSystemTime(await page.evaluate((ms) => Date.now() + ms, PING + 2000));
  await setVisible(page, true);
  expect(await streams(page)).toEqual([2, 2, 2, 0]);
});

test('a stream that goes silent is replaced after the silence window, a stuck attempt after the open window', async ({ page }) => {
  await scripted(page);
  await newest(page, 'live');
  await page.clock.runFor(SILENT - 1);
  expect(await streams(page)).toEqual([1]);
  await expect(page.locator('#conn')).toHaveText('');
  await page.clock.runFor(1);                        // no state and no ping for 25 s: dead
  expect(await streams(page)).toEqual([2]);
  await expect(page.locator('#conn')).toHaveText('Reconnecting…');
  await page.clock.runFor(1000);
  expect(await streams(page)).toEqual([2, 0]);
  await page.clock.runFor(OPEN - 1);                 // this attempt never answers (black-holed)
  expect(await streams(page)).toEqual([2, 0]);
  await page.clock.runFor(1);
  expect(await streams(page)).toEqual([2, 2]);
  await page.clock.runFor(2000);
  await newest(page, 'live');
  await expect(page.locator('#conn')).toHaveText('');
});

test('never more than one stream, however the reconnects pile up', async ({ page }) => {
  await scripted(page);
  const atMostOne = async (when: string) => expect(await notClosed(page), when).toBeLessThanOrEqual(1);
  await newest(page, 'live');
  await newest(page, 'network-error');               // CONNECTING: the browser alone would retry too
  expect(await streams(page)).toEqual([2]);          // so the page closes it and owns the retry
  await page.clock.runFor(1000);
  await setVisible(page, true);                      // an attempt is under way: nothing new
  await backOnline(page);
  expect(await streams(page)).toEqual([2, 0]);
  await backFromCache(page);
  await atMostOne('after a bfcache return');
  await backFromCache(page);
  await atMostOne('after a second bfcache return');
  expect(await streams(page)).toEqual([2, 2, 2, 0]);

  await failNew(page, true);                         // a minute of 502s
  await newest(page, 'http-error');
  const before = (await streams(page)).length;
  for (let t = 5000; t <= 60_000; t += 5000) {
    await page.clock.runFor(5000);
    await atMostOne(`${t} ms into the failures`);
  }
  const retries = (await streams(page)).length - before;
  expect(retries).toBeGreaterThanOrEqual(5);         // still trying...
  expect(retries).toBeLessThanOrEqual(7);            // ...on the backoff, not in a storm

  const retry = page.locator('#reconnect');
  for (let i = 0; i < 3; i++) {
    await retry.click();
    await atMostOne('after Try again');
  }
  await failNew(page, false);
  await retry.click();
  await expect(retry).toHaveText('Trying…');
  const made = (await streams(page)).length;
  await retry.dispatchEvent('click');                // a second tap while trying adds nothing
  expect((await streams(page)).length).toBe(made);
  await newest(page, 'live');
  expect((await streams(page)).filter((s) => s !== 2)).toEqual([1]);
});

test('when recovery stalls: a plain message and Try again, which reconnects at once', async ({ page }, info) => {
  await scripted(page);
  await newest(page, 'live');
  await failNew(page, true);                         // the party answers 502 every time
  await newest(page, 'http-error');
  await page.clock.runFor(STALL - 1);
  await expect(page.locator('#conn')).toHaveText('Reconnecting…');
  await expect(page.locator('#reconnect')).toBeHidden();
  await page.clock.runFor(1);
  await expect(page.locator('#conn')).toHaveText(AWAY);
  const retry = page.getByRole('button', { name: 'Try again' });
  await expect(retry).toBeVisible();
  expect((await retry.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.body.innerText)).not.toMatch(JARGON);
  await page.screenshot({ path: info.outputPath('stalled.png') });

  let made = (await streams(page)).length;           // the next automatic retry is 15 s away...
  await retry.click();                               // ...a tap tries now
  expect((await streams(page)).length).toBe(made + 1);
  await expect(page.locator('#conn')).toHaveText(STILL_AWAY);
  await expect(retry).toBeVisible();

  await failNew(page, false);                        // the party is back
  made = (await streams(page)).length;
  await retry.click();
  expect((await streams(page)).length).toBe(made + 1);
  await expect(page.locator('#conn')).toHaveText('Reconnecting…');
  await expect(page.locator('#reconnect')).toHaveText('Trying…');
  await newest(page, 'live');
  await expect(page.locator('#conn')).toHaveText('');
  await expect(page.locator('#reconnect')).toBeHidden();
});

// ---- real ------------------------------------------------------------------------------------------
test('real browser and party: a stream that ends, then 502s while the party restarts, recovers by itself', async ({ page, browser, request }) => {
  const view = await (await request.get('/party/state')).text();
  let n = 0;
  await page.route('**/party/events', (route) => {
    n += 1;
    if (n === 1) {                                   // one state event, then the stream ends
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: `retry: 2000\n\nevent: state\ndata: ${view}\n\n` });
    }
    if (n <= 3) return route.fulfill({ status: 502, contentType: 'text/html', body: '<h1>502 Bad Gateway</h1>' });
    return route.continue();                         // the party is back
  });
  await page.goto('/party/');
  await expect(page.locator('#conn')).toHaveText('Reconnecting…');
  await expect(page.locator('#conn')).toHaveText('', { timeout: 15_000 });
  expect(n).toBe(4);

  const ctx = await browser.newContext();            // and it is the party's live stream again:
  const ben = await ctx.newPage();                   // another phone joining shows up, no reload
  await ben.goto('/party/');
  await ben.getByLabel('What should we call you?').fill('Ben');
  await ben.getByRole('button', { name: 'Join the party' }).click();
  await expect(page.getByText('1 person is here. Ben is hosting.')).toBeVisible();
  await ctx.close();
});

test('real browser and party: a quiet, healthy stream is left alone past the silence window', async ({ page }) => {
  test.slow();                                       // waits out SILENT in real time
  let requests = 0;
  page.on('request', (r) => { if (new URL(r.url()).pathname === '/party/events') requests += 1; });
  await page.goto('/party/');
  await expect(page.getByRole('button', { name: 'Join the party' })).toBeVisible();
  await expect(page.locator('#conn')).toHaveText('');
  await page.waitForTimeout(SILENT + 2000);          // only the party's pings arrive meanwhile
  expect(requests).toBe(1);
  await expect(page.locator('#conn')).toHaveText('');
});
