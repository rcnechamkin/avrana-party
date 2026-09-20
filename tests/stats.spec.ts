import { test, expect } from '@playwright/test';

/**
 * Arcade /stats contract. Cheap HTTP guard on the invariants the streaming
 * design depends on: a single shared encode, the 2-player cap, and a running
 * emulator. Not a performance assertion (power is unresolved; capture ages are
 * not trustworthy latency figures).
 */
test.describe('Arcade /stats contract', () => {
  test('exposes players, single shared encoder, and a running emulator', async ({ request }) => {
    const res = await request.get('/arcade/stats');
    expect(res.ok()).toBeTruthy();
    const s = await res.json();

    expect(s.max_players).toBe(2);
    expect(s.emulator_running).toBe(true);
    expect(s.video_encoders).toBe(1); // one hardware encode shared across peers
    expect(typeof s.players).toBe('number');
    expect(s.players).toBeGreaterThanOrEqual(0);
    expect(s.players).toBeLessThanOrEqual(s.max_players);
    expect(s.error).toBeFalsy();
    expect(s.capture_age_ms?.video?.p50).toBeGreaterThanOrEqual(0);
  });
});
