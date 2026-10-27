# Select, then launch, for every game (AVR-701, with AVR-700)

- **Status:** proposal, 2026-10-26. Nothing is implemented. ADR 0011 is unchanged until the owner amends it. **Owner decisions required** (section 7).
- **Reads with:**
  - [ADR 0011](../../adr/0011-party-console-model.md), decision 1 (the location; "→ game for a game without a pregame") and decision 4 (the setup scene);
  - `avrana/party/core.py` (`launch`, `_open_session`, `start_round`, `setup_status`);
  - `web/party/lib/party-mode.js` (`destination`);
  - [UI-DESIGN-SYSTEM.md](../../UI-DESIGN-SYSTEM.md), the Concept K "Actual vs Proposal" table (K1 on Home: AVR-701; Ready 3/4: AVR-700);
  - the guests-browse-during-setup amendment (AVR-702), which is separate and not decided here.

## 1. What happens today

| Game kind | Host taps a game | Who plays | Where the party goes |
|---|---|---|---|
| **Pregame** (`"pregame": true`: BLUFF, EXPO, Courting) | `_open_session` puts the session in `setup`. Each member here chooses Play or Watch. The host's Start is gated by `setup_status` (everyone chose, min ≤ players ≤ max). | the choices | `location.at = setup`, so every phone is on Party Home's setup scene. The round starts only at Start. |
| **No pregame** (`"pregame": false`: Checkers, Hello, Best Guess, Tanks) | `_open_session` builds the roster **at once** and the session goes to `launching`. | members here, in join order, up to the maximum; `watch_next` members watch | straight to the game (`location.at = game` once the game accepts) |

So a Concept K "Selected for Party" moment (K1) exists only for pregame games. For every other game, one tap launches. Nobody can gather, see who is coming, or back out first.

## 2. Proposal

**A "select" setup for games without a pregame.** It is the same `setup` location, with no Play/Watch choice.

- **The host taps a game.** `_open_session` opens the session in `setup` for every game. For a game without a pregame:
  - the session carries `setup.kind = "select"`, and `"choose"` for pregame games;
  - no choices are collected, and `choose` is refused with "This game seats everyone who is here."
- **Where the party is:** `location.at = setup`. `destination()` already sends every member page to Party Home for `setup`, so no game page changes. Home shows K1, the selected game, with:
  - for the host: **Start** and a quiet **Choose another game**;
  - for everyone else: **Waiting for <host> to start**.
- **Start** (`start_round`): for a select setup, the roster is built exactly as `_open_session` builds it today (members here, join order, up to the maximum; `watch_next` members watch). Then the session goes to `launching`, so **the game sees nothing different**: it is launched with a roster at Start, as before.
- **Blocker:** only the game's minimum, counted over members here (not over choices): "2 players needed; 1 is here."
- **Unchanged:**
  - Choose another game and End (→ home);
  - host authority and succession;
  - one activity at a time (`busy` while a session is live);
  - a late arrival during setup is simply here at Start.
- **Idle selection:** a select setup left untouched for 10 minutes (D3) returns the party home with the system line "Back to Party Home". Nobody waits forever on a host who walked away. Succession still applies first.

**AVR-700, voluntary Ready, in the same setup (optional, D2).** During any setup, a member may tap **Ready**. Home shows "Ready 3/4". It is **never a gate**:
- the host can always start;
- Ready resets at every new setup;
- it is in memory only, like choices.

For pregame games, choosing Play or Watch already counts as Ready, so no second tap is asked for.

## 3. What changes, by file (not done here)

| Where | Change |
|---|---|
| `core.py` `_open_session` | always enter `SETUP`; record `kind` |
| `core.py` `start_round`, `setup_status` | the `select` branch: roster from presence, blocker from presence |
| `core.py` `choose` | refuse on a select setup |
| `core.py` | the idle return; `ready` set and view field (if D2) |
| view and contract | `session.setup.kind`, `session.setup.ready` (count, and this member's flag) |
| Party Home | K1 on Home for a select setup: Start, Choose another game, waiting line, Ready 3/4 |
| tests | unit tests for each branch; the browser journeys that tap a non-pregame game and expect the table at once (`multi-client`, `guest-journey`, the hosted drivers) must tap Start too |

Games change nothing: launch still carries a roster, and setup still routes to Party Home. A **paired Games review** is still needed, because every kit game's `party-driver.mjs` and the match scripts assume a one-tap launch.

## 4. Risks

- **An extra tap for every quick game.** It is the point of K1, but it costs a moment when the party is just "one more round". D1 offers a direct start for the host.
- **Every non-pregame launch path changes:** Core, Home, and the test drivers in both repositories. This is behind a default-off Core option (`select_then_launch`) until the owner turns it on, so the change can merge dark.
- **The roster is decided at Start, not at selection.** A member who arrives during the select setup plays. That is the same rule pregame setups already follow.

## 5. The ADR text, if accepted (ready to paste into ADR 0011)

> **Amendment (2026-10-xx, AVR-701): select, then launch.** Decision 1 is amended: the host's start moves the party to `setup` for every game. For a game without a pregame, the setup has no Play/Watch choice (`setup.kind = select`): the host's Start seats the members who are here in join order up to the game's maximum, as the direct start did, and the round starts then. A select setup idle for 10 minutes returns the party home. Everything else in decisions 1–4 is unchanged.

## 6. Exit criteria (AVR-701)

| Criterion | Section |
|---|---|
| The ADR is amended or the proposal rejected | 5, 7 |
| If accepted, Core and Party Home support selection without launch | 2, 3 (behind `select_then_launch`) |
| No Play/Watch choice for those games | 2 |
| Host authority and the one-activity rule unchanged | 2 |
| A paired Games review | 3 |

## 7. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | Keep a direct start for the host (a long-press or "Start now" on the tile)? | no; yes | **no** at first: one rule is easier to learn; revisit after a real night |
| D2 | Voluntary Ready (AVR-700) in the same change? | yes; later | **yes**, as a count that never gates |
| D3 | Idle select setup returns home after | 10 min; never | **10 min** |
| D4 | Merge dark behind `select_then_launch`, default off? | yes; switch at once | **yes**, then turn it on after the Games drivers are updated |
