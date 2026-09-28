# LAN Games providerization and direct launch

Status: TESTED locally on review branches; not deployed or merged.
Bases: platform 459d4cd19c3a638f6d9fce54eaea675ba0f8890e,
games 2cf4831064de709feeb31865c5022a3f048e49ef.
Branches: fix/lan-games-providerization and fix/avrana-provider-integration.
Architecture/audit: docs/design/LAN-GAMES-PROVIDER.md and ADR 0005.

Baseline read-only evidence: owner-merged PR #5 CI succeeded (run 36226221830).
Pi clean source/installed /party/ release both 459d4cd; trusted TLS fetches (no -k)
returned version/catalog/origin, shell HTTP200 and active nginx/games/arcade.
No Pi changes. Physical phone acceptance did not block development.

## Implemented

Authoritative deterministic public registry export (30 titles); 29 installed LAN
paths remain grants. BLUFF uses existing ID, remains uninstalled. Arcade and two
experimental PS1 entries remain unchanged. No experiment branches imported.
Version-gated direct /games/<slug>/?avrana=1 launch, explicit donor bootstrap,
one normal-flow Back to Party, declared profile/global/viewport boundaries,
shared identity and canonical aliases in existing library lists. Standalone legacy
access remains compatible. One existing chat history/transport; games open no
duplicate global chat. Updated root worker preserves /party/ scope/cache ownership.

## Commands and evidence

Platform:

```
python -m avrana.contracts.catalog --check
python -m unittest tests.unit.test_assimilation tests.unit.test_contracts -v
python -m unittest discover -s tests/unit -v
node --test tests/offline/*.test.mjs
npx playwright test tests/soak-metrics.spec.ts
AVRANA_PYTHON=python npx playwright test -c playwright.offline.config.ts
AVRANA_GAMES_REPO=../avrana-party-games AVRANA_PROVIDER_PYTHON=../avrana-party-games/.venv/bin/python npx playwright test -c playwright.provider.config.ts
```

PowerShell uses $env assignments and .venv/Scripts/python.exe. Linux defaults
python3. Windows: modules 56 pass, contracts+assimilation27 pass, soak10 pass,
combined browser12 pass (all30 pages at two sizes; real donor sockets), catalog and
nginx byte hashes pass. Full Windows unit suite: 61 pass, 5 fail, 2 error, 4 skip
of72; Linux paths/bash/symlinks/arcade subprocess and nginx need Linux CI.
Final offline Chromium: 56 passed. Current Linux CI results are recorded below when complete. The final combined suite adds a TV link/QR context test and passes 12/12.

Games:

```
.venv/Scripts/python -m pytest -q
python ops/export_avrana_catalog.py --check provider/catalog.json
python ops/export_avrana_catalog.py --check ../avrana-party/contracts/catalogs/lan-games.json
node --test tests/avrana_worker.test.mjs
python tests/test_no_private_data.py
bash ops/check_static.sh
bash ops/test_release_safety.sh
```

Python1200 pass; worker3 pass; drift/privacy/static syntax pass. Local release-safety
could not run because rsync is absent; Linux CI must supply that gate.
A new alias-removal regression fails against origin/main's actual profile.js,
which leaves avrana:lan-chess behind after removing the raw-slug favorite.
Current implementation collapses/removes both. No synthetic played telemetry.

Initial browser assertion failures were fixed to select behavioral targets:
existing game-specific class, hidden join link, duplicate legacy hub tiles and
legacy aria-label vs aria-pressed. Windows socket shutdown errors during navigation
are harness noise, not browser page errors or live service changes.

## Hardware acceptance after owner-approved deployment

1. Pi: install reviewed donor release first and separately built shell. Verify
   known /api/games marker, all grants, unchanged HTTPS/captive HTTP/DNS/services,
   clean logs and supported rollback. Preserve ignored avatar/media/venue data.
2. iPhone on Party Wi-Fi: trusted https://party.avrana.net/party/, edit name/avatar/
   photo, launch CHESS directly, ready/play, return/reload; repeat WORDCLASH,
   a private-hand game (SPADES/POKER), a real-time game (TANKS/DODGEBALL), and a
   TV-required title only with its expected display. Check room/navigation does
   not clip controls, keyboard, safe area, scrolling or fullscreen behavior.
3. Android Chrome: same identity/launch/return and game-control checks.
4. Two phones: distinct profiles/seats; weaker capability report on one must not
   downgrade the other. Chat from Party, play, return to same conversation.
5. Favorite/remove/reopen: no duplicate legacy/canonical IDs; recent means opened.
   Profile edits survive game refresh and return; photos use same existing store.
6. Previously-used browser: standalone root worker upgrade, then integrated launch;
   Party cache/offline scope remains /party/, no old hub return/chat/profile chrome.
7. Bare legacy deep links remain usable standalone. Marked refresh returns directly
   to /party/ without browser history. Unsupported donor shows update needed.
8. PS1 remains experimental/uninstalled; this sprint validates no execution,
   streaming, latency, TV/Personal Viewport hardware or Wi-Fi recovery claims.

## Next / deferred

Next migration: extract/harden shared transport behind an Avrana service interface,
then define authoritative session/roster independently of chat connections. Do not
promote Party Home here. Scoped chat, deeper legacy deletion, PS1 runtime promotion,
TV/Personal Viewport and native Companion execution remain later sprints.
Private combined CI still needs a read-access/artifact mechanism; no new secrets.

## Review and Linux CI

- Donor PR: https://github.com/rcnechamkin/avrana-party-games/pull/1 (first).
- Platform PR: https://github.com/rcnechamkin/avrana-party/pull/7 (second).
- Donor run 36261284527 SUCCESS: Python1200 (84.68s), privacy/drift/static,
  worker3 and release-safety passed.
- Platform run 36261333271 SUCCESS: Python72 including real nginx and Linux
  process/symlink gates, modules56, offline browser56, soak10, catalog/byte identity.
- Final review added unknown future-ID preservation to the standalone adapter;
  focused cross-repo browser checks passed 2/2 after the full12/12 run.
- Closing checkpoint reruns independent PR CI; inspect current PR head checks.
Both review branches remain unmerged; no production files or services changed.

Working-tree final state and final SHAs are available through git status / git
rev-parse HEAD and PR heads. Secrets, browser output, test runtime data, dependencies
and local logs remain ignored. The private games repository retains original main
history with historical branding/paths; no abandoned refs were published.
