import { test, expect, type Page } from '@playwright/test';

/**
 * The arcade phone page (arcade/index.html) against the simulated Party (Tier 2).
 *
 * No emulator or encoder here: WebSocket and RTCPeerConnection are replaced by small fakes that
 * follow the arcade's signalling (player → offer → answer → connected), so the page's own state
 * machine is tested: honest "full" vs "lost", quiet reconnect after a drop, waiting while the
 * phone is locked, Leave, and keeping the screen on. Real streaming stays Tier 3 (the Pi).
 */
async function arcade(page: Page, mode: 'up' | 'down' | 'full' | 'hang') {
  expect((await page.request.post(`/__test__/arcade/${mode}`)).status()).toBe(204);
}

async function fakeWakeLock(page: Page) {
  await page.addInitScript(() => {
    (window as any).__wake = { requests: 0, releases: 0, held: 0 };
    Object.defineProperty(navigator, 'wakeLock', {
      configurable: true,
      value: {
        request: async () => {
          const w = (window as any).__wake;
          w.requests += 1; w.held += 1;
          const handlers: Array<() => void> = [];
          return {
            released: false,
            addEventListener: (_: string, fn: () => void) => handlers.push(fn),
            async release() {
              if (!this.released) { this.released = true; w.releases += 1; w.held -= 1; handlers.forEach((f) => f()); }
            },
          };
        },
      },
    });
  });
}

async function fakeTransport(page: Page) {
  await page.addInitScript(() => {
    const sockets: any[] = [];
    (window as any).__sockets = sockets;
    // Knobs for tests: delay the remote description (a slow signalling step), make every new
    // socket fail at once (the arcade is gone), have the arcade refuse because its video is not
    // flowing (stream.py's "no-media"), leave ICE hanging so the peer never connects, or hand this
    // phone another of the arcade's controller slots (1 to 4: the arcade chooses, the page shows).
    (window as any).__slot = 1;
    (window as any).__slowOfferMs = 0;
    (window as any).__refuseSockets = false;
    (window as any).__noMedia = false;
    (window as any).__neverConnect = false;
    class FakeSocket {
      static OPEN = 1;
      url: string; readyState = 0; bufferedAmount = 0; sent: string[] = [];
      onmessage: ((e: { data: string }) => void) | null = null;
      onclose: ((e: { code: number }) => void) | null = null;
      onerror: (() => void) | null = null;
      onopen: (() => void) | null = null;
      constructor(url: string) {
        this.url = url;
        sockets.push(this);
        if ((window as any).__refuseSockets) {
          setTimeout(() => { this.readyState = 3; this.onerror?.(); this.onclose?.({ code: 1006 }); }, 10);
          return;
        }
        setTimeout(() => {
          if (this.readyState === 3) return;  // closed sockets deliver nothing, as in browsers
          this.readyState = 1;
          this.onopen?.();
          if ((window as any).__noMedia) {
            this.onmessage?.({ data: JSON.stringify({ type: 'error', reason: 'no-media', media: ['video'] }) });
            this.readyState = 3;
            this.onclose?.({ code: 1000 });
            return;
          }
          this.onmessage?.({ data: JSON.stringify({ type: 'player', slot: (window as any).__slot }) });
          this.onmessage?.({ data: JSON.stringify({ type: 'offer', sdp: 'v=0 fake' }) });
        }, 20);
      }
      send(data: string) { this.sent.push(data); }
      close() { this.readyState = 3; }
      drop() { this.readyState = 3; this.onclose?.({ code: 1006 }); }
    }
    class FakePeer {
      connectionState = 'new'; remoteDescription: any = null; localDescription: any = null;
      onconnectionstatechange: (() => void) | null = null; ontrack = null; onicecandidate = null;
      async setRemoteDescription(d: any) {
        const wait = (window as any).__slowOfferMs;
        if (wait) await new Promise((r) => setTimeout(r, wait));
        if (this.connectionState === 'closed') throw new Error('InvalidStateError: closed');
        this.remoteDescription = d;
      }
      async createAnswer() { return { type: 'answer', sdp: 'fake' }; }
      async setLocalDescription(d: any) {
        this.localDescription = d;
        if ((window as any).__neverConnect) { this.connectionState = 'connecting'; return; }
        setTimeout(() => { this.connectionState = 'connected'; this.onconnectionstatechange?.(); }, 20);
      }
      async addIceCandidate() {}
      async getStats() { return new Map(); }
      close() { this.connectionState = 'closed'; }
    }
    (window as any).WebSocket = FakeSocket;
    (window as any).RTCPeerConnection = FakePeer;
  });
}

async function setHidden(page: Page, hidden: boolean) {
  await page.evaluate((h) => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => h });
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (h ? 'hidden' : 'visible') });
    document.dispatchEvent(new Event('visibilitychange'));
  }, hidden);
}

async function open(page: Page) {
  await page.goto('/arcade/', { waitUntil: 'networkidle' });  // includes the keep-awake module
}

test.beforeEach(async ({ page }) => arcade(page, 'up'));

test('Party admission fetches a fresh authenticated game ticket before each socket and sends it only in hello', async ({ page }) => {
  await fakeTransport(page);
  let tickets = 0;
  await page.route('**/arcade/stats', route => route.fulfill({ json: {
    party_managed: true, state: 'running', players: 0, max_players: 4, emulator_running: true,
  } }));
  await page.route('**/party/api/session/ticket', async route => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({ game: 'arcade-gauntlet2' });
    expect(await page.evaluate(() => (window as any).__sockets.length)).toBe(tickets);
    tickets++;
    await route.fulfill({ json: { ticket: `secret-ticket-${tickets}`, role: 'player' } });
  });
  await page.goto('/arcade/?ticket=do-not-forward&audio=0');
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  await page.evaluate(() => (window as any).__sockets[0].drop());
  await expect.poll(() => page.evaluate(() => (window as any).__sockets.length)).toBe(2);
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  const sockets = await page.evaluate(() => (window as any).__sockets.map((s: any) => ({ url: s.url, sent: s.sent.map(JSON.parse) })));
  expect(tickets).toBe(2);
  for (const [i, s] of sockets.entries()) {
    expect(new URL(s.url).search).toBe('?audio=0');
    expect(s.sent[0]).toEqual({ type: 'hello', ticket: `secret-ticket-${i + 1}` });
  }
  await page.locator('#leave').click();
  expect(await page.evaluate(() => (window as any).__sockets[1].sent.map(JSON.parse))).toContainEqual({ type: 'leave' });
});

test('Party ticket refusal never opens a socket or enables controls', async ({ page }) => {
  await fakeTransport(page);
  await page.route('**/arcade/stats', route => route.fulfill({ json: { party_managed: true, state: 'running' } }));
  await page.route('**/party/api/session/ticket', route => route.fulfill({ status: 403, json: { message: 'Join the party first.' } }));
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Join the party first.');
  expect(await page.evaluate(() => (window as any).__sockets.length)).toBe(0);
  await expect(page.locator('[data-key="coin"]')).toBeDisabled();
});

test('a replaced tab gives up its binding without automatically taking it back', async ({ page }) => {
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  await page.evaluate(() => {
    const socket = (window as any).__sockets[0];
    socket.onmessage({ data: JSON.stringify({ type: 'error', reason: 'replaced' }) });
    socket.drop();
  });
  await expect(page.locator('#status')).toHaveText('Your controller is open in another tab. Tap Play here to take it back.');
  await page.waitForTimeout(1200);
  expect(await page.evaluate(() => (window as any).__sockets.length)).toBe(1);
  await expect(page.locator('[data-key="coin"]')).toBeDisabled();
});

test('the page contract the live suite relies on is unchanged', async ({ page }) => {
  await open(page);
  await expect(page).toHaveTitle(/Gauntlet II/);
  await expect(page.locator('#connect')).toHaveText(/Play Gauntlet II/);
  await expect(page.locator('#status')).toContainText(/Ready to play/i);
  await expect(page.locator('[data-key]')).toHaveCount(8);
  // Full Mode (a secure context, as here and on https://party.avrana.net): back to Party Home.
  await expect(page.getByRole('link', { name: 'Other games' })).toHaveAttribute('href', '/party/');
  await expect(page.locator('#leave')).toBeDisabled();
  await expect(page.locator('#sound')).toBeDisabled();
  await expect(page.locator('#leave')).toBeHidden();             // nothing to leave until a seat is held
  await expect(page.locator('#who')).toBeHidden();
  await expect(page.locator('#details')).toBeHidden();           // raw stats only with #diag
  expect(await page.locator('#metrics').textContent()).toBe('Not connected');
  await page.goto('/arcade/#diag');
  await page.reload();
  await expect(page.locator('#details')).toBeVisible();
});

test('a full game says so, and the screen lock is let go', async ({ page }) => {
  await fakeWakeLock(page);
  await arcade(page, 'full');
  await open(page);
  await page.locator('#connect').click();   // no fake transport: the real socket fails like a 409
  await expect(page.locator('#status')).toHaveText('All controllers are in use. Try again when one is free.');
  await expect(page.locator('#status')).toContainText(/slot|in use|free/i);  // the live harness's rejection check
  await expect(page.locator('[data-key="coin"]')).toBeDisabled();
  await expect(page.locator('#connect')).toBeEnabled();
  expect(await page.evaluate(() => (window as any).__wake)).toMatchObject({ requests: 1, held: 0 });
});

test('full is the arcade’s own count of its own controllers, whatever that number is', async ({ page }) => {
  // three of four in use is not full; four of four is; the page never knew either number
  for (const [players, max, full] of [[3, 4, false], [4, 4, true], [2, 2, true]] as const) {
    await page.route('**/arcade/stats', (route) => route.fulfill({ json: { players, max_players: max, error: null, emulator_running: true } }));
    await open(page);
    await page.locator('#connect').click();   // no fake transport: the real socket fails like a refused one
    await expect(page.locator('#status'), `${players} of ${max}`).toHaveText(full
      ? 'All controllers are in use. Try again when one is free.'
      : 'Can’t connect right now. Stay on the Avrana Party Wi-Fi, then tap Play.');
    await page.unroute('**/arcade/stats');
  }
});

test('each of the four controller slots is shown as its own Player, and Leave puts the title back', async ({ page }) => {
  await fakeTransport(page);
  await open(page);
  for (const slot of [1, 2, 3, 4]) {
    await page.evaluate((n) => { (window as any).__slot = n; }, slot);   // the slot the arcade hands this phone
    await page.locator('#connect').click();
    await expect(page.locator('#status')).toHaveText(`Player ${slot} connected. Add a coin to join.`);
    await expect(page.locator('h1')).toHaveText(`Gauntlet II Player ${slot}`);
    await expect(page.locator('#who')).toHaveText(`Player ${slot}`);
    for (const key of ['up', 'down', 'left', 'right', 'fire', 'magic', 'coin', 'start']) {
      await expect(page.locator(`[data-key="${key}"]`), `${key} as Player ${slot}`).toBeEnabled();
    }
    await page.locator('#leave').click();
    await expect(page.locator('#status')).toHaveText('You left the game. Tap Play to join again.');
    await expect(page.locator('h1')).toHaveText('Gauntlet II');
    await expect(page.locator('#who')).toBeHidden();
    await expect(page.locator('#connect')).toBeEnabled();
  }
  expect(await page.evaluate(() => (window as any).__sockets.length)).toBe(4);   // one connection per Play
});

test('a failed first connection is not called "full"', async ({ page }) => {
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Can’t connect right now. Stay on the Avrana Party Wi-Fi, then tap Play.');
});

test('connect, drop, and a quiet reconnect that keeps the screen on', async ({ page }) => {
  await fakeWakeLock(page);
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  await expect(page.locator('#leave')).toBeEnabled();
  await expect(page.locator('[data-key="coin"]')).toBeEnabled();
  await expect.poll(() => page.evaluate(() => (window as any).__wake.held)).toBe(1);

  await page.evaluate(() => (window as any).__sockets[0].drop());
  await expect(page.locator('#status')).toHaveText(/Reconnecting…|Player 1 connected/);
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  expect(await page.evaluate(() => (window as any).__sockets.length)).toBe(2);
  expect(await page.evaluate(() => (window as any).__wake.held)).toBe(1);
});

test('a locked phone waits, then reconnects when it wakes', async ({ page }) => {
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  await setHidden(page, true);
  await page.evaluate(() => (window as any).__sockets[0].drop());
  await expect(page.locator('#status')).toHaveText('Reconnecting…');
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => (window as any).__sockets.length)).toBe(1);  // no retries while locked
  await setHidden(page, false);
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  expect(await page.evaluate(() => (window as any).__sockets.length)).toBe(2);
});

test('Leave is final: no reconnect, and the screen may sleep again', async ({ page }) => {
  await fakeWakeLock(page);
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#leave')).toBeEnabled();
  await page.locator('#leave').click();
  await expect(page.locator('#status')).toHaveText('You left the game. Tap Play to join again.');
  await expect(page.locator('#connect')).toBeEnabled();
  await page.waitForTimeout(800);
  expect(await page.evaluate(() => (window as any).__sockets.length)).toBe(1);
  expect(await page.evaluate(() => (window as any).__wake.held)).toBe(0);
});

test('a reconnect keeps trying while the arcade still counts the old connection', async ({ page }) => {
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  await arcade(page, 'full');   // /stats still counts this phone's dropped slot
  await page.evaluate(() => (window as any).__sockets[0].drop());
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  expect(await page.evaluate(() => (window as any).__sockets.length)).toBe(2);
});

test('a slow answer from the arcade does not leave a stale screen', async ({ page }) => {
  await arcade(page, 'hang');
  await open(page);
  await page.locator('#connect').click();   // the real socket fails; /stats never answers
  await expect(page.locator('#status')).toHaveText(/Checking…|Can’t connect right now/);
  await expect(page.locator('#status')).toHaveText('Can’t connect right now. Stay on the Avrana Party Wi-Fi, then tap Play.',
    { timeout: 4000 });
  await expect(page.locator('#connect')).toBeEnabled();
});

test('a late failure from an older attempt does not cancel the reconnect', async ({ page }) => {
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  // Attempt 2's offer step takes 1.5 s; drop attempt 2 as soon as it exists, so that step fails
  // (on a closed peer) after attempt 2 was torn down, typically while attempt 3 is running.
  await page.evaluate(() => { (window as any).__slowOfferMs = 1500; (window as any).__sockets[0].drop(); });
  await expect.poll(() => page.evaluate(() => (window as any).__sockets.length), { intervals: [20] }).toBe(2);
  await page.waitForTimeout(150);   // attempt 2 received its offer and is inside the slow step
  await page.evaluate(() => { (window as any).__slowOfferMs = 0; (window as any).__sockets[1].drop(); });
  await page.waitForTimeout(1700);  // past the stale step's failure
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.', { timeout: 8000 });
  expect(await page.evaluate(() => (window as any).__sockets.length)).toBe(3);
});

test('after five failed retries the phone says so and offers Play', async ({ page }) => {
  test.setTimeout(40_000);
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  await page.evaluate(() => { (window as any).__refuseSockets = true; (window as any).__sockets[0].drop(); });
  await expect(page.locator('#status')).toHaveText('Connection lost. Tap Play to reconnect.', { timeout: 20_000 });
  expect(await page.evaluate(() => (window as any).__sockets.length)).toBe(6);  // 1 + 5 retries
  await expect(page.locator('#connect')).toBeEnabled();
});

// AVR-92: a Play that cannot produce a picture must say so, and the way out is Party Home.

test('on plain HTTP (no /party/ there) Other games keeps the games hub', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(window, 'isSecureContext', { value: false }));
  await open(page);
  await expect(page.getByRole('link', { name: 'Other games' })).toHaveAttribute('href', '/');
});

test('Other games returns to Party Home, and Back returns to a clean arcade page', async ({ page }) => {
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  await page.getByRole('link', { name: 'Other games' }).click();
  await expect(page).toHaveURL(/\/party\/$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/arcade\/$/);
  await expect(page.locator('#connect')).toBeEnabled();
  await expect(page.locator('#connect')).toHaveText(/Play Gauntlet II/);
  await expect(page.locator('#leave')).toBeDisabled();
});

test('Play shows it is working: a busy, not faded, button until the picture', async ({ page }) => {
  await fakeTransport(page);
  await open(page);
  // A slow offer step holds "Connecting video…" long enough to see on a loaded test machine.
  await page.evaluate(() => { (window as any).__slowOfferMs = 4000; });
  await page.locator('#connect').click();
  const connect = page.locator('#connect');
  await expect(connect).toHaveAttribute('aria-busy', 'true');
  await expect(connect).toBeDisabled();
  expect(await connect.evaluate((b) => getComputedStyle(b).opacity)).toBe('1');
  await expect(page.locator('#status')).toHaveText('You are Player 1. Connecting video…');
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  await expect(connect).toHaveText(/Starting video/);   // connected; waiting for the first frame
  await page.evaluate(() => document.querySelector('video')!.dispatchEvent(new Event('playing')));
  await expect(page.locator('#start-overlay')).toBeHidden();
  await expect(connect).not.toHaveAttribute('aria-busy', 'true');
});

test('the arcade refusing for lack of video says so, not "check your Wi-Fi"', async ({ page }) => {
  await fakeTransport(page);
  await open(page);
  await page.evaluate(() => { (window as any).__noMedia = true; });
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Gauntlet II isn’t sending a picture right now. Wait a minute, then tap Play.');
  await expect(page.locator('#connect')).toBeEnabled();
  await expect(page.locator('#connect')).not.toHaveAttribute('aria-busy', 'true');
  expect(await page.evaluate(() => (window as any).__sockets.length)).toBe(1);   // no retry loop
});

test('a stopped arcade (the Pi answers, the game does not) is named as such', async ({ page }) => {
  await arcade(page, 'down');
  await open(page);
  await page.locator('#connect').click();   // the real socket fails; /arcade/stats is a 502
  await expect(page.locator('#status')).toHaveText('Gauntlet II isn’t running right now. Wait a minute, then tap Play, or pick another game.');
  await expect(page.locator('#connect')).toBeEnabled();
});

test('a Party-managed arcade that the host has not started says who starts it (AVR-134)', async ({ page }) => {
  await arcade(page, 'down');
  await page.route('**/arcade/stats', (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ players: 0, max_players: 4, error: null, emulator_running: false, state: 'idle', party_managed: true }) }));
  await open(page);
  await page.locator('#connect').click();   // the arcade answers 503: nothing runs until the host starts it
  await expect(page.locator('#status')).toHaveText('Gauntlet II isn’t on right now. The Party Host starts it for everyone from Party Home.');
  await expect(page.locator('#connect')).toBeEnabled();
});

test('a connection that never completes ends in a message, not an endless "Connecting"', async ({ page }) => {
  await page.clock.install();
  await fakeTransport(page);
  await open(page);
  await page.evaluate(() => { (window as any).__neverConnect = true; });
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('You are Player 1. Connecting video…');
  await page.clock.fastForward(21_000);
  await expect(page.locator('#status')).toHaveText('Can’t connect right now. Stay on the Avrana Party Wi-Fi, then tap Play.');
  await expect(page.locator('#connect')).toBeEnabled();
});

test('connected without a picture tells the player what to do', async ({ page }) => {
  await page.clock.install();
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  await page.clock.fastForward(11_000);
  await expect(page.locator('#status')).toHaveText('Connected, but no picture yet. Tap Sound; if it stays dark, tap Leave, then Play.');
  await expect(page.locator('#leave')).toBeEnabled();
  // the picture arriving late takes the stale words away
  await page.evaluate(() => document.querySelector('video')!.dispatchEvent(new Event('playing')));
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  await expect(page.locator('body')).toHaveAttribute('data-link', 'playing');
});

test('controls and sound work once connected', async ({ page }) => {
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  await page.evaluate(() => document.querySelector('video')!.dispatchEvent(new Event('playing')));
  const coin = page.locator('[data-key="coin"]');
  await coin.hover();
  await page.mouse.down();   // a real pointer (setPointerCapture needs one)
  await expect.poll(() => page.evaluate(() => (window as any).__sockets[0].sent
    .map((m: string) => JSON.parse(m)).some((m: any) => m.type === 'input' && m.buttons.includes('coin')))).toBe(true);
  await page.mouse.up();
  await expect(page.locator('#sound')).toBeEnabled();
  await expect(page.locator('#sound')).toHaveAttribute('aria-pressed', 'false');
  await page.locator('#sound').click();
  expect(await page.evaluate(() => document.querySelector('video')!.muted)).toBe(false);
  await expect(page.locator('#sound')).toHaveAttribute('aria-pressed', 'true');   // the button says whether it is on
  await page.locator('#sound').click();
  await expect(page.locator('#sound')).toHaveAttribute('aria-pressed', 'false');
});

// AVR-133: the Avrana game surface. What a layout engine can prove (target sizes, nothing off
// screen, portrait and landscape); the token and icon copies, the viewport meta and the words
// are held by tests/unit/test_arcade_page.py. Comfort under a thumb is on the pull request's
// "Needs real phones" list.

/** Problems with the page's controls and layout as it stands now: [] is a good page. */
async function layoutProblems(page: Page) {
  return page.evaluate(() => {
    const visible = (e: Element) => {
      const s = getComputedStyle(e); const b = e.getBoundingClientRect();
      return s.display !== 'none' && s.visibility !== 'hidden' && b.width > 0 && b.height > 0;
    };
    const out: string[] = [];
    for (const e of document.querySelectorAll('button, a[href]')) {
      if (!visible(e)) continue;
      const b = e.getBoundingClientRect();
      const name = e.id || (e as HTMLElement).dataset.key || e.className;
      if (b.width < 43.5 || b.height < 43.5) out.push(`${name} is ${Math.round(b.width)}x${Math.round(b.height)}`);
      if (b.left < -0.5 || b.right > innerWidth + 0.5) out.push(`${name} leaves the screen sideways`);
    }
    if (document.documentElement.scrollWidth > innerWidth) out.push('the page scrolls sideways');
    return out;
  });
}

test('every control is a comfortable target and on screen: before Play, connected and playing', async ({ page }) => {
  await fakeTransport(page);
  await open(page);
  const controlsEnd = () => page.evaluate(() => Math.round(document.querySelector('.controls')!.getBoundingClientRect().bottom) - innerHeight);
  expect(await layoutProblems(page), 'before Play').toEqual([]);
  expect(await controlsEnd(), 'the controls end on screen before Play').toBeLessThanOrEqual(0);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  expect(await layoutProblems(page), 'connected').toEqual([]);
  expect(await controlsEnd(), 'the controls end on screen when connected').toBeLessThanOrEqual(0);
  await page.evaluate(() => document.querySelector('video')!.dispatchEvent(new Event('playing')));
  expect(await layoutProblems(page), 'playing').toEqual([]);
});

test('the picture is dominant and the controls are in the thumbs’ half of a portrait phone', async ({ page }) => {
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  const m = await page.evaluate(() => {
    const r = (s: string) => document.querySelector(s)!.getBoundingClientRect();
    return { vw: innerWidth, vh: innerHeight, bar: r('.bar').height, screen: r('.screen'), dpad: r('.dpad'), acts: r('.acts'), status: r('.statusrow') };
  });
  expect(m.bar, 'one slim bar').toBeLessThanOrEqual(56);
  expect(m.screen.width, 'the picture is edge to edge').toBeGreaterThanOrEqual(m.vw - 1);
  expect(m.screen.width / m.screen.height).toBeCloseTo(4 / 3, 1);
  expect(m.status.top, 'the words sit under the picture').toBeGreaterThanOrEqual(m.screen.bottom - 2);
  expect(m.dpad.top, 'movement is in the lower half').toBeGreaterThan(m.vh / 2);
  expect(m.dpad.right, 'movement is left of the actions').toBeLessThan(m.acts.left);
  expect(m.acts.top, 'the actions are in the lower half').toBeGreaterThan(m.vh / 2);
});

test('sideways, the picture takes the height and the controls sit over its two ends', async ({ page }) => {
  await page.setViewportSize({ width: 844, height: 390 });
  await fakeTransport(page);
  await open(page);
  expect(await layoutProblems(page), 'before Play').toEqual([]);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  await page.evaluate(() => document.querySelector('video')!.dispatchEvent(new Event('playing')));
  expect(await layoutProblems(page), 'playing').toEqual([]);
  const m = await page.evaluate(() => {
    const rect = (e: Element) => { const b = e.getBoundingClientRect(); return { l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height }; };
    return {
      vw: innerWidth, vh: innerHeight, scrollH: document.documentElement.scrollHeight,
      screen: rect(document.querySelector('.screen')!), status: rect(document.querySelector('.statusrow')!),
      keys: Object.fromEntries([...document.querySelectorAll('[data-key]')].map((e) => [(e as HTMLElement).dataset.key!, rect(e)])),
      sound: rect(document.querySelector('#sound')!), leave: rect(document.querySelector('#leave')!),
    };
  });
  expect(m.scrollH, 'nothing to scroll').toBeLessThanOrEqual(m.vh);
  expect(m.screen.b).toBeLessThanOrEqual(m.vh + 0.5);
  expect(m.screen.h, 'the picture takes the height under the bar').toBeGreaterThan(m.vh * 0.8);
  const mid = m.vw / 2;
  for (const k of ['up', 'down', 'left', 'right']) expect(m.keys[k].r, `${k} is on the left`).toBeLessThan(mid);
  for (const k of ['fire', 'magic', 'coin', 'start']) expect(m.keys[k].l, `${k} is on the right`).toBeGreaterThan(mid);
  const names = Object.keys(m.keys);
  for (const a of names) for (const b of names) {
    if (a < b) {
      const x = m.keys[a], y = m.keys[b];
      expect(x.l < y.r - 1 && y.l < x.r - 1 && x.t < y.b - 1 && y.t < x.b - 1, `${a} and ${b} overlap`).toBe(false);
    }
  }
  expect(m.sound.b, 'sound and leave stay in the slim bar').toBeLessThan(60);
  expect(m.leave.b).toBeLessThan(60);
  expect(m.status.w, 'the status words are quiet while the picture plays').toBeLessThanOrEqual(2);
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');   // still there for a screen reader
});

test('a tablet sideways or a laptop window holds the whole page: the picture gives way, not the page', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  expect(await layoutProblems(page), 'connected').toEqual([]);
  const m = await page.evaluate(() => ({
    vh: innerHeight, scrollH: document.documentElement.scrollHeight, picture: document.querySelector('.screen')!.getBoundingClientRect().width,
  }));
  expect(m.scrollH, 'nothing to scroll').toBeLessThanOrEqual(m.vh);
  expect(m.picture, 'the picture is still the main thing').toBeGreaterThan(300);
});

test('the seat and the connection state are said in an icon and in words', async ({ page }) => {
  await fakeTransport(page);
  await open(page);
  const body = page.locator('body');
  await expect(body).toHaveAttribute('data-link', 'idle');
  await expect(page.locator('.i-idle')).toBeVisible();
  await expect(page.locator('#who')).toBeHidden();
  await page.evaluate(() => { (window as any).__slot = 3; (window as any).__slowOfferMs = 1200; });
  await page.locator('#connect').click();
  await expect(body).toHaveAttribute('data-link', 'wait');
  await expect(page.locator('.i-wait')).toBeVisible();
  await expect(page.locator('#status')).toHaveText('You are Player 3. Connecting video…');
  await expect(body).toHaveAttribute('data-link', 'live');
  await expect(page.locator('.i-live')).toBeVisible();
  await expect(page.locator('#who')).toHaveText('Player 3');
  await expect(page.locator('#status')).toHaveText('Player 3 connected. Add a coin to join.');
  await page.evaluate(() => document.querySelector('video')!.dispatchEvent(new Event('playing')));
  await expect(body).toHaveAttribute('data-link', 'playing');
  await page.locator('#leave').click();
  await expect(body).toHaveAttribute('data-link', 'idle');
  await expect(page.locator('#who')).toBeHidden();
  // a failure is a problem with its own icon, beside the words that say what to do
  await page.evaluate(() => { (window as any).__refuseSockets = true; });
  await page.locator('#connect').click();
  await expect(body).toHaveAttribute('data-link', 'problem');
  await expect(page.locator('.i-problem')).toBeVisible();
  await expect(page.locator('#status')).toHaveText('Can’t connect right now. Stay on the Avrana Party Wi-Fi, then tap Play.');
});

test('with less motion asked for, nothing spins', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await fakeTransport(page);
  await open(page);
  await page.evaluate(() => { (window as any).__slowOfferMs = 3000; });
  await page.locator('#connect').click();
  await expect(page.locator('#connect')).toHaveAttribute('aria-busy', 'true');
  await expect(page.locator('body')).toHaveAttribute('data-link', 'wait');
  expect(await page.locator('#connect').evaluate((b) => getComputedStyle(b, '::after').animationName)).toBe('none');
  expect(await page.locator('.i-wait').evaluate((e) => getComputedStyle(e).animationName)).toBe('none');
});

test('with more contrast asked for, the quiet words and the control edges are raised', async ({ page }) => {
  await open(page);
  const token = (name: string) => page.evaluate((n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim(), name);
  expect([await token('--color-muted'), await token('--color-control')]).toEqual(['#aeaba7', '#6e6c72']);
  await page.emulateMedia({ contrast: 'more' });
  expect([await token('--color-muted'), await token('--color-control')]).toEqual(['#d2cfcb', '#a5a3a8']);
});

test('a keyboard or switch user can see where focus is', async ({ page }) => {
  await open(page);
  await page.keyboard.press('Tab');
  const ring = await page.evaluate(() => {
    const e = document.activeElement as HTMLElement; const s = getComputedStyle(e);
    return { id: e.id, style: s.outlineStyle, width: s.outlineWidth, color: s.outlineColor };
  });
  expect(ring).toEqual({ id: 'connect', style: 'solid', width: '2px', color: 'rgb(185, 169, 232)' });
});

test('the page asks for nothing from any other origin', async ({ page }) => {
  const origins = new Set<string>();
  page.on('request', (r) => { if (r.url().startsWith('http')) origins.add(new URL(r.url()).origin); });
  await fakeTransport(page);
  await open(page);
  await page.locator('#connect').click();
  await expect(page.locator('#status')).toHaveText('Player 1 connected. Add a coin to join.');
  expect([...origins]).toEqual([new URL(page.url()).origin]);
});
