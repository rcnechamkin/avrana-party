# ADR 0010: The pregame is the Party's (Play or Watch, host start)

**Status: proposed.**
- Implemented and TESTED on a laptop, on branches `feat/avr-129-party-pregame` (this repository) and `feat/avr-129-bluff-pregame` (games).
- Merged (#33, games #12) and **deployed 2026-09-29** with BLUFF's pregame on; verified server-side (`docs/findings/2026-09-29-avr129-deploy.md`). Not yet tried on a phone.
- Date: 2026-09-29. Linear: AVR-129.
- It answers the M3 part of AVR-26 (Party lobby versus game lobby) and extends ADRs 0006–0008.

## Context

On real phones on 2026-09-29, BLUFF could begin as soon as enough players pressed Ready, and **any** ready player could press Start. Launching BLUFF from Party Home opened BLUFF's own ready/countdown lobby: a second lobby after the Party's, where the Party Host had no role. Nothing let someone choose to watch a round instead of playing it. BLUFF's watch view was the TV view, which masks every hand.

AVR-26 asks what a game's lobby should do once the Party has already formed, and says: no generalized lobby framework. AVR-56 asks for a platform-shaped briefing/Ready pattern that games fill with their own content.

## Decision

1. **The Party owns the pregame.** A Party Core game configured with `pregame: true` (and `min_players`, from its contract) does not launch at once. The host's start opens the session in a new state, `setup`:
   - Nothing runs at the game yet, and `nav` moves everyone to the game's page (a committed move, ADR 0008).
   - Every member who is here chooses **Play this round** or **Watch this round** (`POST /party/api/session/choice`). They may change their mind until the start.
   - **Only the Party Host starts the round** (`POST /party/api/session/start`, with `if_version`). Party Core refuses the start until:
     - every member who is here has chosen (`unresolved`);
     - at least `min_players` and at most `max_players` chose Play (`player_count`).

     Away members do not block. A member who joins during setup must choose too.
   - The choices become the roster's roles in the unchanged launch message (ADR 0006): players first, then spectators. Then the launch proceeds as before.
   - During setup, the host can End (everyone goes home) or switch. Nothing ever reached the game, so there is nothing to end there.
2. **Roles change only at the setup boundary.**
   - During a round, a choice is refused (`round_on`: "Roles change between rounds").
   - Members who arrive late, or come back from away, are admitted as spectators (as before).
   - The next time the host picks the game, a fresh setup starts with no choices carried over.
   - The live round's seats never move.
3. **Game pages wait instead of joining alone.**
   - While the round is set up, a game page that names its game gets `409 setup` for a ticket. `hubnet.js` then opens no socket (never a standalone hello), calls `onSetup(true)`, and asks again every 2 s.
   - The host's start arrives as a ticket, and the page joins with its role.
4. **The setup panel is platform UI; the rules are the game's.**
   - `web/party/lib/party-follow.js` shows the Party's setup panel on every game page:
     - who plays, who watches and who is still choosing;
     - Play and Watch, marked `aria-pressed`;
     - Start the round for the host only, disabled with the reason as text.
   - A game may set `window.AvranaPregame.beforePlay()`, which is asked before a member's Play. BLUFF opens its first-play briefing there, so nobody plays without it (AVR-90).
   - Games hear `avrana-party-setup` events.
   - BLUFF shows its own setup screen: the title, "How to play", and who starts. Its `?` rules stay available during play.
5. **A Party round skips the game's own lobby** (games core, reusable).
   - `GameSession.party_start(roster)` seats the launch roster's players at once. The game's `ready`, `start` and `settings` verbs are refused ("The Party Host starts rounds from the Party").
   - The round starts after a 3-2-1 once every seat's phone is here, or after `PARTY_ARRIVAL_SECONDS` (15 s). Missing seats start away, so BLUFF's grace and autopilot apply.
   - Standalone play (no Party session) keeps the game's own lobby unchanged.
6. **Spectators get what the game allows spectators; BLUFF allows everything.**
   - Games core adds `game_state_spectator()`; the default is the public view.
   - `core/net.py` gives a spectator *ticket* its own socket set, and only that set receives `state_for(None, spectator=True)`.
   - BLUFF's spectator view is intentionally omniscient: every seat's cards, plus the exchange draw while one is open.
   - Player sockets get only their own cards, as before. Anonymous watchers get only the public view. Anonymous watchers are a browser token, or a TV the players can see.
   - When the Party session ends, spectator sockets become plain watchers, so the omniscient view never reaches a later room.

## What is reusable, and what is BLUFF's

| Reusable | BLUFF-specific |
|---|---|
| Party Core `setup` state, choices, host-only start, min/max, the `round_on` boundary, `setup` tickets (any Party game with `pregame: true`) | the briefing content and its gate (`beforePlay`) |
| the setup panel in `party-follow.js`; Party Home's setup text and "Go to … setup" | the setup screen's look |
| games core `party_start`, refused lobby verbs, arrival 3-2-1, `game_state_spectator` hook, spectator sockets | the omniscient spectator view (all hands, the exchange draw) |

This is not a lobby framework (AVR-26). Party Core decides who plays; games keep their rules, seating and rendering.

## Consequences

**Where the code and tests are:**
- **Party Core:** `avrana/party/core.py` (`SETUP`, `choose`, `start_round`, `setup_status`, the setup view); `avrana/party/service.py` (the routes, and no game link during setup); `deploy/party-core/party-core.example.json` (BLUFF: `min_players` 2, `pregame` true).
- **Party Core tests:**
  - `tests/unit/test_party_core.py` `Pregame`, and a fuzz with choices and starts: nobody is seated in setup, and never more than the maximum.
  - `tests/unit/test_party_service.py` `PregameHttp`.
  - `tests/unit/test_party_session_flow.py` `PregameFlow`: the whole session-protocol flow again, through setup, plus the chosen roles in the launch roster and tickets.
- **Web:** `web/party/lib/party-mode.js` (`setupPanel`), `party-client.js` (`choose`, `startRound`), `party-follow.js` (the panel), `web/party/app.js`. Tests: `tests/offline/party-mode.test.mjs`.
- **Games:** `core/session.py`, `core/net.py`, `games/bluff/game.py`, `web/hubnet.js`, `games/bluff/web/client.js`. Tests:
  - `tests/test_bluff_party_pregame.py`: seating, refused verbs, a missing phone, spectator/player/TV privacy;
  - updated party-session tests;
  - `tests/hubnet_party_ticket_test.mjs` (setup wait).
- **E2E:** `tests/provider/party-pregame.spec.ts`, with the harness reset `?pregame=1`.

**Deployment order:**
- **Party Core first, config last.** With the new config but old game pages, a page would get `409 setup` and treat it as "no": it would join the standalone room during setup, the pre-AVR-129 behaviour. Deploy the games side (hubnet) before turning `pregame` on in `/etc/avrana-party/party-core.json`.
- **Games first is safe:** it only changes party rounds. They now seat the roster and skip BLUFF's lobby, and an old Party Core's roster still works.

**Limits in v0:**
- **A second device sees every hand.** A player whose second device joined the Party as another member could watch as a spectator and see every hand. Party identity is per device; social rules cover this.
- **No spectator-to-player promotion mid-round, by design.**
- **Not verified on real phones:** the arrival wait (15 s) and the 2 s setup poll are not tuned there.

**Tier 3, still open:**
- setup and start on real phones;
- the briefing gate on a first-time phone;
- a sleeping phone during setup;
- a 4-person round with a spectator.
