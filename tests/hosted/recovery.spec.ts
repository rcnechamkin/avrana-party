import { test, expect } from '@playwright/test';
import { BASE, GAME_LIST, OWNER_ASSIST, api, close, homeFor, hostOf, launch, phone, state, type Phone } from './hosted';

// Failure and recovery on a deployed Party (H3), through the network as a tester's phone has it: a refresh,
// a lost connection, a Host who goes away (Party Core's own timing: away after 45 s, hosting passes 30 s
// later), a late spectator, back navigation and repeated launches. Each runs on the first game in
// HOSTED_GAMES. Cases that need the owner at the VM (a killed game process) run only with
// HOSTED_OWNER_ASSIST=1 and say so; a case that cannot be exercised is skipped, never reported as passing.
const GAME = GAME_LIST[0];
test.beforeEach(({}, info) => {
  test.skip(!GAME, 'HOSTED_GAMES names the game the recovery cases run on');
  test.skip(info.project.name !== 'android-size', 'recovery cases run once');
});
test.setTimeout(420_000);

/** Two (or more) phones at Party Home, one of them the Host (an earlier run's Host may first have to pass it on). */
async function table(browser: any, names: string[]) {
  const phones: Phone[] = [];
  for (const n of names) phones.push(await phone(browser, n));
  const host = (await homeFor(...phones)) ?? (await hostOf(phones));
  return { phones, host, others: phones.filter((p) => p !== host) };
}
const atGame = (p: Phone) => expect(p.page).toHaveURL(new RegExp(`/games/${GAME}/`), { timeout: 60_000 });

test('a player refreshes mid-game and is back in the same round', async ({ browser }) => {
  const { phones, host, others } = await table(browser, ['Rae', 'Sol']);
  try {
    await launch(host, others, GAME);
    const p = others[0];
    const session = (await state(p)).session.id;
    await p.page.reload();
    await atGame(p);
    expect((await state(p)).session.id).toBe(session);
    expect((await state(p)).session.my_role).toBe('player');
  } finally { await homeFor(...phones).catch(() => undefined); await close(...phones); }
});

test('a phone loses its connection for 20 s mid-game and is followed back into the round', async ({ browser }) => {
  const { phones, host, others } = await table(browser, ['Tam', 'Uma']);
  try {
    await launch(host, others, GAME);
    const p = others[0];
    await p.context.setOffline(true);
    await p.page.waitForTimeout(20_000);
    await p.context.setOffline(false);
    await p.page.evaluate(() => window.dispatchEvent(new Event('online')));
    await expect.poll(async () => (await state(p))?.session?.my_role, { timeout: 60_000 }).toBe('player');
    await atGame(p);
  } finally { await homeFor(...phones).catch(() => undefined); await close(...phones); }
});

test('a late arrival joins a round that is on as a spectator, and comes home with the Party', async ({ browser }) => {
  const { phones, host, others } = await table(browser, ['Vic', 'Wren']);
  let late: Phone | null = null;
  try {
    await launch(host, others, GAME);
    late = await phone(browser, 'Xan');
    await atGame(late);
    expect((await state(late))?.session?.my_role).toBe('spectator');
    await homeFor(host, ...others, late);
  } finally { await homeFor(...phones).catch(() => undefined); await close(...phones, late); }
});

test('browser back from a game page does not strand the phone: the Party brings it back to the round', async ({ browser }) => {
  const { phones, host, others } = await table(browser, ['Yan', 'Zed']);
  try {
    await launch(host, others, GAME);
    const p = others[0];
    await p.page.goBack().catch(() => undefined);
    await atGame(p);
  } finally { await homeFor(...phones).catch(() => undefined); await close(...phones); }
});

test('the Host goes away mid-game: hosting passes to someone who is here, who brings everyone home', async ({ browser }) => {
  const { phones, host, others } = await table(browser, ['Abe', 'Bo']);
  try {
    await launch(host, others, GAME);
    await host.context.close();               // the Host's phone is gone, no goodbye
    const heir = await hostOf(others, 240_000);
    expect(others).toContain(heir);
    await homeFor(...others);
  } finally { await close(...others); }
});

test('five launches and returns in a row leave the Party usable', async ({ browser }) => {
  const { phones, host, others } = await table(browser, ['Cy', 'Di']);
  try {
    for (let i = 0; i < 5; i++) {
      await launch(host, others, GAME);
      await homeFor(...phones);
    }
    expect((await state(host)).location.at).toBe('home');
  } finally { await close(...phones); }
});

test('the open page runs the deployed shell build: no stale assets from an edge cache or an old worker', async ({ browser }) => {
  const ada = await phone(browser, 'Ed');
  try {
    const status = await (await api(ada, 'GET', 'status')).json();
    const shell = await ada.page.evaluate(async () => (await fetch('/party/version.json', { cache: 'no-store' })).json());
    test.skip(!status.web_release, 'this deployment reports no web release (a dev server)');
    expect(shell.build, 'the page loaded the deployed build').toBe(status.web_release.build);
  } finally { await close(ada); }
});

test('owner-assisted: the game process is killed mid-round; the Party says so and the Host can bring everyone home', async ({ browser }) => {
  test.skip(!OWNER_ASSIST, 'HOSTED_OWNER_ASSIST=1 with the owner at the VM: sudo systemctl kill avrana-game@<game>.service when asked');
  const { phones, host, others } = await table(browser, ['Fay', 'Gus']);
  try {
    await launch(host, others, GAME);
    console.log(`OWNER: now run on the VM: sudo systemctl kill avrana-game@${GAME}.service`);
    await expect.poll(async () => (await state(host))?.session?.state, { timeout: 300_000, intervals: [5000] }).not.toBe('active');
    await homeFor(...phones);
  } finally { await close(...phones); }
});
