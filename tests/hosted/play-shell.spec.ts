import { test, expect } from '@playwright/test';
import { BASE, GAMES, phone, post, state } from './hosted';

/**
 * PROPOSAL play_shell (AVR-766) on a real deployment: with the proposal on in party-core.json, a round
 * of a game on the game origin runs inside the Party's /party/play.html, and the game really loads in
 * the frame (the game origin's frame-ancestors names the Party). Skipped where the proposal is off.
 * Not shown: an installed app on a phone, which is what AVR-766 is for.
 */
const GAME = process.env.HOSTED_SHELL_GAME || 'colyseus-tanks';

test('a round runs inside /party/play.html and the game loads in its frame', async ({ browser }) => {
  test.setTimeout(120_000);
  const ana = await phone(browser, 'Shell-A'), ben = await phone(browser, 'Shell-B');
  try {
    const view = await state(ana);
    test.skip(!(view?.proposals || []).includes('play_shell'), 'the play_shell proposal is off here');
    const refused: string[] = [];
    for (const p of [ana, ben]) p.page.on('console', (m) => { if (/frame-ancestors|Refused to frame/i.test(m.text())) refused.push(m.text()); });
    const host = view.me.host ? ana : ben;
    const launched = await post(host, 'session/launch', { game: GAME, if_version: (await state(host)).version });
    expect(launched.status(), await launched.text()).toBe(200);
    for (const p of [ana, ben]) {
      await expect(p.page).toHaveURL(`${BASE}/party/play.html`, { timeout: 30_000 });
      await expect(p.page.locator('#game')).toHaveAttribute('src', new RegExp(`^${GAMES}/games/${GAME}/`));
      await expect.poll(() => p.page.frames().some((f) => f.url().startsWith(`${GAMES}/games/${GAME}/`))).toBe(true);
      const frame = p.page.frames().find((f) => f.url().startsWith(`${GAMES}/games/${GAME}/`))!;
      await expect(frame.locator('body')).not.toBeEmpty({ timeout: 20_000 });
      // joined, not only loaded: Tanks fills its scoreboard once matchmaking answers (it says
      // "Could not join the game" while it does not)
      if (GAME === 'colyseus-tanks') await expect(frame.getByText('Yellow', { exact: true })).toBeVisible({ timeout: 20_000 });
      await expect(p.page.locator('iframe[data-avrana-party-layer]')).toHaveAttribute('data-avrana-party-layer', 'button');
    }
    expect(refused, 'no frame was refused').toEqual([]);
    const ended = await post(host, 'session/end', { if_version: (await state(host)).version });
    expect(ended.status(), await ended.text()).toBe(200);
    for (const p of [ana, ben]) await expect(p.page).toHaveURL(new RegExp(`^${BASE}/party/(#.*)?$`), { timeout: 30_000 });
  } finally {
    for (const p of [ana, ben]) {
      await post(p, 'leave', {}).catch(() => null);
      await p.context.close();
    }
  }
});
