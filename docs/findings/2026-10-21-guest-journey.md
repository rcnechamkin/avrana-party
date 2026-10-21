# The guest journey: one browser spec from arrival to the next round (AVR-698)

Observed 2026-10-21 (Sprint 06, track 06C). Party branch `claude/avr-698-guest-journey`, based on
`main` at `8de7ef2`. Evidence is from Windows 11 with **Chromium emulating a Pixel 7**, a real Party
Core behind `avrana/web/devserver.py --party --test-controls`, and the dev server's stub game pages.
It is not iPhone Safari, not a physical Android phone, not Wi-Fi, not nginx or HTTPS, and not the Pi.
Hosted CI did not run. Nothing here is deployed.

## 1. What the journey covers

`tests/party/guest-journey.spec.ts` (project `phones-chromium`) uses separate browser contexts as
phones, each with its own cookie jar and `localStorage`, and the helpers the other Party suites use
(`tests/lib/phones.ts`, `tests/lib/frame.ts`; two small helpers were added to `phones.ts`:
`arrive` for a phone that does not wait for Party Home to settle and `chooseName` for a guest with no
profile). Every assertion is a thing the code or `PARTY-LIFECYCLE.md`, ADR 0008, 0010 and 0011 (with
its AVR-580 amendment) already says. The Host leaves and ends through the Party layer, because that
is the only Host surface over a game page of the Party's own origin; the stub page opts in the way
`party-layer.spec.ts` does.

| # | Step | Where | Result |
|---|---|---|---|
| 1 | A new guest (no profile) arrives at Party Home and is asked to choose a name | BLUFF journey | pass |
| 2 | The guest joins; two new guests; counts and Host named on every phone | BLUFF journey | pass |
| 3 | The Host selects BLUFF; everyone is on the setup scene; only the Host can start (guests get `not_host`) | BLUFF journey | pass |
| 4 | Play and Watch chosen; a watcher reloads the scene and keeps the answer | BLUFF journey | pass |
| 5 | The Host starts the round; roles are player, player, spectator | BLUFF journey | pass |
| 6 | A late guest joins: taken to the round, a watcher, counted once; a role request is `round_on` | BLUFF journey; EXPO and Gauntlet II; game origin | pass |
| 7 | A player reloads (same member id, session and seat); a watcher's phone is suspended and woken (`goQuiet` plus clock advance) | BLUFF journey | pass |
| 8 | A player loses the Party box and gets it back; the drawer says so while it is out | BLUFF journey | pass |
| 9 | The Host leaves from the layer; the confirmation names the successor; the round goes on; the old Host has no authority | BLUFF journey | pass |
| 10 | The new Host ends the round from the layer, after a confirmation | BLUFF journey | pass |
| 11 | Members are at Party Home; the one who left sees Reconnect, comes back once and is not the Host | BLUFF journey | pass |
| 12 | The new Host launches BLUFF again: fresh setup, no carried-over answers, a former watcher may play, ids and names unchanged | BLUFF journey | pass |

Further cases, each its own test:

- **Direct-launch games.** The Host's phone is suspended at Party Home; Away is said; hosting passes
  to the earliest guest; the old Host wakes as a member. EXPO (two seats: two play, the third and a
  late guest watch). A guest's phone goes offline while the new Host ends the round and lands at Party
  Home when it is back. Gauntlet II (four seats, `late_join: supported`): four play, a fifth, late,
  watches (Core v0 admits every late member as a spectator, `core._late_admit`).
- **Setup edges.** A brand-new guest who arrives during setup lands on the scene and the Host's Start
  waits for them by name; a phone that goes quiet does not block Start (ADR 0010); two guests who type
  one name are two people (`Bob`, `Bob 2`) and a reload keeps the second. The Host leaves during
  setup, the next phone gets Start, she reconnects and chooses again.
- **Pi restart mid-round.** Every phone is brought to Party Home and is in the new Party once, with
  exactly one Host. Which phone hosts is not asserted (the next member seen claims it).
- **Game origin** (`guest-journey-origins.spec.ts`, project `two-origins-chromium`, via a one-line
  change to `playwright.party.config.ts`). A guest new to the Party arrives mid-round and is taken to
  the registered game origin once, never to the Party origin's copy, counted once.

## 2. Failures found

### F1. A move to a round that arrived while the phone was offline left it on the browser's error page

- **Symptom.** A phone on Party Home or on a round's setup scene is offline (`navigator.onLine` is
  false) at the moment the Party moves to the round. It lands on `chrome-error://chromewebdata/`
  ("no internet") and stays there after the network returns: a dead end that needs a manual reload,
  and a reload of that page has lost the Party's own hand-off. ADR 0011 decision 3 says a move that
  arrives while the phone is offline waits for the network.
- **How it was reached.** A long poll already on its way is answered by Party Core, and the phone's
  connection drops before the page acts on the answer (reproduced with Playwright's `setOffline`; a
  poll in flight is delivered, the navigation that follows is refused).
- **Root cause.** The wait existed only in the game page's follower (`party-follow.js` `leave()`).
  Party Home's `leaveForRound()` in `web/party/app.js` navigated at once.
- **Fix.** `web/party/app.js`: when `navigator.onLine === false`, `leaveForRound()` holds the move
  (`holdMove`), says "Waiting for the connection to take you to <game>…" on the going screen, and
  looks again from the latest view when the browser reports `online` or when Party Core answers a try
  made since (`releaseMove`). Same rule as `party-follow.js`; a held move is never replayed from a
  stale view, so a round that ended meanwhile sends the phone home. 28 lines, no protocol change, no
  change to who owns navigation.
- **Regression test.** `guest-journey.spec.ts`, "AVR-698: a phone that is offline when the Party
  moves waits for the network...". It holds the phone's own poll, lets Party Core answer it, drops the
  radio, then delivers the answer: for Party Home (EXPO) and for the briefing (BLUFF), and a third
  case where the round ends while the phone is away. It fails on `main` (the navigation request goes
  out and the page never shows the waiting line) and passes with the fix.

- **Independent review (same day), and what changed.** The first version released a held move on the
  browser's `online` event from the view it already had (the held one), and otherwise only on the next
  long-poll answer (up to 20 s). Reproduced: held for EXPO, the Party went home while the phone was
  offline, and on `online` the phone navigated to the round that had ended. Now a held move asks Party
  Core once at once, every 2 s and on `online` (`party.refresh()`, one short ask, its view accepted), and
  the move is decided again only from that answer: a round that ended keeps the phone on Party Home, and
  a stale `navigator.onLine === false` on a working network costs one request, not 20 s. The hold also
  cancels an earlier navigation's watchdog (it could retry an old target while offline), and it ends when
  the Party is no longer in a round. Second regression test: "a held move is decided again from a fresh
  answer; a stale offline flag does not hold a working phone" (fails on the first version: the phone
  is sent to the ended round).
- **Left as it is.** While a move is held the going screen offers no way back to Party Home; it says it
  is waiting for the connection. ADR 0011 says the move waits; a way out there is a UI change for the
  owner, not part of this fix.

## 3. Looked at, not changed

- **A successor Host's Back button.** The Host who started a round gets Party Home behind the game
  (AVR-476), so Back reaches the Party's way out. A phone that becomes Host mid-round by succession
  arrived by `location.replace`, so Back leaves the site (to `about:blank` in the test). ADR 0011 and
  `host-escape.spec.ts` define a follower's Back as unchanged; the layer's drawer is the Host's way
  out in that case. Whether a successor should also get Party Home behind the game is a contract
  question for the owner, not a bug fix.
- **Leave from another tab while on the briefing.** The briefing has no Leave (people only). A Leave
  made from another tab takes the phone off the scene to the page it came from, which offers
  "Reconnect to play", not the Reconnect? panel. It works; asserted as such.
- **A page that loses the network while it is still loading** (module scripts fail) never starts its
  follower. That is a load failure of the page, in the test's stub; not asserted.
- **A name that is taken** is silently shown with a number (`Bob 2`). Defined by `_unique`; the guest's
  own profile still reads `Bob`. Not changed.
- **`late_join: supported`** (Gauntlet II) is not honoured by Core v0 (spectators only), as the code and
  `PARTY-LIFECYCLE.md` say.

## 4. Not covered

A round the game itself completes (the results screen and Play again), because the stub pages do not
sign a result. A cross-origin Host departure and end: the stub on the game origin has no bridge that
follows the Party, so only the arrival is tested there (the moves between origins are
`follow-origin.spec.ts`). Limited Mode. Chat.

## 5. Physical only (not proven here)

iPhone Safari and Android Chrome on hardware: a locked or backgrounded phone (here a page is
navigated away or its requests are blocked, and `setOffline` stands in for a Wi-Fi drop; neither is a
radio), the system Back gesture, cookies in a framed bridge under ITP, the captive-portal sheet, real
Wi-Fi roaming, the Pi's own restart, and nginx and HTTPS. `navigator.onLine` on a real phone can lag
or disagree with reachability, which is why the fix also releases on an answer from Party Core. Owner
runbooks for the physical checks are the existing ones in `docs/runbooks/`.

## 6. Commands and results

```
AVRANA_PARTY_DEV_PORT=8284 AVRANA_PYTHON=python npx playwright test -c playwright.party.config.ts \
  tests/party/guest-journey.spec.ts tests/party/guest-journey-origins.spec.ts --repeat-each=3
AVRANA_PARTY_DEV_PORT=8284 AVRANA_PYTHON=python npx playwright test -c playwright.party.config.ts
node --test tests/offline/*.test.mjs
npm run check:ui ; npm run check:repo
```

Results are recorded in the pull request.
