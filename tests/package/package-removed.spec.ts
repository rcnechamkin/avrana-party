import { test, expect } from '@playwright/test';
import { place } from '../lib/frame';
import { GAMES, PARTY, joinParty, leaveAll, partyState, phone, post } from './phones';

/**
 * AVR-338, part 2: after `install-game remove hello` the game is gone from what a browser sees:
 * not in Party Home's Library, not launchable by the Host, and its route answers with an error, not a
 * stale page. The script has already run the real remove and regenerated the (harness-assisted) catalog.
 * Tier 2 on a CI runner (see package-play.spec.ts).
 */
test.skip(!process.env.AVRANA_PACKAGE_BROWSER_PROOF, 'runs only inside experiments/native-game/package-browser-proof.sh');

test('a removed package: gone from the Library, not launchable, its route is an error', async ({ browser }, info) => {
  const dee = await phone(browser, info, 'Dee');
  try {
    await joinParty(dee);
    await expect(dee.page.locator('#party-host')).toContainText('You’re the host');
    await place(dee.page, 'library');
    await expect(dee.page.locator('#games [data-game]').first()).toBeVisible();     // the Library rendered ...
    await expect(dee.page.locator('#games [data-game="hello"]')).toHaveCount(0);   // ... without the game
    const catalog = await (await dee.page.request.get(`${PARTY}/party/catalog.json`)).json();
    expect(catalog.games.map((g: any) => g.id)).not.toContain('hello');
    expect((await partyState(dee)).games).not.toContain('hello');                   // Party Core does not offer it

    // Not launchable: the Host's own request is refused.
    const before = (await partyState(dee)).session?.id ?? null;     // the finished session of an earlier suite stays in the Party's state
    const version = (await partyState(dee)).version;
    const launch = await post(dee, 'session/launch', { game: 'hello', if_version: version });
    expect(launch.status(), await launch.text()).toBeGreaterThanOrEqual(400);
    expect(launch.status()).toBeLessThan(500);
    expect((await partyState(dee)).session?.id ?? null).toBe(before);    // and nothing new started

    // Its route is gone. In the committed nginx site a slug that matches the native-game rule is proxied to
    // /run/avrana-games/<slug>.sock; with no socket nginx answers 502 itself. A 404 would mean the request never
    // reached that rule (a different failure), so only 502 or 503 is accepted. Never the page.
    const route = await dee.page.request.get(`${GAMES}/games/hello/`);
    expect([502, 503]).toContain(route.status());
    expect(await route.text()).not.toContain('Hello Party');
    const api = await dee.page.request.get(`${GAMES}/games/hello/api/party`);
    expect([502, 503]).toContain(api.status());
    const nav = await dee.page.goto(`${GAMES}/games/hello/`);
    expect([502, 503]).toContain(nav!.status());
    await expect(dee.page.locator('#secret')).toHaveCount(0);
  } finally {
    await leaveAll([dee]);
    await dee.context.close();
  }
});
