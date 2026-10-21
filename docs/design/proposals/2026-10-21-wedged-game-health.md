# A game that listens but no longer answers (AVR-673): recommendation and test plan

- **Status:** recommendation, 2026-10-21 (Sprint 05). Nothing is implemented. Any probe is a Party↔game protocol
  change (ADR 0006, the vendored protocol, Games, both kits, the Arcade runtime) and needs the owner's approval.
- **Reads with:** [session-probe proposal](2026-10-12-session-probe.md) Part B (the signed `state` probe; it already
  recommends deferring the probe, line 93), AVR-33 finding, `tests/unit/test_failure_injection.py` `LostGameCheck`.

## 1. What happens today

| Fact | Where |
|---|---|
| The lost-game check is a bare connect: a refused connection counts, an accepted one is "up" | `avrana/party/sessions.py` `HttpGameLink.reachable` (262-296) |
| It runs only when a page asks for a ticket, not on a timer, so pages already seated never trigger it | `sessions.py:325` → `service.game_up` (`service.py:367`) |
| 3 failures inside 10 s close an active round as `abandoned` / `game_lost` | `core.py:76-77`, `core.py:829-862` |
| The switch is off by default | `avrana/contracts/party_config.py:140` (`close_lost_game: False`) |
| A wedged game is pinned as a known gap: the round stays `active`, and the Host's End still returns within the link bound | `test_failure_injection.py:481-495` |
| A wedged LAN Games loop cannot answer End either (End takes the same asyncio lock); the Arcade does the same | Games `core/net.py:236-258`; `managed.py:105-131` |
| systemd restarts a crashed game (`Restart=on-failure`), with no `WatchdogSec` | Games `deploy/games/avrana-game@.service:41` |

Nobody is stranded: End goes home first and returns within `END_LINK_TIMEOUT` + 3 s (`END_TIMEOUT` 15 s).

## 2. Is automatic termination justified?

**Not while a Host is present.** End is one tap and bounded. Closing a round automatically loses it (no result,
outcome `abandoned`), and a false positive would end a real game in front of the players.

**Only where no one can press End:**
- an unattended table where the Host's phone is asleep or gone;
- a Host role left vacant by Leave. Under the 2026-10-18 owner decision the role stays vacant and the round goes on
  (`core.py:483-488`).

`TABLE_ABANDON` (5 min) does not help in either case: players are present, at a game that does not answer.

## 3. Which failures need an answer from the game

| Failure | Caught today by |
|---|---|
| process dead, socket refused | the connect check (when enabled), systemd |
| hung event loop that still accepts TCP | nothing (needs an application answer) |
| restarted game holding no session (C-08); with socket activation a connect even restarts it | nothing (needs an application answer) |
| Arcade wrapper alive, emulator stuck or stopped | nothing (needs an application answer) |

A systemd watchdog would catch a hung process, but not a live process with no session.

## 4. The smallest compatible contract, if the owner wants one

This is the proposal's `state` probe with a clearer gate. It is not new design.

- **Opt-in.** A game declares `extensions["net.avrana.party"].state = true`. An undeclared game keeps today's
  connect check, so every existing package is unchanged.
- **Route.** `POST {game}/avrana/session/v0/state`, on the same transports as `launch` and `end`.
- **Signing.** The request is a sealed `state` message with the game key and the existing nonce guard. The reply
  is sealed `state_is {sid, holds}`. Signing keeps a LAN stranger from learning session ids. The new message types
  go in a separate module, so the vendored `party_protocol.py` digest does not move.
- **Thresholds.**
  - An authentic `holds: false` takes 2 misses over at least 3 s.
  - Silence takes 3 misses over at least 15 s. That is 10 s today; the change gives a loaded Pi or an SD-card stall
    more room.
  - Any success resets the count.
  - The probe runs at most once every 2 s.
  - A 404 or 405 from a game that declared the probe, or a bad signature, is logged and never counted.
- **Timer.** The probe needs its own timer, because ticket requests alone miss seated pages. Running it only while
  a round is active and the Host is absent or vacant keeps the Pi quiet.

**Applicability**

| Runtime | What to add |
|---|---|
| Python kit | Answer from `GameSide.sid` under the session lock. The kit's server is threaded, so the HTTP thread alone proves nothing. |
| Node kit | The same in `game-app.mjs`. A single thread means any answer proves the loop is alive. |
| LAN Games | A route beside the launch and end routes, answering from `GameBinding`. |
| Arcade | `holds` only when `RUNNING` and the process is alive. It must not wait on the start lock. |

## 5. Recommendation

1. **Now: no protocol change.** Keep `close_lost_game` off. Keep the known-gap test, and record the Host's End as
   the supported recovery.
2. **Phase 1, if approved:** the probe raises a "the game is not answering" flag in Party state, and the Host (or
   anyone, when the Host role is vacant) sees a prompt offering End. No round changes by itself.
3. **Phase 2, only with evidence from phase 1:** auto-close under `close_lost_game`, and only after the Host has
   been absent or vacant for a set time. It stays off by default.

## 6. Test plan

- **Unit (Party).**
  - A declaring game that hangs: the flag is raised (phase 1), or the round ends `abandoned` / `game_lost`
    (phase 2). This flips `test_failure_injection.py:481`.
  - A non-declaring game that hangs stays `active`: today's behaviour.
  - Signature vectors: accepted; wrong key; wrong sid; replayed nonce; expired; malformed; a 404 ignored; a slow
    reply under the threshold; a reply that flaps.
- **Conformance (kit, Python and Node).**
  - `holds` is false before launch, true after, false after End and after the game's own `ended`, and false after a
    restart.
  - The reply is signed, and a stranger's request is refused.
- **Arcade.** The probe during a stuck start, during stopping, and while idle.
- **Cross-repository.** `tests/test_party_session_cross_repo.py` with a real kit game.
- **Physical (owner).** A Pi under load, to confirm the 15 s silence threshold gives no false flag on SD-card stalls.

## 7. Owner decisions

1. Build the probe at all, or keep the Host's End as the only recovery (the proposal's own recommendation).
2. Prompt only, or later auto-close, and under what Host-absence rule.
3. A signed `state` message (recommended), or reuse of the unsigned `/health`. `/health` is not session-aware, and
   it lives on the same loop that hangs.
4. The miss thresholds and the timer.
5. Whether `close_lost_game` may ever be enabled before C-08 is settled (`offline-acceptance.md:170`, NOT RUN).
6. A systemd `WatchdogSec` fallback for hung processes.
