import { test, expect, type Page, type Route } from '@playwright/test';
import { place, startForEveryone } from '../lib/frame';
import { arrive, chooseName, goQuiet, later, phone, post, version, view, type Phone } from '../lib/phones';

/**
 * AVR-698 (Sprint 06, track 06C): one guest journey, start to finish, on phones that are separate
 * browser contexts (own cookie jar, own localStorage) against a real Party Core behind the dev
 * server (playwright.party.config.ts, project phones-chromium, Pixel 7 emulation). Every step is
 * a thing the contracts already define; nothing here asserts a behaviour the code and
 * docs/design/PARTY-LIFECYCLE.md, ADR 0008, 0010, 0011 (and its AVR-580 amendment) do not state.
 *
 *  1 a new guest arrives at Party Home      2 the guest joins the current Party
 *  3 the Host selects a game                4 players complete Play/Watch
 *  5 the Host launches the round            6 another guest joins late
 *  7 a participant reloads; another is suspended
 *  8 a participant loses and restores connectivity to the Party box
 *  9 the Host departs and succession occurs 10 the new Host ends the round
 * 11 everyone returns to the right place    12 another round, with no identity duplicated
 *
 * Tier 2: Chromium emulating a Pixel 7 on Windows, a simulated appliance, stub game pages. Not
 * iPhone Safari, not a physical Android phone, not Wi-Fi, not the Pi (docs/TESTING.md, Tier 3).
 *
 * The Host leaves and ends the round through the Party layer (the stub game page opts in with
 * localStorage avrana-test-layer, as party-layer.spec.ts does): that is the only Host surface a
 * phone has over a game page of the Party's own origin (ADR 0011 amendments 2026-10-16, 10-18).
 */

test.beforeEach(async ({ request }) => {
  expect((await request.post('/__test__/party/reset')).status()).toBe(204);
});

type Member = { id: string; name: string; host: boolean; presence: string };
const atRound = (game: string) => new RegExp(`/games/${game}/\\?avrana=1`);
const atHome = /\/party\/(#.*)?$/;
const FRAME = 'iframe[title="Your Party"]';
const layerOf = (page: Page) => page.frameLocator(FRAME);

const members = async (p: Phone): Promise<Member[]> => (await view(p)).members;

/** The Party has these people, once each: no id and no name twice (the identity-duplication check). */
async function expectPeople(p: Phone, names: string[], ids: Record<string, string>) {
  const list = await members(p);
  expect(list.map((m) => m.name).sort(), 'who is in the Party').toEqual([...names].sort());
  expect(new Set(list.map((m) => m.id)).size, 'no member twice').toBe(list.length);
  for (const m of list) if (ids[m.name]) expect(m.id, `${m.name} is the same member as before`).toBe(ids[m.name]);
  return Object.fromEntries(list.map((m) => [m.name, m.id]));
}

/** The Party's answer reaches a phone that has just gone offline: the long poll the page already had
 * on its way is answered (by the real Party Core) and the phone's radio drops before it is read.
 * This is the ordering that sent a phone to the browser's own error page (AVR-698). The page is
 * reloaded so that the poll in flight is one this test can hold; `armed` resolves once it is. */
async function answerArrivesOffline(p: Phone, isTheMove: (view: { location: { at: string } }) => boolean) {
  let held: { route: Route; json: unknown } | null = null;
  let waiting!: () => void, arrived!: () => void;
  const armed = new Promise<void>((resolve) => { waiting = resolve; });
  const answered = new Promise<void>((resolve) => { arrived = resolve; });
  await p.context.route('**/party/api/state?*', async (route) => {
    if (held) return route.continue();
    waiting();
    const response = await route.fetch();
    const json = await response.json().catch(() => null);
    if (!json || !isTheMove(json)) return route.fulfill({ response, json });
    held = { route, json };
    arrived();
  });
  await p.page.reload();
  await expect(p.page.locator('html')).toHaveAttribute('data-ready', 'true');
  await armed;
  return {
    answered,
    async deliverOffline() {
      await p.context.setOffline(true);
      await held!.route.fulfill({ json: held!.json });
    },
    online: () => p.context.setOffline(false),
  };
}

async function openLayer(page: Page) {
  const layer = layerOf(page);
  await layer.locator('#layer-button').click();
  await expect(layer.locator('#layer-sheet')).toBeVisible();
  return layer;
}

test.describe('the guest journey: BLUFF (Play/Watch setup, spectator-only late join)', () => {
  const all: Phone[] = [];
  const keep = (p: Phone) => { all.push(p); return p; };
  test.afterEach(async () => { for (const p of all.splice(0)) await p.context.close(); });

  test('arrive, join, choose, play, a late guest, reload, suspend, lose the box, Host departs, new Host ends, play again', async ({ browser, request }, testInfo) => {
    test.setTimeout(180_000);
    const ids: Record<string, string> = {};
    let ada!: Phone, bob!: Phone, cleo!: Phone, dee!: Phone;

    await test.step('1 a new guest arrives at Party Home (the first phone hosts; the guest has no profile yet)', async () => {
      ada = keep(await phone(browser, 'Ada'));
      await ada.context.addInitScript(() => { try { localStorage.setItem('avrana-test-layer', '1'); } catch { /* none */ } });   // for her game page
      expect(testInfo.project.name).toBe('phones-chromium');
      expect(ada.page.viewportSize()!.width, 'a Pixel 7 sized phone').toBeLessThan(500);
      expect(await ada.page.evaluate(() => navigator.maxTouchPoints), 'touch emulation is on').toBeGreaterThan(0);
      bob = keep(await arrive(browser, 'Bob', { profile: false, layer: true }));
      await chooseName(bob);
      await expect(bob.page.locator('#party-host')).toContainText('Ada is the host');
    });

    await test.step('2 the guest joins the current Party (a second new guest does the same)', async () => {
      cleo = keep(await arrive(browser, 'Cleo', { profile: false, layer: true }));
      await chooseName(cleo);
      for (const p of [ada, bob, cleo]) {
        await expect(p.page.locator('#party-count'), p.name).toHaveText('3 people');
        await expect(p.page.locator('#party-lede'), p.name).toHaveText('Three of you are here.');
      }
      await expect(ada.page.locator('#party-host')).toContainText('You’re the host');
      Object.assign(ids, await expectPeople(ada, ['Ada', 'Bob', 'Cleo'], {}));
      expect((await view(bob)).me.host).toBe(false);
      expect((await view(ada)).location.at).toBe('home');
    });

    await test.step('3 the Host selects a game: everyone is taken to BLUFF’s setup, and only the Host can start it', async () => {
      await startForEveryone(ada.page, 'bluff');
      for (const p of [ada, bob, cleo]) {
        await expect(p.page.locator('#scene'), p.name).toBeVisible();
        await expect(p.page.locator('#scene-title'), p.name).toHaveText('BLUFF');
        await expect(p.page.locator('#scene-roster li'), p.name).toHaveCount(3);
      }
      const v = await view(bob);
      expect([v.location.at, v.session.state]).toEqual(['setup', 'setup']);
      for (const p of [bob, cleo]) {
        await expect(p.page.locator('#scene-start'), p.name).toBeHidden();
        expect((await post(p, 'session/start', { if_version: await version(p) })).status(), p.name).toBe(403);
      }
      await expect(ada.page.locator('#scene-start')).toBeDisabled();       // nobody has chosen
    });

    await test.step('4 players complete Play/Watch (Cleo reloads the briefing and keeps her answer)', async () => {
      for (const p of [ada, bob]) {
        await p.page.locator('#choose-play').click();
        const ok = p.page.locator('#rules-ok');
        if (await ok.isVisible().catch(() => false)) await ok.click();     // a first-timer's briefing, if the game ships one
        await expect(p.page.locator('#choose-play'), p.name).toHaveAttribute('aria-pressed', 'true');
      }
      await cleo.page.locator('#choose-watch').click();
      await expect(cleo.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
      await expect(ada.page.locator('#scene-count')).toHaveText('2 playing · 1 watching');
      await expect(ada.page.locator('#scene-start')).toBeEnabled();
      await cleo.page.reload();
      await expect(cleo.page.locator('#scene')).toBeVisible();
      await expect(cleo.page.locator('#choose-watch')).toHaveAttribute('aria-pressed', 'true');
      await expectPeople(ada, ['Ada', 'Bob', 'Cleo'], ids);
    });

    await test.step('5 the Host launches the round: everyone is at BLUFF’s page with the role they chose', async () => {
      await ada.page.locator('#scene-start').click();
      for (const p of [ada, bob, cleo]) await expect(p.page, p.name).toHaveURL(atRound('bluff'));
      const roles = async (p: Phone) => (await view(p)).session.my_role;
      expect([await roles(ada), await roles(bob), await roles(cleo)]).toEqual(['player', 'player', 'spectator']);
      const v = await view(ada);
      expect([v.location.at, v.session.state, v.session.players]).toEqual(['game', 'active', 2]);
      await expect(layerOf(ada.page).locator('#layer-button')).toBeVisible();
    });

    await test.step('6 another guest joins late: taken straight to the round, as a watcher, counted once', async () => {
      dee = keep(await arrive(browser, 'Dee', { layer: true }));
      await expect(dee.page).toHaveURL(atRound('bluff'));
      const v = await view(dee);
      expect([v.session.my_role, v.session.players, v.location.at]).toEqual(['spectator', 2, 'game']);
      Object.assign(ids, await expectPeople(ada, ['Ada', 'Bob', 'Cleo', 'Dee'], ids));
      // the roster the others see grew by one, and nobody's role moved
      expect((await view(bob)).session.my_role).toBe('player');
      expect((await view(cleo)).session.my_role).toBe('spectator');
      // asking for a role mid-round is refused: roles change at the setup boundary (ADR 0010 decision 2)
      const refused = await post(dee, 'session/choice', { choice: 'player' });
      expect([refused.status(), (await refused.json()).error]).toEqual([409, 'round_on']);
    });

    await test.step('7a a player reloads mid-round: same member, same seat, no second copy', async () => {
      const before = await view(bob);
      await bob.page.reload();
      await expect(bob.page).toHaveURL(atRound('bluff'));
      await expect(bob.page.locator('h1[data-game="bluff"]')).toBeVisible();
      const after = await view(bob);
      expect([after.me.id, after.session.id, after.session.my_role]).toEqual([before.me.id, before.session.id, 'player']);
      await expectPeople(ada, ['Ada', 'Bob', 'Cleo', 'Dee'], ids);
    });

    await test.step('7b a watcher’s phone is suspended (page gone, nothing leaves it) and woken: back in the round, once', async () => {
      const wake = await goQuiet(cleo);
      await later(request, 60);                                           // longer than the 45 s a quiet phone is allowed
      // a seat in a live round counts as playing, not away (core.presence), so the roster is unchanged
      const v = await view(ada);
      expect(v.members.find((m: Member) => m.name === 'Cleo').presence).toBe('playing');
      await wake();
      await cleo.page.goto('/party/');                                    // the phone is opened again on Party Home
      await expect(cleo.page).toHaveURL(atRound('bluff'));                // and goes where the Party is
      expect((await view(cleo)).session.my_role).toBe('spectator');
      await expectPeople(ada, ['Ada', 'Bob', 'Cleo', 'Dee'], ids);
    });

    await test.step('8 a player loses the Party box and gets it back: still in the round, and hears the Party again', async () => {
      const block = (route: { abort: () => Promise<void> }) => route.abort();
      await bob.context.route('**/party/api/**', block);
      await bob.page.evaluate(() => window.dispatchEvent(new Event('offline')));
      // the Party moves while Bob is out of reach: Dee renames
      expect((await post(dee, 'rename', { name: 'Dee', avatar: 'gaze-07' })).status()).toBe(200);
      const seen = () => bob.page.evaluate(() => (window as unknown as { AvranaParty: { view(): { members: { name: string; avatar: string }[] } } })
        .AvranaParty.view().members.find((m) => m.name === 'Dee')!.avatar);
      expect(await seen(), 'Bob has not heard it').not.toBe('gaze-07');
      // the game owns the screen, so the Party says so where Bob can ask it: the drawer
      const layer = await openLayer(bob.page);
      await expect(layer.locator('#layer-link')).toHaveText('Not connected to the Party. Trying again…', { timeout: 15_000 });
      await bob.context.unroute('**/party/api/**', block);
      await bob.page.evaluate(() => window.dispatchEvent(new Event('online')));
      await expect.poll(seen, { timeout: 12_000 }).toBe('gaze-07');
      await expect(layer.locator('#layer-link')).toHaveText('', { timeout: 12_000 });
      await bob.page.keyboard.press('Escape');
      await expect(layer.locator('#layer-sheet')).toBeHidden();
      await expect(bob.page).toHaveURL(atRound('bluff'));
      await expectPeople(ada, ['Ada', 'Bob', 'Cleo', 'Dee'], ids);
    });

    await test.step('9 the Host departs (Leave from the Party layer): the next phone hosts at once, the round goes on', async () => {
      const layer = await openLayer(ada.page);
      await layer.locator('#layer-leave-ask').click();
      await expect(layer.locator('#layer-leave-host')).toContainText('You are the Host. Bob becomes the Host right away.');
      await layer.locator('#layer-leave-yes').click();
      await expect(ada.page).toHaveURL(atHome);
      await expect(ada.page.locator('#reconnect')).toBeVisible();
      const v = await view(bob);
      expect([v.me.host, v.state, v.location.at, v.session.my_role]).toEqual([true, 'active', 'game', 'player']);
      await expectPeople(bob, ['Bob', 'Cleo', 'Dee'], ids);
      for (const p of [bob, cleo, dee]) await expect(p.page, p.name).toHaveURL(atRound('bluff'));
      // the former Host keeps no authority, even by name
      const stale = await post(ada, 'session/end', { if_version: (await view(bob)).version });
      expect(stale.status()).toBe(403);
    });

    await test.step('10 the new Host ends the round, from the layer after a confirmation', async () => {
      const layer = await openLayer(bob.page);
      await expect(layer.locator('[data-action="end"]')).toBeVisible();
      await layer.locator('[data-action="end"]').click();
      await expect(layer.locator('#layer-confirm-text')).toHaveText('This ends the round for everyone. Everyone goes back to Party Home.');
      await layer.locator('#layer-yes').click();
    });

    await test.step('11 everyone is where the Party is: Party Home; the one who left is asked to Reconnect, and comes back once', async () => {
      for (const p of [bob, cleo, dee]) {
        await expect(p.page, p.name).toHaveURL(atHome);
        await expect(p.page.locator('#party-lede'), p.name).toHaveText('Three of you are here.');
        await expect(p.page.locator('#party-host'), p.name).toContainText(p === bob ? 'You’re the host' : 'Bob is the host');
      }
      expect((await view(bob)).location.at).toBe('home');
      await expect(ada.page.locator('#reconnect')).toBeVisible();
      await ada.page.locator('#reconnect-btn').click();
      await expect(ada.page.locator('#party-members')).toContainText('Ada (you)');
      await expect(ada.page.locator('#party-host')).toContainText('Bob is the host');   // coming back does not restore the role
      await expect(ada.page.locator('#reconnect')).toBeHidden();
      await expectPeople(bob, ['Ada', 'Bob', 'Cleo', 'Dee'], ids);
    });

    await test.step('12 another round: the new Host launches BLUFF again; fresh setup, same four people, no copy of anyone', async () => {
      await startForEveryone(bob.page, 'bluff');
      for (const p of [ada, bob, cleo, dee]) {
        await expect(p.page.locator('#scene'), p.name).toBeVisible();
        await expect(p.page.locator('#scene-roster li'), p.name).toHaveCount(4);
      }
      const fresh = await view(dee);
      expect(fresh.session.setup.mine, 'last round’s answers are not carried over').toBeNull();
      expect(fresh.session.setup.choices).toEqual({});
      for (const p of [ada, bob, dee]) {
        await p.page.locator('#choose-play').click();
        const ok = p.page.locator('#rules-ok');
        if (await ok.isVisible().catch(() => false)) await ok.click();
        await expect(p.page.locator('#choose-play'), p.name).toHaveAttribute('aria-pressed', 'true');
      }
      await cleo.page.locator('#choose-watch').click();
      await expect(bob.page.locator('#scene-count')).toHaveText('3 playing · 1 watching');
      await bob.page.locator('#scene-start').click();
      for (const p of [ada, bob, cleo, dee]) await expect(p.page, p.name).toHaveURL(atRound('bluff'));
      // Dee watched last round and plays this one: the setup boundary is where roles change
      expect((await view(dee)).session.my_role).toBe('player');
      expect((await view(ada)).session.my_role).toBe('player');
      expect((await view(cleo)).session.my_role).toBe('spectator');
      await expectPeople(bob, ['Ada', 'Bob', 'Cleo', 'Dee'], ids);
      expect((await post(bob, 'session/end', { if_version: await version(bob) })).status()).toBe(200);
      for (const p of [ada, bob, cleo, dee]) await expect(p.page, p.name).toHaveURL(atHome);
      await expectPeople(bob, ['Ada', 'Bob', 'Cleo', 'Dee'], ids);
    });
  });
});

test.describe('the guest journey: direct-launch games (EXPO seats two, Gauntlet II seats four)', () => {
  const all: Phone[] = [];
  const keep = (p: Phone) => { all.push(p); return p; };
  test.afterEach(async () => { for (const p of all.splice(0)) await p.context.close(); });

  test('the Host’s phone is suspended and hosting passes; a guest loses the box while the new Host ends the round and lands home when it is back', async ({ browser, request }) => {
    test.setTimeout(180_000);
    const ids: Record<string, string> = {};
    const ada = keep(await phone(browser, 'Ada'));
    await ada.context.addInitScript(() => { try { localStorage.setItem('avrana-test-layer', '1'); } catch { /* none */ } });
    const bob = keep(await arrive(browser, 'Bob', { profile: false, layer: true }));
    await chooseName(bob);
    const cleo = keep(await arrive(browser, 'Cleo', { profile: false, layer: true }));
    await chooseName(cleo);
    Object.assign(ids, await expectPeople(ada, ['Ada', 'Bob', 'Cleo'], {}));

    await test.step('the Host’s phone is suspended at Party Home: Away is said, then hosting passes to the earliest guest', async () => {
      const wake = await goQuiet(ada);
      await later(request, 50);
      for (const p of [bob, cleo]) await expect(p.page.locator('#party-host'), p.name).toHaveText('Ada is the host, and is away.');
      await view(bob); await view(cleo);                                  // both have asked since: they are here when the role passes
      await later(request, 30);
      await expect(bob.page.locator('#party-host')).toContainText('You’re the host');
      await expect(cleo.page.locator('#party-host')).toHaveText('Bob is the host and picks the games.');
      await wake();
      await ada.page.goto('/party/');
      await expect(ada.page.locator('#party-host')).toHaveText('Bob is the host and picks the games.');
      await expectPeople(bob, ['Ada', 'Bob', 'Cleo'], ids);
    });

    let dee!: Phone;
    await test.step('the new Host starts EXPO (two seats): two play, the third watches, a late guest watches too', async () => {
      await startForEveryone(bob.page, 'expo');
      for (const p of [ada, bob, cleo]) await expect(p.page, p.name).toHaveURL(atRound('expo'));
      expect([(await view(ada)).session.my_role, (await view(bob)).session.my_role, (await view(cleo)).session.my_role])
        .toEqual(['player', 'player', 'spectator']);
      dee = keep(await arrive(browser, 'Dee', { layer: true }));
      await expect(dee.page).toHaveURL(atRound('expo'));
      expect((await view(dee)).session.my_role).toBe('spectator');
      Object.assign(ids, await expectPeople(bob, ['Ada', 'Bob', 'Cleo', 'Dee'], ids));
    });

    await test.step('a guest’s phone drops off the Wi-Fi; the Host ends the round; the guest lands on Party Home when it is back', async () => {
      await cleo.context.setOffline(true);
      const layer = await openLayer(bob.page);
      await layer.locator('[data-action="end"]').click();
      await layer.locator('#layer-yes').click();
      for (const p of [ada, bob, dee]) await expect(p.page, p.name).toHaveURL(atHome);
      expect(cleo.page.url(), 'the phone that cannot hear is still where it was').toMatch(atRound('expo'));
      await cleo.context.setOffline(false);
      await expect(cleo.page).toHaveURL(atHome, { timeout: 15_000 });
      await expect(cleo.page.locator('#party-lede')).toHaveText('Four of you are here.');
      await expectPeople(bob, ['Ada', 'Bob', 'Cleo', 'Dee'], ids);
    });

    await test.step('Gauntlet II (four seats): all four play; a fifth, late, watches; ending takes everyone home', async () => {
      await startForEveryone(bob.page, 'arcade-gauntlet2');
      const four = [ada, bob, cleo, dee];
      for (const p of four) await expect(p.page, p.name).toHaveURL(/\/arcade\//);
      expect(await Promise.all(four.map(async (p) => (await view(p)).session.my_role))).toEqual(['player', 'player', 'player', 'player']);
      const eli = keep(await arrive(browser, 'Eli', { layer: true }));
      await expect(eli.page).toHaveURL(/\/arcade\//);
      expect((await view(eli)).session.my_role).toBe('spectator');       // v0 admits a late member as a spectator, whatever late_join says
      Object.assign(ids, await expectPeople(bob, ['Ada', 'Bob', 'Cleo', 'Dee', 'Eli'], ids));
      await ada.page.reload();                                           // a player reloads the arcade page
      await expect(ada.page).toHaveURL(/\/arcade\//);
      expect((await view(ada)).session.my_role).toBe('player');
      expect((await post(bob, 'session/end', { if_version: await version(bob) })).status()).toBe(200);
      for (const p of [...four, eli]) await expect(p.page, p.name).toHaveURL(atHome);
      await expectPeople(bob, ['Ada', 'Bob', 'Cleo', 'Dee', 'Eli'], ids);
    });
  });
});

test.describe('the guest journey: setup and the Party box', () => {
  const all: Phone[] = [];
  const keep = (p: Phone) => { all.push(p); return p; };
  test.afterEach(async () => { for (const p of all.splice(0)) await p.context.close(); });

  test('a guest who arrives during setup must choose before the Host can start; a quiet phone does not block it; two guests with one name stay two people', async ({ browser, request }) => {
    test.setTimeout(180_000);
    const ada = keep(await phone(browser, 'Ada'));
    const bob = keep(await arrive(browser, 'Bob', { profile: false, layer: true }));
    await chooseName(bob);
    const cleo = keep(await arrive(browser, 'Cleo', { profile: false, layer: true }));
    await chooseName(cleo);
    await startForEveryone(ada.page, 'bluff');
    for (const p of [ada, bob, cleo]) await expect(p.page.locator('#scene'), p.name).toBeVisible();

    // a new guest, with no profile, arrives while BLUFF is being set up
    const dee = keep(await arrive(browser, 'Dee', { profile: false, layer: true }));
    await chooseName(dee, 'scene');
    await expect(dee.page.locator('#scene-roster li')).toHaveCount(4);
    for (const p of [ada, bob, cleo]) await p.page.locator('#choose-play').click();
    await expect(ada.page.locator('#scene-start')).toBeDisabled();
    await expect(ada.page.locator('#scene-status')).toContainText('Dee');   // Party Core says who it waits for
    await dee.page.locator('#choose-watch').click();
    await expect(ada.page.locator('#scene-start')).toBeEnabled();

    // a phone that goes quiet (Cleo) does not hold the Start: away members do not block it (ADR 0010)
    const wake = await goQuiet(cleo);
    await later(request, 50);
    await expect(ada.page.locator('#scene-roster li', { hasText: 'Cleo' })).toContainText('Away');
    await expect(ada.page.locator('#scene-start')).toBeEnabled();
    await ada.page.locator('#scene-start').click();
    for (const p of [ada, bob, dee]) await expect(p.page, p.name).toHaveURL(atRound('bluff'));
    expect([(await view(ada)).session.players, (await view(dee)).session.my_role]).toEqual([2, 'spectator']);
    // she wakes after the Start: she is taken to the round and is a watcher; her first ask of the game seats her once
    await wake();
    await cleo.page.goto('/party/');
    await expect(cleo.page).toHaveURL(atRound('bluff'));
    expect((await post(cleo, 'session/ticket', { game: 'bluff' })).status()).toBe(200);
    expect((await view(cleo)).session.my_role).toBe('spectator');
    const ids = await expectPeople(ada, ['Ada', 'Bob', 'Cleo', 'Dee'], {});
    expect((await post(ada, 'session/end', { if_version: await version(ada) })).status()).toBe(200);
    for (const p of [ada, bob, cleo, dee]) await expect(p.page, p.name).toHaveURL(atHome);

    // a second guest who types a name that is taken is a second person, shown with a number; a reload keeps that one
    const bob2 = keep(await arrive(browser, 'Bob', { profile: false, layer: true }));
    await chooseName(bob2, 'joined');
    const twice = await members(ada);
    expect(twice.map((m) => m.name).sort()).toEqual(['Ada', 'Bob', 'Bob 2', 'Cleo', 'Dee']);
    await bob2.page.reload();
    await expect(bob2.page.locator('#party-members')).toContainText('Bob 2 (you)');
    await expectPeople(ada, ['Ada', 'Bob', 'Bob 2', 'Cleo', 'Dee'], { ...ids });
  });

  test('AVR-698: a phone that is offline when the Party moves waits for the network; it never lands on the browser’s error page', async ({ browser }) => {
    test.setTimeout(120_000);
    const ada = keep(await phone(browser, 'Ada'));
    const bob = keep(await phone(browser, 'Bob'));
    const cleo = keep(await phone(browser, 'Cleo'));
    const seen: string[] = [];
    for (const p of [bob, cleo]) p.page.on('framenavigated', (f) => { if (f === p.page.mainFrame()) seen.push(`${p.name} ${f.url()}`); });

    // 1 Party Home, and the Host starts a game that needs no setup (EXPO)
    const home = await answerArrivesOffline(bob, (v) => v.location.at === 'game');
    expect((await post(ada, 'session/launch', { game: 'expo', if_version: await version(ada) })).status()).toBe(200);
    await home.answered;
    await home.deliverOffline();
    await expect(bob.page.locator('#going-text')).toHaveText('Waiting for the connection to take you to EXPO…');   // said, not a spinner alone
    await bob.page.waitForTimeout(1500);                                   // longer than any retry the page makes
    expect(bob.page.url(), 'the move waits while the phone is offline').toMatch(atHome);
    await home.online();
    await expect(bob.page).toHaveURL(atRound('expo'), { timeout: 15_000 });
    await expect(bob.page.locator('h1[data-game="expo"]')).toBeVisible();
    expect((await post(ada, 'session/end', { if_version: await version(ada) })).status()).toBe(200);
    for (const p of [ada, bob, cleo]) await expect(p.page, p.name).toHaveURL(atHome);

    // 2 The briefing, and the Host starts the round
    await startForEveryone(ada.page, 'bluff');
    for (const p of [ada, bob, cleo]) await expect(p.page.locator('#scene'), p.name).toBeVisible();
    for (const p of [ada, bob]) await p.page.locator('#choose-play').click();
    await cleo.page.locator('#choose-watch').click();
    await expect(ada.page.locator('#scene-start')).toBeEnabled();
    const brief = await answerArrivesOffline(cleo, (v) => v.location.at === 'game');
    await ada.page.locator('#scene-start').click();
    await brief.answered;
    await brief.deliverOffline();
    for (const p of [ada, bob]) await expect(p.page, p.name).toHaveURL(atRound('bluff'));
    await cleo.page.waitForTimeout(1500);
    expect(cleo.page.url()).toMatch(atHome);
    await brief.online();
    await expect(cleo.page).toHaveURL(atRound('bluff'), { timeout: 15_000 });
    expect((await view(cleo)).session.my_role).toBe('spectator');

    // 3 The Party moves on again while the phone is away: when it is back it goes where the Party is, not where it was told
    await bob.context.setOffline(true);
    expect((await post(ada, 'session/end', { if_version: await version(ada) })).status()).toBe(200);
    await bob.context.setOffline(false);
    await expect(bob.page).toHaveURL(atHome, { timeout: 15_000 });
    expect(seen.filter((u) => u.includes('chrome-error')), 'no phone was ever left on the browser’s own error page').toEqual([]);
    await expectPeople(ada, ['Ada', 'Bob', 'Cleo'], {});
  });

  test('the Host leaves during setup: the next phone gets Start; she reconnects and chooses again; nobody is counted twice', async ({ browser }) => {
    test.setTimeout(120_000);
    const ada = keep(await phone(browser, 'Ada'));
    const bob = keep(await phone(browser, 'Bob'));
    const cleo = keep(await phone(browser, 'Cleo'));
    const ids = await expectPeople(ada, ['Ada', 'Bob', 'Cleo'], {});
    await startForEveryone(ada.page, 'bluff');
    for (const p of [ada, bob, cleo]) await expect(p.page.locator('#scene'), p.name).toBeVisible();
    await ada.page.locator('#choose-play').click();
    await expect(ada.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'true');
    expect((await post(ada, 'leave', {})).status()).toBe(200);
    // her briefing has no Leave of its own (the Party control is people only there), so this is a Leave
    // from another tab of the same phone; her page comes off the briefing and offers Reconnect where it is
    expect((await view(ada)).departed).toBe(true);
    await expect(ada.page.locator('#scene')).toBeHidden();
    await expect(ada.page.getByRole('button', { name: 'Reconnect to play' })).toBeVisible();
    await expect(bob.page.locator('#scene-status')).toHaveText(/^You’re hosting now\./);
    await expect(bob.page.locator('#scene-start')).toBeVisible();
    await expect(cleo.page.locator('#scene-status')).toContainText('Bob is hosting now');
    await expectPeople(bob, ['Bob', 'Cleo'], ids);
    await ada.page.getByRole('button', { name: 'Reconnect to play' }).click();
    await expect(ada.page.locator('#scene')).toBeVisible();              // Reconnect follows the Party: it is in setup
    await expect(ada.page.locator('#choose-play')).toHaveAttribute('aria-pressed', 'false');   // and she chooses again
    expect((await view(ada)).session.setup.mine ?? null).toBeNull();
    await expect(ada.page.locator('#scene-start')).toBeHidden();         // she is not the Host any more
    await expectPeople(bob, ['Ada', 'Bob', 'Cleo'], ids);
    for (const p of [ada, bob]) await p.page.locator('#choose-play').click();
    await cleo.page.locator('#choose-watch').click();
    await bob.page.locator('#scene-start').click();
    for (const p of [ada, bob, cleo]) await expect(p.page, p.name).toHaveURL(atRound('bluff'));
    expect([(await view(ada)).session.my_role, (await view(cleo)).session.my_role]).toEqual(['player', 'spectator']);
    await expectPeople(bob, ['Ada', 'Bob', 'Cleo'], ids);
    expect((await post(bob, 'session/end', { if_version: await version(bob) })).status()).toBe(200);
    for (const p of [ada, bob, cleo]) await expect(p.page, p.name).toHaveURL(atHome);
  });

  test('the Party box restarts mid-round: every phone is brought home and is in the new Party once', async ({ browser, request }) => {
    test.setTimeout(120_000);
    const ada = keep(await phone(browser, 'Ada'));
    const bob = keep(await phone(browser, 'Bob'));
    const cleo = keep(await phone(browser, 'Cleo'));
    expect((await post(ada, 'session/launch', { game: 'expo', if_version: await version(ada) })).status()).toBe(200);
    for (const p of [ada, bob, cleo]) await expect(p.page, p.name).toHaveURL(atRound('expo'));
    expect((await request.post('/__test__/party/reset')).status()).toBe(204);   // the Pi restarts; its Party is memory-only
    for (const p of [ada, bob, cleo]) await expect(p.page, p.name).toHaveURL(atHome, { timeout: 20_000 });
    for (const p of [ada, bob, cleo]) await expect(p.page.locator('#party-lede'), p.name).toHaveText('Three of you are here.', { timeout: 15_000 });
    const list = await members(ada);
    expect(list.map((m) => m.name).sort()).toEqual(['Ada', 'Bob', 'Cleo']);
    expect(list.filter((m) => m.host), 'exactly one Host').toHaveLength(1);
    expect((await view(ada)).location.at).toBe('home');
    const host = list.find((m) => m.host)!.name;
    const hostPhone = [ada, bob, cleo].find((p) => p.name === host)!;
    for (const p of [ada, bob, cleo]) await expect(p.page.locator('#party-host'), p.name).toContainText(p === hostPhone ? 'You’re the host' : `${host} is the host`);
    // and the next round starts as usual
    await startForEveryone(hostPhone.page, 'expo');
    for (const p of [ada, bob, cleo]) await expect(p.page, p.name).toHaveURL(atRound('expo'));
    expect((await post(hostPhone, 'session/end', { if_version: await version(hostPhone) })).status()).toBe(200);
  });
});
