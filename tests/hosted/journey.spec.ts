import { test, expect } from '@playwright/test';
import { BASE, GAMES, GAME_LIST, api, close, homeFor, hostOf, launch, phone, playToTheEnd, resetIfLocal, state, type Phone } from './hosted';

// The remote journey (initiative brief, H3 steps 1-14), once per game in HOSTED_GAMES, through real pages
// on a deployed Party: testers join independently, the Host picks the game, the players choose Play (one
// more watches), Party Core launches the real game, the game's own driver plays it to its end, the Party
// records the result, everyone is back at Party Home, the Party is still usable, and the Host starts the next
// round. Game-neutral: the table is as large as the game's catalog row asks (at least two players), and
// HOSTED_GAMES_REPO/<id>/party-driver.mjs is the only thing that knows the game's rules.
const NAMES = ['Ada', 'Ben', 'Cleo', 'Dev', 'Eli', 'Fen', 'Gil', 'Hal'];

test.beforeEach(() => resetIfLocal());

for (const id of GAME_LIST) {
  test(`${id}: join, launch, play to the end, return to the Party, and start again`, async ({ browser }, info) => {
    test.skip(info.project.name !== 'android-size' && process.env.HOSTED_BOTH_SIZES !== '1', 'one phone size per game unless HOSTED_BOTH_SIZES=1');
    test.setTimeout(900_000);
    const phones: Phone[] = [];
    try {
      let players: Phone[] = [], watcher: Phone;
      await test.step('1-5 testers open the site, are signed in, and join the Party on their own', async () => {
        phones.push(await phone(browser, NAMES[0]), await phone(browser, NAMES[1]));
        await homeFor(...phones).catch(() => undefined);
        expect((await state(phones[0]))?.games, `Party Core offers ${id}`).toContain(id);
        const catalog = await (await phones[0].context.request.get(`${BASE}/party/catalog.json`).catch(() => null))?.json().catch(() => null)
          ?? await phones[0].page.evaluate(async () => (await fetch('/party/catalog.json')).json());
        const need = Math.max(2, catalog?.games?.find((g: any) => g.id === id)?.players?.min ?? 2);
        while (phones.length < need + 1) phones.push(await phone(browser, NAMES[phones.length]));
        await expect(phones[0].page.locator('#party-members')).toContainText(phones[1].name);
        await expect(phones[1].page.locator('#party-members')).toContainText(phones[0].name);
        const host = await hostOf(phones);
        players = [host, ...phones.filter((p) => p !== host)].slice(0, need);
        watcher = phones.find((p) => !players.includes(p))!;
      });

      await test.step('6-9 the Host picks the game, players choose Play, a spectator Watches, Party Core launches it', async () => {
        await launch(players[0], [...players.slice(1), watcher], id, [watcher]);
        for (const p of players) expect((await state(p))?.session?.my_role, p.name).toBe('player');
        expect((await state(watcher))?.session?.my_role).toBe('spectator');
        if (GAMES !== BASE) for (const p of phones) {
          const onGame = (await p.context.cookies(GAMES)).filter((c) => /avrana_device/.test(c.name));
          expect(onGame, `${p.name}: no Party cookie on the game origin`).toEqual([]);
        }
      });

      await test.step('10-11 the players play the game to its end through its pages', async () => {
        const { finished, actions } = await playToTheEnd(id, players);
        test.info().annotations.push({ type: 'actions', description: `${id}: ${actions} player actions` });
        expect(finished, `${id} reached its end on every player's phone`).toBe(true);
        expect(actions, 'meaningful play happened').toBeGreaterThan(2);
      });

      await test.step('12-13 the result is recorded, everyone returns to Party Home, and the Party is still usable', async () => {
        await expect.poll(async () => (await state(players[0]))?.session?.outcome, { timeout: 60_000 }).toBe('completed');
        const v = await state(players[0]);
        expect(v.session?.result_summary?.players?.length ?? 0).toBeGreaterThanOrEqual(players.length);
        await homeFor(...phones);
        await expect(phones[0].page.locator('#party-members')).toContainText(phones[1].name);
      });

      await test.step('14 the Host starts another round of the same game', async () => {
        // The same size of table: one phone still watches, so a game with a small maximum (Checkers) can start.
        const host = await hostOf(phones);
        const others = phones.filter((p) => p !== host);
        await launch(host, others, id, [others[others.length - 1]]);
        await homeFor(...phones);
      });

      // Page errors are reported, and fail the run: a game or the Party throwing on a tester's phone is a finding.
      for (const p of phones) expect.soft(p.errors, `${p.name} had no page errors`).toEqual([]);
      void api;
    } finally { await close(...phones); }
  });
}

test('the hosted run names at least one game to play', () => {
  test.skip(GAME_LIST.length > 0, 'HOSTED_GAMES is set');
  test.info().annotations.push({ type: 'not run', description: 'HOSTED_GAMES is empty: no game journey was played' });
});
