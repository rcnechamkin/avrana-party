import { test, expect, type Page } from '@playwright/test';
import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

/**
 * Rollback, rehearsed (docs/design/ux-redesign/IMPLEMENTATION-PLAN.md, "Dependencies and
 * rollback"): flip, reload, verify the restored build; and going back loses no one's favorites
 * or recently played.
 *
 * Two releases are built with the real build step (avrana.web.build): NEW from this checkout's
 * web/party/, OLD from the same folder at AVRANA_ROLLBACK_FROM (default origin/main). A `current`
 * link points at one of them and the dev server serves through it, with a real Party Core that
 * is not restarted: the flip touches nothing but the link, as `ops/install-party-web.sh
 * --rollback` touches nothing but `current` on the Pi.
 *
 * What this does not show: nginx, the Pi, the install script itself, Safari, or a phone's own
 * cache. The owner's flip on the appliance is still the owner's to verify.
 */
const ROOT = path.resolve(__dirname, '..', '..');
const PYTHON = process.env.AVRANA_PYTHON || 'python3';
const FROM = process.env.AVRANA_ROLLBACK_FROM || 'origin/main';
const PORT = Number(process.env.AVRANA_ROLLBACK_PORT || 8186);
const BASE = `http://127.0.0.1:${PORT}`;
const git = (...args: string[]) => execFileSync('git', args, { cwd: ROOT, maxBuffer: 64 * 1024 * 1024 });

let work = '', server: ChildProcess | null = null;
const releases = { old: { dir: '', build: '', commit: '' }, new: { dir: '', build: '', commit: '' } };

/** web/party/ as it was at a commit, written out file by file (no archive tool needed). */
function checkoutShell(commit: string, into: string) {
  for (const file of git('ls-tree', '-r', '--name-only', commit, 'web/party').toString().split('\n').filter(Boolean)) {
    const out = path.join(into, file.slice('web/party/'.length));
    mkdirSync(path.dirname(out), { recursive: true });
    writeFileSync(out, git('show', `${commit}:${file}`));
  }
}

/** The real build step, on a given source folder: a stamped sw.js and a version.json. */
function build(source: string, out: string, commit: string, id: string) {
  execFileSync(PYTHON, ['-c',
    'import sys, pathlib; from avrana.web import build; build.build(sys.argv[2], sys.argv[4], sys.argv[3], source=pathlib.Path(sys.argv[1]))',
    source, out, commit, id], { cwd: ROOT });
}

/** Point `current` at a release: the whole of a flip. */
function flip(to: 'old' | 'new') {
  const link = path.join(work, 'current');
  try { unlinkSync(link); } catch { try { rmSync(link, { recursive: true }); } catch { /* first time */ } }
  symlinkSync(releases[to].dir, link, 'junction');          // a junction on Windows, a plain link elsewhere
}

test.beforeAll(async () => {
  const head = git('rev-parse', 'HEAD').toString().trim();
  const old = git('rev-parse', `${FROM}^{commit}`).toString().trim();
  work = mkdtempSync(path.join(tmpdir(), 'avrana-rollback-'));
  const source = path.join(work, 'old-source');
  checkoutShell(old, source);
  releases.old = { dir: path.join(work, 'releases', 'old'), commit: old, build: old.slice(0, 12) };
  // the working tree is what is being proposed; its id says so when it is not exactly HEAD
  const dirty = git('status', '--porcelain', '--', 'web/party').toString().trim().length > 0;
  releases.new = { dir: path.join(work, 'releases', 'new'), commit: head, build: head.slice(0, 12) + (dirty ? '-wip' : '') };
  mkdirSync(path.join(work, 'releases'), { recursive: true });
  build(source, releases.old.dir, old, releases.old.build);
  build(path.join(ROOT, 'web', 'party'), releases.new.dir, head, releases.new.build);
  flip('new');
  server = spawn(PYTHON, ['-m', 'avrana.web.devserver', '--port', String(PORT), '--web', path.join(work, 'current'), '--party', '--test-controls'],
    { cwd: ROOT, stdio: 'ignore' });
  await expect.poll(async () => { try { return (await fetch(`${BASE}/party/version.json`)).ok; } catch { return false; } }, { timeout: 20_000 }).toBe(true);
  console.log(`rollback rehearsal: NEW ${releases.new.build} (${head}) <-> OLD ${releases.old.build} (${FROM})`);
});

test.afterAll(async () => {
  if (server) server.kill();
  await new Promise((r) => setTimeout(r, 300));
  if (work) { try { rmSync(work, { recursive: true, force: true }); } catch { /* the server may still hold a file for a moment */ } }
});

const served = async (page: Page) => (await page.request.get(`${BASE}/party/version.json`)).json();
const running = (page: Page) => page.evaluate(async () => (await (await fetch('version.json', { cache: 'no-store' })).json()).build);
const kept = (page: Page) => page.evaluate(() => ({ favorites: localStorage.getItem('lg-favorites'), recent: localStorage.getItem('lg-recent'),
  name: localStorage.getItem('wc-name'), view: localStorage.getItem('avrana-library-view') }));
const caches = (page: Page) => page.evaluate(async () => (await window.caches.keys()).filter((k) => k.startsWith('avrana-party-shell-')));
const ready = async (page: Page) => { await expect(page.locator('html')).toHaveAttribute('data-ready', 'true'); };

test('flip back, reload, verify: the restored build runs, and favorites and recently played are all still there', async ({ page }) => {
  expect(releases.old.build).not.toBe(releases.new.build);

  // ---- the new release is running; a phone uses it ---------------------------------------------
  await page.goto(`${BASE}/party/`);
  await ready(page);
  expect((await served(page)).build).toBe(releases.new.build);
  await page.locator('#nav a[data-go="party"]').click();
  await page.locator('#player-chip').click();
  await page.locator('#profile-name').fill('Rae');
  await page.getByRole('button', { name: 'Save profile' }).click();
  await expect(page.locator('#party-members')).toContainText('Rae (you)');
  // a favorite, a new-build setting, and a game played (the Host of one starts a round for everyone)
  await page.locator('#nav a[data-go="library"]').click();
  await page.locator('#lib-view').click();
  await page.locator('#view-choices [data-v="list"]').click();
  await page.locator('#games [data-game="bluff"]').click();
  await page.locator('#game-detail [data-fav="bluff"]').click();
  await expect(page.locator('#game-detail [data-fav="bluff"]')).toHaveAttribute('aria-pressed', 'true');
  await page.goBack();
  await page.locator('#games [data-game="expo"]').click();
  await page.locator('#game-detail').getByRole('button', { name: 'Start for everyone' }).click();
  await expect(page).toHaveURL(/\/games\/expo\//);
  const end = await page.request.post(`${BASE}/party/api/session/end`, { data: { if_version: (await (await page.request.get(`${BASE}/party/api/state`)).json()).version },
    headers: { 'Content-Type': 'application/json', Origin: BASE } });
  expect(end.status()).toBe(200);
  await expect(page).toHaveURL(/\/party\/$/);                              // the round's page brings the phone home by itself
  await ready(page);
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);   // the offline copy is in play
  await expect.poll(() => caches(page)).toEqual([`avrana-party-shell-${releases.new.build}`]);
  const before = await kept(page);
  expect(JSON.parse(before.favorites || '[]').length).toBe(1);
  expect(JSON.parse(before.recent || '[]').length).toBe(1);
  expect(before).toMatchObject({ name: 'Rae', view: 'list' });
  await expect(page.locator('#home-lead')).toContainText('You played this last.');

  // ---- 1. flip: `current` points at the release before; nothing else is touched -----------------
  flip('old');
  expect((await served(page)).build).toBe(releases.old.build);             // what the box now serves
  expect((await (await page.request.get(`${BASE}/party/api/state`)).json()).members.map((m: { name: string }) => m.name)).toEqual(['Rae']);   // the Party never noticed
  // the flip alone is not a finished rollback: the page that was open is still the page it loaded
  await expect(page.locator('#net')).toHaveCount(1);                       // (an element only the new build has)

  // ---- 2. reload: the phone fetches the restored files (the worker is network-first) -----------
  await page.reload();
  await ready(page);

  // ---- 3. verify the restored build -----------------------------------------------------------
  expect(await running(page)).toBe(releases.old.build);
  await expect.poll(() => caches(page), { timeout: 20_000 }).toEqual([`avrana-party-shell-${releases.old.build}`]);   // the newer offline copy is gone
  await page.goto(`${BASE}/party/diag/`);
  await expect(page.locator('#build')).toContainText(releases.old.build);  // "Shell build", as the runbook says to check
  await page.goto(`${BASE}/party/`);
  await ready(page);
  // nothing a person kept is lost, and the same person is still in the same Party
  expect(await kept(page)).toEqual(before);
  expect((await (await page.request.get(`${BASE}/party/api/state`)).json()).me).toMatchObject({ name: 'Rae', host: true });
  // then walk it: Home, the Library, a briefing. What the restored build's own pages look like
  // is that build's business: a build with the frame (slice 1) is walked through its bar and its
  // shelves; an older one, which has neither, is only asked for its games and a briefing.
  const framed = (await page.locator('#nav a[data-go="library"]').count()) > 0;
  if (framed) {
    await expect(page.locator('#party-lede')).toBeVisible();
    await page.locator('#nav a[data-go="party"]').click();
    await expect(page.locator('#party-members')).toContainText('Rae (you)');
    await page.locator('#nav a[data-go="library"]').click();
    await expect(page.locator('#games [data-game="bluff"]')).toBeVisible();
    await page.locator('#game-views [data-view="favorites"]').click();
    await expect(page.locator('#games [data-game]')).toHaveCount(1);       // the favorite, shown by the restored build
    await expect(page.locator('#games [data-game="bluff"]')).toBeVisible();
    await page.locator('#game-views [data-view="recent"]').click();
    await expect(page.locator('#games [data-game="expo"]')).toBeVisible(); // and what was played
    await page.locator('#game-views [data-view="all"]').click();
  } else {
    console.log('rollback rehearsal: the restored build has no frame; its shelves are not walked');
    await expect(page.locator('#games [data-id="bluff"]')).toBeVisible();   // (how that build marks a title)
  }
  const briefing = await page.request.post(`${BASE}/party/api/session/launch`, { data: { game: 'bluff', if_version: (await (await page.request.get(`${BASE}/party/api/state`)).json()).version },
    headers: { 'Content-Type': 'application/json', Origin: BASE } });
  expect(briefing.status()).toBe(200);
  await expect(page.locator('#scene')).toBeVisible();
  await expect(page.locator('#scene-title')).toHaveText('BLUFF');
  expect((await page.request.post(`${BASE}/party/api/session/end`, { data: { if_version: (await (await page.request.get(`${BASE}/party/api/state`)).json()).version },
    headers: { 'Content-Type': 'application/json', Origin: BASE } })).status()).toBe(200);
  await expect(page.locator('#scene')).toBeHidden();

  // ---- and forward again: going back was not a one-way door -------------------------------------
  flip('new');
  await page.reload();
  await ready(page);
  expect(await running(page)).toBe(releases.new.build);
  await expect.poll(() => caches(page), { timeout: 20_000 }).toEqual([`avrana-party-shell-${releases.new.build}`]);
  expect(await kept(page)).toEqual(before);
  await expect(page.locator('#home-lead')).toContainText('You played this last.');
  await page.locator('#nav a[data-go="library"]').click();
  await expect(page.locator('#games')).toHaveAttribute('data-view', 'list');   // the new build's own setting waited through the rollback
});
