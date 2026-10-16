# Friend-ready acceptance matrix and GO / NO-GO (2026-10-15)

Dated evidence. Nothing was deployed, restarted, installed or changed on the Pi to produce it. The only
appliance contact was one read-only `GET /party/api/status` and `GET /party/api/state` over the
management address (2026-10-16T03:57Z); no SSH, no phone, no Wi-Fi. Linear: AVR-510, AVR-10, AVR-12,
AVR-27, AVR-511, AVR-76, AVR-139, AVR-301, AVR-475, AVR-476.

## Evidence levels

| Level | Meaning | Closes a physical gate? |
|---|---|---|
| **T1** | Unit tests, in process | No |
| **T2** | Real Party service + real Games server + real WebSockets (or real Chromium) on one machine | No |
| **T3** | Read-only observation of the deployed Pi | No |
| **T4** | Real phones on the Pi's Wi-Fi, WAN disconnected | Yes (owner/humans only) |

## Revisions

| Item | Value |
|---|---|
| Deployed Party (Pi, status read 2026-10-16T03:57Z) | `b3e993ca9b56`, deployed 2026-10-15T01:56Z, smoke passed, `summary: ok` |
| Deployed Games | `bd7e01df2699` (an ancestor of Games `main`) |
| Party `main` tested | `79b99f75c2fa` (77 commits ahead of the deployed Party) |
| Games `main` tested | `e83d98e` (36 commits ahead of the deployed Games) |
| Test host | Windows 11, Python 3.12.3, Games requirements pinned (`fastapi 0.139.2`, `uvicorn 0.51.0`, `websockets 16.1`) |
| Not in the deployed Party | PR #149 (AVR-475 abandoned table) and PR #150 (AVR-476 Host's way out). Both are on `main` only |
| Pi, as read | certificate `ok`, 87.8 days left; services active; no session, 0 members; arcade idle; nginx site matches |

`main` Party with the **deployed** Games passes `tools/contract_check.py` and the journey below, so the
smallest change set for the next physical run is **Party `main` alone; Games stays at `bd7e01d`**.

## Matrix

PASS / FAIL / BLOCKED / NOT TESTED. A PASS at T1/T2 never reads as a T4 PASS.

| # | Journey step | T1/T2 (source) | Pi as deployed | Real phones (T4) |
|---|---|---|---|---|
| 1 | Offline cold boot, no upstream DNS (AVR-10) | NOT TESTED (needs hardware) | NOT TESTED. Last Pi reboot was online ([baseline](2026-10-12-deployed-baseline.md)) | NOT TESTED |
| 2 | First-time Wi-Fi join and browser onboarding (AVR-76) | T2 PASS for the shell and captive pages (offline suites) | NOT TESTED | NOT TESTED |
| 3 | Four phones join one Party (AVR-12) | **PASS** J1 (4 sockets, 4 seats, private hands) | NOT TESTED | NOT TESTED |
| 4 | Host launches BLUFF, game completes (AVR-27) | **PASS** J1 (59 moves, result accepted, results screen) | NOT TESTED | NOT TESTED |
| 5a | Phone drops and returns to its seat and hand | **PASS** J2 | NOT TESTED | NOT TESTED |
| 5b | Host's phone vanishes mid-round | **PASS** J3 (round continues; Host role stays, see Findings) | NOT TESTED | NOT TESTED |
| 5c | Host succession after the round | **PASS** J3 | NOT TESTED | NOT TESTED |
| 5d | Every phone vanishes: abandoned table (AVR-475) | **PASS** J4 and unit tests (#149) | **BLOCKED**: not deployed (#149 is after `b3e993c`) | NOT TESTED |
| 5e | Host's way out of a full-screen game (AVR-476) | T2 PASS: `host-escape.spec.ts` (all pass, run twice more in isolation) | **BLOCKED**: not deployed | NOT TESTED |
| 6a | Host ends a live round; old tickets refused; start again | **PASS** J5 | NOT TESTED | NOT TESTED |
| 6b | Play again after completion, fresh hands, no residual room | **PASS** J1 round 2 | NOT TESTED | NOT TESTED |
| 6c | Switch between two different games | T2 browser spec (stub game pages); real second game server NOT TESTED | NOT TESTED | NOT TESTED |
| 7a | Service restart recovery (Party Core, games, arcade) | T1 `test_party_recovery.py` PASS | NOT TESTED (disruptive, owner approval) | NOT TESTED |
| 7b | Reboot recovery, diagnostics survive (journal is volatile, AVR-29) | NOT TESTED | NOT TESTED | NOT TESTED |
| 7c | Useful failure diagnostics | T1 status/smoke tests PASS; live `/party/api/status` reads `ok` | PASS (read) | NOT TESTED |
| 8 | Tanks on iPhone + Android (AVR-511) | NOT TESTED | NOT TESTED (Tanks is registered in `/party/api/state`; not exercised) | NOT TESTED |
| 9 | Cached `.avrgame` relaunch (AVR-139) | NOT TESTED | NOT TESTED; experimental PRs Games #81/#82 unmerged | NOT TESTED |
| 10 | 1 to 4+ client radio capacity (AVR-301) | NOT TESTED; harness (`tools/wifi-lab`, #85) is merged but not run | NOT TESTED | NOT TESTED |

## What was run

| Run | Command | Result |
|---|---|---|
| Python unit suite, Party `79b99f7` | `AVRANA_PYTHON=python python -m unittest discover -s tests/unit` | exit 0, 3 skipped (POSIX-only) |
| Real-service cross-repo tests, Games `e83d98e` | `AVRANA_REQUIRE_PARTY=1 pytest tests/test_party_session_cross_repo.py tests/test_bluff_party_reconnect.py tests/test_bluff_party_pregame.py` | 18 passed |
| Contract, Party `main` vs Games `bd7e01d` and vs `e83d98e` | `python tools/contract_check.py --party . --games <dir>` | compatible, both |
| **Four-player journey (new)**, Party `main` + Games `e83d98e` | `tools/acceptance/four_player_journey.py --games <games>` | **44 PASS, 0 FAIL** |
| Same journey, Party `main` + **deployed** Games `bd7e01d` | same | **43 PASS, 0 FAIL** |
| Party multi-client Chromium suite | `npx playwright test -c playwright.party.config.ts` | 50 passed, 1 failed (5.3 min); the failure reproduces in isolation, see Findings 6 |

Measured (loopback, T2, so *not* Wi-Fi latency; the 62 ms is dominated by the harness's 50 ms read poll):
launch to all four welcomed p50 87 ms, p95 134 ms; action to the next table state p50 62 ms, p95 63 ms
over 217 moves; reconnect to the restored state 63 ms. Full 4-player BLUFF to a winner: 59 moves per
round in the scripted play (income, then coup).

## The new harness

`tools/acceptance/four_player_journey.py` drives the real `PartyService`, its HTTP routes and
launch/end `GameLink`, and the Games repository's real `server.py` over uvicorn, with four real
WebSocket clients using Party-minted tickets (including the Host claim). Party timers run on a
controllable clock. It writes `journey-<stamp>.json` and `.md` (git SHAs, PASS/FAIL per check,
timings) under `test-results/acceptance/` (ignored by git). Scenarios:

- **J1** launch, four welcomes, private hands, play to a winner, structured result accepted, results
  screen, Host sends everyone home, no residual room, play again, second full round.
- **J2** a phone drops, others see the held seat, a fresh ticket restores seat and hand, game completes.
- **J3** the Host's phone vanishes mid-round; the round continues to completion; Host succession after.
- **J4** every phone vanishes; Party abandons after `TABLE_ABANDON`; the game releases its room; the
  next arrival starts a new round.
- **J5** Host ends a live round; every phone is told; the old session's ticket is refused; a new round starts.

Run: `python tools/acceptance/four_player_journey.py --games <Games checkout> [--out DIR] [--only J1,J4]`
with an interpreter that has the Games requirements.

Not covered by it, on purpose: browsers, Wi-Fi, TLS/nginx, systemd, the Pi, a second real game server,
service restarts, reboot.

## Findings

1. **No test defect blocks the protocol journey.** Nothing needed repair in this pass, so there is no
   fix PR. The gaps are deployment and physical evidence, not source defects found here.
2. **The Pi does not run the abandoned-table or Host-escape changes (AVR-475/476).** Until a Party build
   with #149 and #150 is deployed, a round whose phones all die stays `playing` on the appliance, and
   the Host cannot reach the Party's way out of a full-screen game. For a four-human BLUFF night the
   realistic trigger is a dead phone battery; the rest of the table can finish, so this is a recovery
   risk, not a blocker for the happy path.
3. **Host's phone gone mid-round keeps the Host role until the round ends** (J3, by design,
   PARTY-LIFECYCLE). The three others finish BLUFF; nobody can press End meanwhile. Acceptable for
   BLUFF (the game ends itself). It becomes a trap for a game that never ends itself (AVR-475's
   OpenCE case); `TABLE_ABANDON` covers it only when *every* phone is gone. Not changed (lifecycle
   rules are an owner/architecture decision).
4. **The friend-ready runbook's release pair is stale.** `friend-ready-acceptance.md` step 0 pins Party
   `defd4a2` and Games `fb711d9`; the appliance already runs `b3e993c` / `bd7e01d` and `main` is far
   ahead. Use the pair in the owner checklist and update step 0 when the owner picks the SHAs.
5. **Private-repo CI cannot be cited.** Actions do not start (billing; see the 2026-10-12 baseline and
   the owner's 2026-10-15 decision). Every result above is local evidence.
6. **One Chromium spec fails on this machine, every time:** `tests/party/device-requirements.spec.ts:66`
   (AVR-469, experimental). A tap on **Play this round** made right after the briefing appears does not
   register (`aria-pressed` stays `false`); with a 3 s pause before the tap it passes (debug copy,
   removed). So it is a timing race between the briefing showing and its Play/Watch buttons taking
   taps, visible on a slow machine. It is not in the BLUFF journey, and a slow phone could meet the same
   dropped first tap. Not fixed here (UI lane; no evidence yet on a phone). Worth one look when the
   owner has the four phones: tap Play immediately when the briefing opens.

## GO / NO-GO for a four-human offline playtest

**NO-GO today. Conditional GO after three owner actions and one rehearsal.**

Why not yet: no physical evidence exists for offline cold boot, onboarding, four phones, or a complete
game on the Pi (matrix rows 1 to 4 are NOT TESTED at T4). The source and protocol journey is sound,
so the smallest set of changes to make it demonstrable is process, not code:

1. Owner approves deploying Party `main` (`79b99f7` or its successor), Games unchanged at `bd7e01d`,
   with `ops/deploy.sh` and explicit SHAs ([deploy](../runbooks/deploy.md)). This puts #149/#150 on the Pi.
2. Owner runs the checklist ([owner checklist](../runbooks/friend-ready-owner-checklist.md)): cold
   boot with Ethernet unplugged, one phone, then four phones, then BLUFF to the end, a lock-and-return,
   and Play again.
3. Anything red goes to the issue named beside the step; do not retry silently.

Becomes **GO** when checklist rows 1 to 7 are PASS on at least one iPhone and one Android phone.
Rows 8 to 10 are desirable and may be NOT TESTED for a friendly night.
