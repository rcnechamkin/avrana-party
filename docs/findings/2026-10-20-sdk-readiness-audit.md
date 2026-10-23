# Game kit and `.avrgame` readiness: can an outside developer get from nothing to an installed game?

Observed 2026-10-20 (Sprint 03 closure, Phase 4). Read-only audit. Party `main` `c903346`, Games
`main` `4acc5ae`. Method: a fresh agent given only the two repositories and no prompt history walked
the nine steps below and ran every command it found documented; its key claims were then spot-checked
by hand (marked ✓). Windows 11 only; nothing on a Pi, phone or Linux host.

The kit is **experimental** (`experimental.1`, Games `docs/DEVELOPING-A-GAME.md:3`). This is a
readiness assessment for the clean-room sprint proposed in
[2026-10-20-sdk-clean-room-validation](../design/proposals/2026-10-20-sdk-clean-room-validation.md),
not a release review.

## 1. The nine steps

| # | Step | Result | Evidence |
|---|---|---|---|
| 1 | Discover the SDK | **Fails.** Nothing a newcomer reads first points at it. | Games `README.md`, `AGENTS.md`, `ADDING_A_GAME.md`, `CONTRIBUTING.md`: 0 mentions of `gamekit`, `DEVELOPING-A-GAME` or `.avrgame` ✓. `ADDING_A_GAME.md` leads to the legacy LAN Games path (AVR-228 retired it as the runtime). |
| 2 | Understand the Party/Game boundary | Partial. The rules exist but are spread out. | ADR 0011, ADR 0013, Games `docs/PARTY-SESSION-PROTOCOL.md`, Party `GAME-UX-CONTRACT`; the kit docs link none of the latter two. No single "the Party owns / a game may never" page. |
| 3 | Scaffold | **Works.** | `python -m avrana_gamekit new sparkle <dir> --title …`, then `check`, `comply --quick` (8/8 groups, 137 checks), the Node runtime, `play --script`, `comply --boot`, `export`. |
| 4 | Session and lifecycle | Works for the protocol; the page lifecycle (hidden, frozen, back-forward cache, reconnect after sleep) is not in conformance. | `avrana_gamekit/conformance.py`; `docs/PARTY-SESSION-PROTOCOL.md:160-162` still says conformance does not run a Node game, which it now does (stale). |
| 5 | Use the Party System Interface | **Not available to SDK games.** On `main` nothing mounts the Party layer for a kit game. Games #88 vendors it for BLUFF and EXPO only, and its docs say kit games wait for owner approval. | Party `docs/design/proposals/2026-10-16-control-center.md:133` says "`comply --boot` checks the button is visible and tappable": not built ✓. |
| 6 | Package and validate | Works, with friction. The packer and validator are Party's, exported by `tools/build_avrgame_tools.py`, which needs a clean Party checkout. It now builds `experimental.3` (`TOOLS_REVISION = 3`, line 72 ✓); the Games guide names `experimental.2` (`DEVELOPING-A-GAME.md:19`) ✓. | |
| 7 | Install through the supported workflow | **No rehearsal path.** Install is owner-only, root, on the appliance; `install --dry-run` fails off the Pi. A developer cannot rehearse the real install without an appliance. | AVR-304, AVR-336 |
| 8 | Test without modifying Party Core | Works with the stand-in (`devparty`). A real-Party harness exists only for Hello Party (`tests/test_hello_party_cross_repo.py`, 3 passed with `AVRANA_PARTY_REPO`); nothing generic a new game can point at. | |
| 9 | Diagnose failures | Works well (`comply` names the failing check and the doc). Two gaps: a game whose vendored `core/party_protocol.py` was edited still passes `comply` and the validator (no digest check against Party's copy outside the Games repo's own contract tests ✓); `comply` passes with the Party validator reported "NOT RUN", and placeholder publisher metadata packs. | |

Also stale: the kit `README.md:91-94` says Party Core has no timeout for a running session; Party
`avrana/party/core.py:74` has `TABLE_ABANDON` (5 min, AVR-475) ✓. `bestguess/docs/ADAPTATION-METHOD-DELTA.md`
refers to an adaptation blueprint from a creative-studio handoff that is not in either repository ✓.

## 2. Gaps, prioritised

**Blockers** for a clean-room adaptation (an outside developer cannot finish without help):

1. **Discovery.** Point the Games `README.md`, `AGENTS.md`, `CONTRIBUTING.md` and `ADDING_A_GAME.md` at `DEVELOPING-A-GAME.md`; mark the legacy path as donor/reference only. *Games, docs only.*
2. **The Party layer for kit games.** Either an owner decision that kit games opt in to the vendored mount (#88 mechanism, `<html data-avrana-party-layer>`), with a scaffold flag and a conformance check, or a written statement that SDK games have no Party button yet. Correct the control-center proposal line 133 either way. *Owner decision first (D3 accepted "coverable" for first-party games only).*
3. **Install rehearsal.** A documented, non-root way to run the real install path against a throwaway Party data directory (or a stated "install is appliance-only; validate is the last developer step"). *Party; design needed.*

**Should fix before the sprint** (it can work around them, but every one costs a reviewer's time):

4. Party tools: name the right version in the guide, or have the guide read it from the export; say a clean checkout is needed.
5. Vendored-file drift: `comply` checks `core/party_protocol.py`, `core/party_result.py` and `web/avrana-party-bridge.js` against the digests in the kit's own declaration; a version policy (AVR-72).
6. A generic real-Party harness (`AVRANA_PARTY_REPO` + any game directory), generalising `test_hello_party_cross_repo.py`.
7. One "the Party owns / a game may never" page, linked from the guide, with the stale timer text (kit README 91-94) and `PARTY-SESSION-PROTOCOL.md:160-162` corrected.
8. `comply` should fail, not pass, when the Party validator was not run (or label the result "partial"); reject placeholder publisher metadata at pack time.

**Optional:**

9. Page-lifecycle cases (hidden, frozen, bfcache, sleep and return) in conformance.
10. Commit the adaptation blueprint `ADAPTATION-METHOD-DELTA.md` refers to, or remove the reference.

## 3. Linear

Existing issues these fall under: AVR-421 (public SDK boundary, items 2, 7), AVR-72 (versioning, item 5),
AVR-37 (`.avrgame` spec, items 4, 8), AVR-59 (developer workflow, Done; items 1, 3, 6 are follow-ups),
AVR-512 (independent Tanks reproduction; the sprint proposal coordinates with it).
