import { test, expect } from '@playwright/test';

/**
 * Captive-portal probe regression (HTTP level).
 *
 * CURRENT design (avrana-party.nginx): the iOS/macOS captive probe
 * `/hotspot-detect.html` returns Apple's literal Success page so the phone
 * marks the network usable and connects silently — NO captive popup — while the
 * landing/hub stays reachable at party.avrana/. Owner decision 2026-09-18; this
 * deliberately reverses the older "never serve Success" note.
 *
 * Scope limit: this only checks what the probe endpoint returns. The DNS
 * interception of captive.apple.com / captive.g.aaplimg.com -> 10.42.0.1 and the
 * real iOS captive-assistant behaviour are NOT exercised here — a real iPhone
 * remains authoritative for those.
 */
const APPLE_SUCCESS = '<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>';

test.describe('Captive probe', () => {
  test('/hotspot-detect.html returns Apple Success with no-store (silent connect)', async ({ request }) => {
    const res = await request.get('/hotspot-detect.html', { maxRedirects: 0 });
    expect(res.status()).toBe(200);
    expect((res.headers()['content-type'] ?? '')).toContain('text/html');
    expect((res.headers()['cache-control'] ?? '')).toContain('no-store');
    expect((await res.text()).trim()).toBe(APPLE_SUCCESS);
  });

  // The probe is intentionally host-independent (nginx `location =` in the
  // default server), so the Apple probe hostnames must resolve to the same
  // Success response once DNS points them at the Pi.
  for (const host of ['captive.apple.com', 'captive.g.aaplimg.com']) {
    test(`probe under Host: ${host} still returns Success`, async ({ request }) => {
      const res = await request.get('/hotspot-detect.html', {
        headers: { Host: host },
        maxRedirects: 0,
      });
      expect(res.status()).toBe(200);
      expect((await res.text()).trim()).toBe(APPLE_SUCCESS);
    });
  }
});
