# Shell assimilation sprint — 2026-09-26

Status: TESTED locally (simulated browsers / portable checks); review branch;
not deployed. Starting main: a671955741bbac2b2ffd04c1929bbe089462a7c3.
Branch: fix/party-shell-assimilation.
PR #3's Capability Engine, Game Contract v0, providers, /party/ and diagnostics
were already merged. Main later moved to 2dd0770 via the separate arcade
fatal-exit PR #4; these source files are untouched by this sprint.

Read [the donor inventory and ownership boundary](../design/LAN-GAMES-ASSIMILATION.md).

## What was built

- One profile compatibility facade over wc-token/name/avatar/pfp; same lg-favorites,
  lg-recent and lg-play-total. Names/characters/photos can be edited from /party/.
  Photo framing reuses /api/avatar; no parallel profile or photo store.
- Party Chat adapter over the existing /chat/ws singleton: hello, rolling history,
  server-echo messages, chat connection count, heartbeat and reconnection. Text chat
  is visible in /party/. Rich legacy chat remains accessible in the old UI.
- 29 individual browser titles normalized into validated Game Contract v0 entries,
  separate appliance grants, and matching live /api/games availability checks.
  Discovery is Avrana-owned; game pages stay legacy.
- Gauntlet II alongside Bomberman Party Edition and Worms Armageddon. PS1 entries
  use authoritative experiment metadata, are not installed, have no launch links,
  and explicitly require device validation. No experimental runtime was copied.
- Focused shell controls: visible name/avatar, profile editor, Party Chat, search,
  group-size filter, favorites and recently opened games. Human capability wording
  and technical diagnostics remain. The service worker still controls /party/ only.

## Validation commands and results

On Windows laptop (Node 22.16, Python 3.12; no Pi/real-phone execution):

| Command | Result |
| --- | --- |
| npm ci | Installed lockfile dependencies; zero reported vulnerabilities |
| node --test tests/offline/*.test.mjs | 54 passed |
| python -m avrana.contracts.catalog --check | Fresh, 33 contracts |
| python -m unittest discover -s tests/unit -p test_contracts.py -q | 22 passed |
| python -m unittest discover -s tests/unit -p test_assimilation.py -v | 5 passed |
| npx playwright test tests/soak-metrics.spec.ts | 10 passed (pure math; no hardware) |
| AVRANA_PYTHON=python npx playwright test -c playwright.offline.config.ts | 54 passed, two Chromium phone sizes |
| python -m unittest discover -s tests/unit -q | 67 run: 58 passed, 4 skipped, 3 failures and 2 errors in existing Linux-specific checks |
| git diff --check | Passed |
| SHA256 comparison of avrana-party.nginx and arcade/nginx-site | Identical; neither changed |

The local Python exceptions are Windows symlink privilege (2), Linux installer/bash
checks (2) and a Linux path assertion (1). Real nginx checks (4) skip without nginx.
Linux GitHub Actions is the required final CI lane; read the PR checks for its result.
The first browser run also had a stale diagnostics three-game assertion (updated to
the expanded catalog) and a trace artifact collision from two Playwright runs sharing
an output directory. The final run was sequential and all 54 tests passed.

## Device validation after a separately approved deployment

No production source/config, networking, certificates, services or donor files changed.
No physical phone, Pi streaming, emulation, TV or controller test was performed.

Test /party/ on Party Wi-Fi with real Android and iPhone Safari: shared profile across
legacy game visits, photo orientation/framing/removal, same Party Chat channel with
legacy clients, reconnect/background behavior, favorites/history persistence, direct
game joins and existing arcade/diagnostics. Confirm expected HTTP onboarding and
trusted HTTPS are still intact. PS1 catalog visibility is not PS1 execution evidence.

HTTP and HTTPS identities cannot be migrated automatically across browser origins.
The donor is a separate runtime dependency; API failure disables those launch buttons.
Unknown newly installed donor titles need a reviewed metadata/grant refresh. Template
HIGH CARD is hidden. BLUFF is in the separate development fork and remains uninstalled.
The registry's coarse contract import does not prove per-title spectator, late-join,
private-hand or motion requirements; review those per game as deeper adapters land.
Chat count is not a roster; session authority and rich chat extraction remain future work.

Next migration: update the separate games fork so legacy global navigation returns to
Avrana, consumes the shared profile facade and retires duplicate hub UI; then extract
session-scoped chat/presence with compatible transport.
