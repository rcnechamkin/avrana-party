import { test, expect } from '@playwright/test';
import { place, openGame } from '../lib/frame';
import { GAMES, PARTY, joinParty, leaveAll, partyState, phone, type Phone } from './phones';

/**
 * AVR-338, part 1: the INSTALLED Hello Party package played in real browsers, end to end, through the
 * Party's own experience. The appliance behind these URLs is built by
 * experiments/native-game/package-browser-proof.sh (real systemd, Party Core, the staged package
 * running as a socket-activated DynamicUser process, the committed nginx site, a throwaway
 * certificate). Discovery is real: the install itself writes the effective catalog
 * (AVR-337) that the committed nginx site serves. Tier 2 on a CI runner: not a phone, not Wi-Fi, not the Pi.
 */
test.skip(!process.env.AVRANA_PACKAGE_BROWSER_PROOF, 'runs only inside experiments/native-game/package-browser-proof.sh');

const GAME_PAGE = new RegExp('^' + GAMES.replace(/\./g, '\\.') + '/games/hello/');
const PARTY_HOME = `${PARTY}/party/`;
const secretOf = (p: Phone) => p.page.locator('#secret').innerText();
const word = (w: string) => new RegExp(`\\b${w}\\b`, 'i');

const b64 = (w: string) => Buffer.from(w).toString('base64').replace(/=+$/, '');
/** Does this text carry the word: bare (on word boundaries), or as its base64? */
const carries = (text: string, w: string) => word(w).test(text) || text.includes(b64(w));
/** The channels a phone was told things on. JSON bodies are the state; static pages and scripts (HTML, CSS, JS) are
 * only searched for the quoted word, since a colour called "amber" in a stylesheet is not a leak. */
const stateBodies = (p: Phone) => p.bodies.filter((b) => /json/.test(b.type)).map((b) => b.text);
const everyBody = (p: Phone) => p.bodies.map((b) => b.text);
const leaks = (p: Phone, w: string) => carries(stateBodies(p).join('\n'), w) || carries(p.frames.join('\n'), w)
  || everyBody(p).some((t) => t.includes(`"${w}"`));
const dom = (p: Phone) => p.page.evaluate(() => document.documentElement.outerHTML + '\n' + document.body.innerText);

test('Hello Party, installed: admission, discovery, launch, private views, reconnect, result, home', async ({ browser }, info) => {
  const ana = await phone(browser, info, 'Ana');
  const ben = await phone(browser, info, 'Ben');
  const all: Phone[] = [ana, ben];
  try {
    // 1. Party admission for real: the first phone is the Host.
    await joinParty(ana);
    await expect(ana.page.locator('#party-members')).toContainText('Ana (you)');
    await joinParty(ben);
    await expect(ben.page.locator('#party-members')).toContainText('Ben (you)');
    await expect(ana.page.locator('#party-count')).toHaveText('2 people');
    await expect(ana.page.locator('#party-host')).toContainText('You’re the host');
    await expect(ben.page.locator('#party-host')).toContainText('Ana is the host');
    const cookies = await ana.context.cookies(PARTY);
    expect(cookies.length).toBeGreaterThan(0);
    expect(cookies.every((c) => c.secure && c.httpOnly)).toBe(true);   // the production cookie, not a weakened one

    // 2. Discovery: the installed package is a game in Party Home's Library, and only the Host can start it.
    await place(ben.page, 'library');
    await place(ana.page, 'library');
    await expect(ana.page.locator('#games [data-game="hello"]')).toBeVisible();
    await expect(ben.page.locator('#games [data-game="hello"]')).toBeVisible();
    const theirs = await openGame(ben.page, 'hello');
    await expect(theirs.getByRole('button', { name: 'Start for everyone' })).toHaveCount(0);
    const mine = await openGame(ana.page, 'hello');

    // 3. The Host launches it from Party: both phones are taken to the game's own origin and page.
    await mine.getByRole('button', { name: 'Start for everyone' }).click();
    for (const p of all) await expect(p.page).toHaveURL(GAME_PAGE);
    for (const p of all) {
      await expect(p.page.locator('#card')).toBeVisible();
      await expect(p.page.locator('#secret')).not.toHaveText('');
      await expect(p.page.locator('#status')).toHaveText('Say hello when you are ready.');
      await expect(p.page.locator('iframe[title="Avrana Party"]')).toHaveAttribute('src', `${PARTY}/party/bridge.html`);
    }
    const anaWord = await secretOf(ana), benWord = await secretOf(ben);
    expect(anaWord).not.toBe(benWord);                                    // each seat holds a word of its own

    // A watcher joins late: the Party sends it to the game, as a spectator with no card.
    const cy = await phone(browser, info, 'Cy');
    all.push(cy);
    await joinParty(cy, { intoRound: true });
    await expect(cy.page).toHaveURL(GAME_PAGE);
    await expect(cy.page.locator('#status')).toHaveText('You are watching.');
    await expect(cy.page.locator('#card')).toBeHidden();
    await expect(cy.page.locator('#say')).toBeHidden();
    await expect(cy.page.locator('#secret')).toHaveText('');

    // 4. Private views: what each phone's DOM shows and what each phone received never holds another's word.
    for (const [p, mineWord, others] of [[ana, anaWord, [benWord]], [ben, benWord, [anaWord]], [cy, '', [anaWord, benWord]]] as const) {
      const shown = await dom(p);
      for (const other of others) {
        expect(shown, `${p.name}'s page shows another seat's word`).not.toMatch(word(other));
        expect(leaks(p, other), `${p.name} was sent another seat's word`).toBe(false);
      }
      // Positive control, per channel: the phone's own word must show up where the state travels, or the recorder is blind.
      if (mineWord) {
        expect(carries(stateBodies(p).join('\n'), mineWord), `${p.name}'s own word is in its JSON bodies (the HTTP channel works)`).toBe(true);
      }
      console.log(`[${p.name}] channels: ${stateBodies(p).length} JSON bodies carried ${mineWord ? 'its own word' : 'no word'}; ${p.frames.length} WebSocket frames`);
    }
    // The game page keeps no cookie of the Party's and never calls the Party API itself (the bridge frame does).
    for (const p of all) {
      expect(await p.context.cookies(GAMES), p.name).toEqual([]);
      expect(p.gameMainFrameCalls, p.name).toEqual([]);
    }

    // Gameplay: Ana says hello; Ben, a different phone, sees it appear.
    await ana.page.locator('#text').fill('hello from Ana');
    await ana.page.locator('#send').click();
    await expect(ana.page.locator('#status')).toHaveText('Waiting for the others.');
    await expect(ben.page.locator('#board')).toContainText('Ana: hello from Ana');
    await expect(cy.page.locator('#board')).toContainText('Ana: hello from Ana');

    // 5. Reconnect: Ben's page is reloaded mid-game and gets the same seat, word and board back.
    await ben.page.reload();
    await expect(ben.page).toHaveURL(GAME_PAGE);
    await expect(ben.page.locator('#secret')).toHaveText(benWord);
    await expect(ben.page.locator('#board')).toContainText('Ana: hello from Ana');
    await expect(ben.page.locator('#say')).toBeVisible();
    // and a dropped network: Ben goes offline and comes back; his seat is still his and he can still play
    await ben.context.setOffline(true);
    await ben.page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await ben.page.waitForTimeout(2500);
    const callsBefore = ben.gameApiRequests;
    await ben.context.setOffline(false);
    await ben.page.evaluate(() => window.dispatchEvent(new Event('online')));
    // The page's own loop must talk to its game again by itself (a poll or redeem request starts after the network is back)
    await expect.poll(() => ben.gameApiRequests, { timeout: 45_000 }).toBeGreaterThan(callsBefore);
    await expect(ben.page.locator('#status')).not.toContainText('Lost the connection');
    await expect(ben.page.locator('#secret')).toHaveText(benWord);

    // 6. Completion: the last hello ends the game; Party Core accepts the signed result.
    await ben.page.locator('#text').fill('hello from Ben');
    await ben.page.locator('#send').click();
    for (const p of all) {
      await expect(p.page.locator('#done')).toBeVisible();
      await expect(p.page.locator('#done-detail')).toContainText('2 greetings');
    }
    await expect.poll(async () => (await partyState(ana)).session?.outcome, { timeout: 30_000 }).toBe('completed');
    const session = (await partyState(ana)).session;
    expect(session.state).toBe('ended');
    expect(session.result_summary.game).toBe('hello');
    expect(Object.fromEntries(session.result_summary.players.map((e: any) => [e.name, e.standing]))).toEqual({ Ana: 'won', Ben: 'won' });
    await expect(ana.page.locator('#host-actions')).toBeVisible();
    await expect(ben.page.locator('#host-actions')).toBeHidden();
    await ana.page.locator('#home').click();                              // the Host takes everyone home
    try {
      for (const p of all) await expect(p.page).toHaveURL(PARTY_HOME, { timeout: 8000 });
    } catch {
      // The one symptom seen once in CI on WebKit: the Host's page still shows the game 8 s after the tap. It is
      // retried ONCE, loudly (marker below, counted by the script, kept as an attachment): a possible product race in
      // the bridge's "go home", not something to hide. Any other symptom falls through to the assertion and fails.
      if (!ana.page.url().startsWith(GAMES)) throw new Error('Party Home did not take, and not by the known symptom');
      const state = await partyState(ben).then((s) => ({ location: s.location, session: s.session && { state: s.session.state, outcome: s.session.outcome } })).catch(() => null);
      const evidence = { bridge: await ana.page.evaluate(() => (window as any).__bridge).catch(() => null),
        partyCalls: ana.partyCalls.slice(-8), urls: all.map((p) => `${p.name} ${p.page.url()}`), state };
      console.log(`HOME-RETRY-FIRED ${JSON.stringify(evidence)}`);
      info.annotations.push({ type: 'home-retried', description: 'first tap on "Party Home" did not move the party' });
      await info.attach('home-retry-evidence.json', { body: JSON.stringify(evidence, null, 1), contentType: 'application/json' });
      await info.attach('home-retry-host.png', { body: await ana.page.screenshot(), contentType: 'image/png' });
      await ana.page.locator('#home').click();
    }
    for (const p of all) await expect(p.page).toHaveURL(PARTY_HOME);
    await expect(ben.page.locator('#party-result')).toContainText(/won/);
    expect((await partyState(ben)).location.at).toBe('home');

    // The private words never crossed, whatever the phones did meanwhile (reconnect included).
    for (const [p, others] of [[ana, [benWord]], [ben, [anaWord]], [cy, [anaWord, benWord]]] as const)
      for (const other of others) expect(leaks(p, other), `${p.name} was sent another seat's word`).toBe(false);
  } finally {
    await leaveAll(all);
    for (const p of all) await p.context.close();
  }
});
