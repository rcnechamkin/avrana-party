import { test, expect } from '@playwright/test';
import { BASE, GAME_LIST, OWNER_ASSIST, api, resetIfLocal, close, homeFor, hostOf, launch, phone, post, state, type Phone } from './hosted';

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
test.beforeEach(() => resetIfLocal());
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
    // A phone that arrived straight on the game page has nothing behind it: back leaves the site, and the
    // tester opens the Party again, which must bring them back to the round.
    if (!p.page.url().startsWith('http')) await p.page.goto(`${BASE}/party/`);
    await atGame(p);
  } finally { await homeFor(...phones).catch(() => undefined); await close(...phones); }
});

// ADR 0006 as amended (owner, 2026-10-22). The Host is a seated player in an active round and their
// phone goes; so does another seated player's. Party authority passes, at the liveness window (45 s)
// plus host grace (30 s), to the player whose page is live, never to a seat whose phone is gone. The
// old Host keeps the seat and gets nothing back on return. The new Host ends the round and everyone
// is home. No in-game role or turn moves with the role: the game owns those.
test('the Host goes away mid-game: Party authority passes to a live member, every seat and role stays, and the new Host ends the round', async ({ browser }) => {
  const { phones, host, others } = await table(browser, ['Abe', 'Bo', 'Cy']);
  const [stale, live] = others[0].name.startsWith('Bo') ? others : [others[1], others[0]];
  try {
    await launch(host, others, GAME);
    // A two-seat game (Checkers) seats the Host and Bo and makes Cy a watcher; a bigger one seats all three.
    // Either way the heir is the live member, and succession moves Party authority only: no seat, no role.
    const before = await state(live);
    const hostRole = (await state(host)).session?.my_role;
    const seats = Object.fromEntries(before.members.map((m: any) => [m.name, m.presence]));
    const gone = Date.now();
    await host.context.setOffline(true);      // the Host's phone is gone, no goodbye
    await stale.context.close();              // and so is Bo's, who joined before Cy

    const heir = await hostOf([live], 120_000);
    const after = (Date.now() - gone) / 1000;
    test.info().annotations.push({ type: 'succession', description: `${after.toFixed(0)} s after the Host's phone went` });
    expect(heir, 'the live member, not the stale one who joined first').toBe(live);
    expect(after, 'not before the grace ran out').toBeGreaterThanOrEqual(55);
    const now = await state(live);
    expect(now.session?.state, 'the round goes on').toBe('active');
    expect(now.session?.my_role, 'the new Host keeps the role they had').toBe(before.session?.my_role);
    const presence = Object.fromEntries(now.members.map((m: any) => [m.name, m.presence]));
    expect(presence[host.name], 'the old Host keeps their seat').toBe('playing');
    expect(presence, 'nobody moved: the same people, each where they were').toEqual(seats);

    // The old Host's phone comes back: on the game page, seated, and not the Host.
    await host.context.setOffline(false);
    await host.page.reload();
    await expect(host.page).toHaveURL(new RegExp(`/games/${GAME}/`), { timeout: 60_000 });
    const back = await state(host);
    expect([back.me.host, back.session?.my_role]).toEqual([false, hostRole]);

    // The new Host ends the round (what the game page's End control asks Party Core for).
    const res = await post(live, 'session/end', { if_version: now.version });
    expect(res.status(), 'the new Host may end it').toBe(200);
    await expect.poll(async () => (await state(live))?.location?.at, { timeout: 30_000 }).toBe('home');
    expect((await state(live)).session?.outcome).toBe('ended_by_host');
    for (const p of [host, live]) await expect(p.page, p.name).toHaveURL(`${BASE}/party/`, { timeout: 60_000 });
    expect((await state(host)).me.host).toBe(false);
  } finally { await close(host, live); }
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
