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
    // flowing (stream.py's "no-media"), or leave ICE hanging so the peer never connects.
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
          if ((window as any).__noMedia) {
            this.onmessage?.({ data: JSON.stringify({ type: 'error', reason: 'no-media', media: ['video'] }) });
            this.readyState = 3;
            this.onclose?.({ code: 1000 });
            return;
          }
          this.onmessage?.({ data: JSON.stringify({ type: 'player', slot: 1 }) });
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

test('the page contract the live suite relies on is unchanged', async ({ page }) => {
  await open(page);
  await expect(page).toHaveTitle(/Gauntlet II/);
  await expect(page.locator('#connect')).toHaveText(/Play Gauntlet II/);
  await expect(page.locator('#status')).toContainText(/Ready to play/i);
  await expect(page.locator('[data-key]')).toHaveCount(8);
  // Full Mode (a secure context, as here and on https://party.avrana.net): back to Party Home.
  await expect(page.getByRole('link', { name: 'Other games' })).toHaveAttribute('href', '/party/');
  await expect(page.locator('#leave')).toBeDisabled();
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
  await expect(page.locator('#status')).toHaveText('Both controllers are in use. Try again when one is free.');
  await expect(page.locator('#status')).toContainText(/slot|in use|free/i);  // the live harness's rejection check
  await expect(page.locator('[data-key="coin"]')).toBeDisabled();
  await expect(page.locator('#connect')).toBeEnabled();
  expect(await page.evaluate(() => (window as any).__wake)).toMatchObject({ requests: 1, held: 0 });
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
  await expect(page.locator('#status')).toHaveText('Connected, but no picture yet. Tap Enable sound; if it stays dark, tap Leave, then Play.');
  await expect(page.locator('#leave')).toBeEnabled();
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
  await page.locator('#sound').click();
  expect(await page.evaluate(() => document.querySelector('video')!.muted)).toBe(false);
});
