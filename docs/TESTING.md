# Testing: every suite, where it lives, how to run it

Guide reconciled 2026-10-01. Commands run from the repo root of the named branch/checkouts.
Results are dated evidence per row; rows without an explicit date in the legacy/experiment
inventory retain the 2026-09-24 snapshot. Counts are not a fresh run of current main.
“Pi” means the appliance; Linux-only offline gates can run in Linux CI without the Pi.

Keep three kinds of evidence separate: automated/source verification (Tier 1–2), deployed
server-side verification (exact releases in [SYSTEM](SYSTEM.md) and dated findings), and real
phone/human acceptance (Tier 3). AVR-51 was deployed 2026-09-29; ADR 0011 is merged source,
with deployment and phone proof pending AVR-212. A deployment curl check is not phone proof.
Claude Code Cloud can run offline tests after `npm ci` and `npx playwright install` where needed;
the offline checks on `main` also run in GitHub Actions (see "Offline CI lane" below).
The `tests/` browser suite targets the live Pi and requires Party Wi-Fi and local name resolution;
do not run `npm test` in Cloud and treat its failure as a product regression.
**Never run heavy suites on the Pi during a power measurement** — each SSH session is a CPU burst
(`docs/findings/2026-09-24-new-psu-power-baseline.md`).

## Workflow, contract and operations checks (AVR-230)

All Tier 1–2: no Pi, no phones. Linux CI is authoritative; rows note what Windows skips.

| Check | Command | Runs in CI as | Notes |
|---|---|---|---|
| Deployment manifest, status document, smoke checks | `python3 -m unittest discover -s tests/unit -p "test_ops_*.py"` | offline lane (full unit run) | fake probes and a scripted HTTP client; the local smoke subset runs against the dev server with a real Party Core |
| `ops/deploy.sh` | `python3 -m unittest discover -s tests/unit -p test_deploy_script.py` | offline lane | arguments and dry runs everywhere; the real path (exact-commit checkouts, selective restarts through a recording `systemctl`, manifest, rollback, failed smoke) is **Linux only** and skipped on Windows |
| Party side of the contract declaration | `python3 tools/contract_check.py` and `-p test_contract.py` | offline lane | mutation tests name the drifted component |
| Both declarations and the real services | `python3 tools/contract_check.py --games ../avrana-party-games`; Games: `AVRANA_PARTY_REPO=../avrana-party python -m pytest -q tests/test_party_session_cross_repo.py tests/test_avrana_contract.py` | `Cross-repo contract` (Party), `cross-repo` job (Games) | the other repository at the paired `avr-N` branch, else `main` ([CROSS-REPO](CROSS-REPO.md)); may not skip in CI |
| Documentation metadata and the historical-edit gate | `-p test_repo_check.py`, `-p test_repo_check_metadata.py`; `python3 tools/repo-check.py --changed-since <base>` | offline lane (gate on PRs only) | see [REPOSITORY-GOVERNANCE](REPOSITORY-GOVERNANCE.md) |
| Drift reconciliation logic | `-p test_reconcile.py`; `python3 tools/reconcile.py --no-network` | `Drift reconciliation` (weekly, manual) | the workflow never fails on drift; Linear checks need `LINEAR_API_KEY`, deployed-version checks need `--status-url` on the Party LAN, and both are reported as not run otherwise |
| Service boundary contract and host checker (ADR 0016) | `python3 -m unittest discover -s tests/unit -p test_ops_boundary.py`; `python3 -m avrana.ops.boundary --facts tests/fixtures/boundary/pi-2026-10-03.json` | offline lane (full unit run) | pure evaluation of recorded facts on any platform; collecting facts from a host is read-only, needs Linux with systemd, and on the Pi is an owner step |
| Clean-target rebuild (AVR-32) | `python3 -m unittest discover -s tests/unit -p test_ops_rebuild.py`; `python3 -m avrana.ops.rebuild check`; `python3 -m avrana.ops.rebuild plan --root <empty directory>` | offline lane (full unit run) | the inventory against the units, installers, network scripts and runbook; the procedure rehearsed on a **simulated** host (plan changes nothing, a second apply changes nothing, secrets are handoffs never created or read, restore). The commands a real run executes are recorded, never run: this is Tier 1 evidence about the procedure, not about a device ([runbook](runbooks/rebuild.md), section 4) |
| Service trust boundary proof (ADR 0016) | `sudo AVRANA_TRUST_PROOF=1 bash experiments/service-trust/proof.sh` | `Service trust proof` (when `avrana/`, `contracts/`, `deploy/`, `experiments/`, `ops/provision-game`, `ops/prepare-native-games` or the appliance fixtures change; manual dispatch) | Linux + systemd + root; transient units on a disposable machine, **never the Pi**. Tier 2 evidence about systemd, not about the appliance; cannot run on Windows |
| Native-game provisioning (ADR 0016 sections 3 to 5 and 8; AVR-236) | `python3 -m unittest discover -s tests/unit -p test_provision_game.py` (also `-p test_standin_game.py`, `-p test_native_game_units.py`); the real path: `sudo AVRANA_NATIVE_GAME_PROOF=1 bash experiments/native-game/proof.sh` | offline lane (unit tests); `Service trust proof`, job `native-game` (same triggers as above; manual dispatch) | the unit tests run `provision-game` on a scratch directory with a recorded `systemctl` and the stand-in game over a real Party Core; the proof job runs it as root on a disposable runner: the real units, socket activation, `LoadCredential=`, a full session, rotate and remove refused during a session, the boundary checker. **Never the Pi.** Tier 2 evidence about systemd, not about the appliance or a product game; the POSIX-only unit tests (descriptors, symbolic links) are skipped on Windows |
| Preparing an appliance for native games (ADR 0016 section 9 phase 2; AVR-304) | `python3 -m unittest discover -s tests/unit -p test_prepare_native_games.py`; the real path: `sudo AVRANA_PREPARE_PROOF=1 bash experiments/native-game/prepare-proof.sh` | offline lane (unit tests); `Service trust proof`, job `prepare-native-games` (same triggers as above; manual dispatch) | the unit tests run `ops/prepare-native-games` on a scratch root with a recording stand-in for `systemctl`: apply, a second run that changes and restarts nothing, a dry run, the reverse, and the refusals (no phase 1 identities, a session running, a native game provisioned), with every byte of `party-core.json` but the one member shown unchanged. The proof job runs it as root on a disposable runner, from a phase 1 host whose Party Core unit has no `ExecReload=` and no socket unit: the real units, the socket handed to Party Core, `provision-game` of the stand-in with a full session, the refusals, and the reverse back to the earlier state. **Never the Pi.** Tier 2 evidence about systemd, not about the appliance; the POSIX-only unit tests (modes, symbolic links, the wrapper process) are skipped on Windows |
| Native Checkers on a real host (ADR 0016; AVR-238) | `sudo AVRANA_CHECKERS_PROOF=1 AVRANA_GAMES_REPO=<avrana-party-games checkout> bash experiments/native-game/checkers-proof.sh` | `Service trust proof`, job `checkers` (the same Party-side triggers as above and manual dispatch; Games is checked out at the paired branch as in `cross-repo.yml`, and a Games-only change does not start it) | on a disposable runner as root: `ops/prepare-native-games`, then the real `provision-game checkers` against `contracts/appliances/avrana-pi4.json`, Party Core launching the socket-activated `avrana-game@checkers` (DynamicUser, `LoadCredential=`), a game played to its natural end by two phones through Party Core's public API and the game's Unix socket (private controls, strangers refused, reconnect, signed result accepted), a Host-ended session, `boundary --phase 2` with Checkers provisioned, and `--remove`. **Never the Pi.** Tier 2 evidence about systemd on Ubuntu, not about the appliance, nginx, TLS or real phones |
| Agent tooling | `-p test_claude_gate.py`, `-p test_avr_context.py` | offline lane | convenience only; nothing is enforced by a hook |
| Multi-client Party browser tests | `npm run test:party-browser` (Windows: `AVRANA_PYTHON=python`) | offline lane | three browser contexts as phones against `devserver --party` (a real Party Core, stub game pages): host and followers, start/end for everyone, switching, reload keeps identity and seat, stale and unauthorized actions, Play/Watch setup, host departure; plus the diagnostics build report. Chromium at phone size is not a phone: iPhone Safari and Android stay Tier 3 |
| Shell accessibility (UX/UI redesign PR 1.4) | part of `npm run test:offline-browser` (`tests/offline/a11y.spec.ts`) and `npm run test:party-browser` (`tests/party/a11y.spec.ts`) | offline lane | contrast, edges, names and reading order on every shell page, Library sheet and empty state and every Party state, each also drawn with more contrast and less motion asked for; headings, targets and sideways scroll on every Party screen; a Tab walk with a ring at every stop over the four places, a game's page and every Party state (not the Library's sheets and empty states). The helpers (`tests/lib/a11y.ts`) are first run against planted faults. Chromium: no screen reader, no Safari, no phone setting (AVR-295) |
| Rollback rehearsal (UX/UI redesign PR 1.4) | `npm run test:rollback` (Windows: `AVRANA_PYTHON=python`; `AVRANA_ROLLBACK_FROM=<git ref>` names the release to go back to, default `origin/main`) | none: run by hand before a release | needs that ref in the local repository, which CI's shallow checkout does not have. Two real builds, a `current` link flipped under a running dev server; proves nothing about the install script, nginx, the Pi or a real phone's cache |
| Owner-supplied game covers (AVR-306) | `-p test_web_covers.py`, `-p test_web_build.py`; `tests/offline/covers.spec.ts` in `npm run test:offline-browser`; `tests/party/covers.spec.ts` in `npm run test:party-browser` | offline lane | what may pass from the covers folder into a release (names, real picture types, size, never a link), the installer taking covers only from the named folder, and the shell showing a cover, falling back when one does not load, trying it again once the Party box answers after a break, and unchanged with none; that Git holds no cover. The installer tests need bash and symlinks (Linux CI). No real box art is in the repository: the fixtures are two flat squares |

`python3 -m avrana.web.devserver --party` is also the local way to try Party mode by hand.
It serves the covers in `web/party/covers/` (or `--covers DIR`); with `--test-controls` it serves
none unless `--covers` names a folder, so a developer's own covers never change a test.
With `--test-controls` it also answers `POST /__test__/party/reset` and
`POST /__test__/party/advance?s=N`, which moves the simulated Party's clock forward N seconds
(0 to 3600) so that "away after 45 s" and "hosting passes after 30 s more" can be tested without
waiting. It moves only a party that a reset made (409 otherwise). Neither route exists without
the flag, and neither exists on the appliance.

## AVR-130 source coverage (PR #35 merged during AVR-213)

AVR-130 offline coverage: `python -m unittest discover -s tests/unit -p test_arcade_stream.py`
tests Party ticket admission, stable slots, reverse-order reconnect, 60-second reservation
grace and expiry, immediate controller release, duplicate binding, stale/malformed/wrong-audience/expired
tickets, spectator refusal, and standalone first-free allocation with fake media. Managed
runtime tests cover session end/switch; the arcade route checks current ownership before input.
`npx playwright test -c playwright.offline.config.ts tests/offline/arcade.spec.ts` checks fresh
authenticated ticket POSTs before sockets, hello-only credentials, refusal, controller release, and the
existing reconnect UI. Real phones, emulator and encoder remain acceptance checks in
`docs/runbooks/arcade-party-provider.md`; no real-device acceptance is claimed.

The arcade controller-release button is lower-level seat cleanup, not Leave Party.
Published deployment evidence has not advanced to this source; physical acceptance is pending.

## This repository (`rcnechamkin/avrana-party`)

| Suite | Branch | Command | Where | Needs | Recorded result (date in row; otherwise 2026-09-24) |
|---|---|---|---|---|---|
| Live appliance E2E (captive probe, hub, arcade, streaming, stats, 2 players) | `main` | `npm test` (fast), `npm run test:all` | laptop **joined to the Avrana Party Wi-Fi** | the live Pi; a hosts-file line `10.42.0.1 party.avrana` (Windows: `C:\Windows\System32\drivers\etc\hosts`, edited as administrator) | not run today (would take the laptop off the home network) |
| Soak / fault harness (`@heavy`) | `main` | `npm run soak`, `npm run fault` | laptop on the Party Wi-Fi | live Pi; owner go-ahead for load | not run |
| Soak metric maths | `main` | `npx playwright test tests/soak-metrics.spec.ts` | laptop, Cloud, **CI** | — (no browser binaries) | 10 pass (5 × 2 projects; Cloud 2026-09-26) |
| Arcade AP-address detection | `main` | `python3 -m unittest discover -s tests/unit -k ApAddresses` (also in the full unit run and **CI**) | laptop, Pi, CI | — (GStreamer/aiohttp stubbed) | 4 pass (2026-09-27) |
| PS1 title profiles | `experiment/ps1-title-profiles` | `python ps1/tests/test_profiles.py` | laptop, Pi | — | 11 pass |
| PS1 hello handshake (+ capture size, viewports) / Leave / slot logic / party-mode seats / latency instrumentation | `experiment/ps1-title-profiles` | `python ps1/tests/test_hello.py`, `test_leave.py`, `test_slots.py`, `test_seats.py`, `test_latency.py` | laptop, Pi | — (aiohttp/GStreamer stubbed) | 10, 4, 5, 4 pass; slots OK |
| PS1 phone page layout (no control over the picture, on screen, targets, states, #diag only on request) | `experiment/ps1-title-profiles` | `npx playwright test -c ps1/tests/playwright.config.ts` | laptop | Playwright browsers | 26 pass (Chromium + WebKit × iPhone 13/SE × portrait/landscape) |
| PS1 latency (real run) | `experiment/ps1-title-profiles` | `AVRANA_PS1_MEASURE=1` on the stream (or on `front.py`), then `python3 ps1/tools/latency-report.py <runtime/latency/*.jsonl>` | **Pi** + phones | a phone (the laptop's firewall drops the kernel ping) | wired baseline 2026-09-24: E p99 32 ms; real phone pending |
| PS1 supervised stream run (power guard, clean exit) | `experiment/ps1-title-profiles` | `ps1/tools/supervised-run.sh <title> <seconds> [stream args]`; phones from the laptop: `node ps1/tools/phones.mjs http://10.0.0.142:8198/ --players 4 --watchers 1 --control FILE` (stream bound to 10.0.0.142 too) | **Pi** + laptop | ROM/BIOS/core on the Pi | 7 runs `VERDICT clean` (2026-09-24) |
| PS1 PID guard | `experiment/ps1-title-profiles` | `python3 ps1/tests/test_pid_guard.py` | **Pi (Linux /proc)** | — | pass (skips on Windows) |
| Party lifecycle model + 300-seed fuzz | `experiment/party-sim` (52), `experiment/party-service` (53) | `python experiments/party-model/test_party_model.py` | laptop | — | 52 / 53 pass |
| Personal Viewport geometry | `experiment/party-sim` | `python experiments/viewports/test_viewport_geometry.py` | laptop | — | 16 pass |
| Viewport PoC server | `experiment/party-sim` | `python experiments/viewports/poc/test_poc_server.py` | laptop | — | 8 pass |
| Viewport PoC browser (pixels, seats, reload, orientation, shared WebRTC source) | `experiment/party-sim` | `npx playwright test -c experiments/viewports/poc/playwright.config.ts` | laptop | Playwright browsers | 13 pass + 1 skip (WebRTC on WebKit) |
| Party service + dev front door (+ service games, seat tickets) | `experiment/party-service` | `python experiments/party-service/test_party_service.py` | laptop, **Pi** (pdeathsig paths are Linux-only) | — (a stand-in `stream_ps1.py`) | 32 pass |
| Party Home → PS1 end to end (seats, spectators, return home) | `experiment/party-service` | on the Pi: `front.py --port 8190 --host 10.0.0.142:8190 --ps1 <dev checkout>/ps1 --devices ""`; laptop: `PW_FROM=<main checkout> node experiments/party-service/e2e-ps1-party.mjs http://10.0.0.142:8190` | Pi + laptop | a fresh party (restart `front.py`) | pass ×3 (2026-09-24) |
| Party Home page (first-time path, host game cards, follow/return, no machinery words, friendly refusal, a11y smoke) | `experiment/party-service` | `npx playwright test -c experiments/party-service/playwright.config.ts` | laptop | Playwright browsers | 6 pass (3 × Chromium, WebKit) |
| Manifest v0 validator | `experiment/party-service` | `python experiments/manifests/test_manifest.py` | laptop | — | 10 pass |
| Topology check (read-only) | `main` | `tools/avrana-topology-check` | **Pi** | — | see `docs/runbooks/network.md` |
| Radio capacity sampler (read-only) | `main` | `tools/radio-watch SECONDS [INTERVAL] [OUT]` (run detached on the Pi) | **Pi** | phones kept awake (a sleeping iPhone ignores ping) | tried 2026-09-24 (1 station); capacity test not run |

From any fresh checkout or worktree, run `npm ci` before Playwright commands.
`test-results/` is generated and Git-ignored.

### Native Checkers integration (AVR-238 branch)

`AVRANA_GAMES_REPO` must name the paired Games checkout containing top-level `checkers/`.
On Linux, run `AVRANA_REQUIRE_NATIVE=1 python3 -m unittest discover -s tests/unit -p
test_native_checkers.py -v` with that variable set. The cross-repo CI job requires these tests:
the generic provider launcher inherits a real Unix listening socket into the grant-declared
child, and real Party Core receives signed results over its internal Unix socket. Windows skips
the process tests; metadata checks still run. Missing peer source is a failure in the required lane.

`npx playwright test -c playwright.provider.config.ts tests/provider/native-checkers.spec.ts`
uses the same paired checkout on Linux and two Chromium phone contexts through separate Party
and game host names and the real bridge. It checks legal completion and Party Home's generic
result display, reconnect, private controls, host end and process failure recovery. HTTP test
origins and inherited descriptors prove browser/process integration only: this harness does
not prove TLS, production cookies, systemd identities/credentials/hardening, nginx, the Pi or
real Safari/Android phones. Checkers-specific real-systemd provisioning and phase-2 boundary
proof is the `checkers` job of `Service trust proof` above (disposable runner, not the Pi); the stand-in proof is not Checkers evidence.

Result projection privacy is pinned by `test_party_result.py` (observer/departed refusal,
allowlisted detached summaries, missing/refused/abandoned result exclusion and next-session
replacement) and `party-bridge.test.mjs` (no summary crosses the bridge). Executed results belong
in the PR implementation report; the presence of these tests is not a passing verdict.

## Offline CI lane and what Cloud can run (current main)

`.github/workflows/offline-checks.yml` (“Offline checks”) runs on PRs, main pushes and demand.
It pins Node 22.22.2. Its current offline commands are:

```sh
npm ci
npm run check:repo
npx playwright test tests/soak-metrics.spec.ts
cmp avrana-party.nginx arcade/nginx-site
AVRANA_REQUIRE_NGINX=1 AVRANA_REQUIRE_LOGROTATE=1 python3 -m unittest discover -s tests/unit -v
node --test 'tests/offline/*.test.mjs'
python3 tools/contract_check.py
npx playwright install --with-deps chromium
npx playwright test -c playwright.offline.config.ts
```

`npm run check:repo` enforces the [governance manifest](manifest.json), local documentation links,
archive/authority boundaries and existing UI/catalog freshness checks. See
[checker scope](REPOSITORY-GOVERNANCE.md). On Windows it selects `python`; existing Python npm
scripts use `python3`, so use `python -m unittest discover -s tests/unit` directly if necessary.
For offline browsers on such Windows hosts, set `$env:AVRANA_PYTHON = 'python'` before running
`npm run test:offline-browser`. UI/catalog checks can also be run individually with
`npm run check:ui` and `python3 -m avrana.contracts.catalog --check`.

CI installs nginx and logrotate for the Linux gates. Local runs may skip those gates if their
binaries are unavailable; Windows also cannot exercise Linux process/symlink paths. The metrics
spec needs no browser fixture/binary. The `cmp` is source byte-identity, not a check of live nginx.
The original lane's dated results remain in `findings/2026-09-26-cloud-offline-ci-lane.md`.

Every other top-level spec in `tests/` on `main` targets the live Pi at `http://party.avrana` and **cannot run
in Cloud or CI**. None is known to be broken; in Cloud they fail before reaching any product code.

| Spec | Hardware / real-device dependency | Why Cloud fails today |
|---|---|---|
| `smoke.spec.ts` | Pi serving the LAN Games hub; OS resolver mapping `party.avrana` → `10.42.0.1` on the Party Wi-Fi | `getaddrinfo ENOTFOUND party.avrana` |
| `captive.spec.ts` | Pi nginx captive-probe handling on the AP | `ENOTFOUND party.avrana` |
| `stats.spec.ts` | running arcade service: emulator + one shared hardware encoder | `ENOTFOUND party.avrana` |
| `arcade.spec.ts` | arcade page served by the Pi | `ENOTFOUND`; also Playwright 1.63 browsers not installed |
| `streaming.spec.ts`, `multiplayer.spec.ts` | Pi WebRTC stream (emulator, H.264 encoder), live player slots | same as `arcade.spec.ts` |
| `soak.spec.ts`, `fault.spec.ts` (`@heavy`) | live load on the Pi; owner go-ahead | same; never run from Cloud |

Classification: **hardware/live-appliance-dependent** — all of the rows above.
**Cloud-environment-incompatible** (on top of that) — `party.avrana` does not resolve outside the
Party Wi-Fi, and the Cloud image's pre-installed Chromium (revision 1194) does not match Playwright
1.63 (`chromium_headless_shell-1243`, WebKit); `npx playwright install` fixes only the latter.
**Failure interpretation:** a resolver/browser dependency failure outside the Party network
is not a product regression. Pi tools/installers in `arcade/` and `install-*.py` are not the
pure unit runner; `tests/unit/` contains the offline suites on main. Experimental suites remain
branch-specific; do not mistake their historical results for current release verification.

## Test tiers and source suites (main; recorded results dated per row)

| Tier | Meaning | Runs in |
|---|---|---|
| **1: pure** | no appliance, no network, no browser (or a VM with fake browser globals) | Cloud, CI, laptop |
| **2: simulated Party** | localhost only: a real nginx with the committed site and stand-in upstreams; real Chromium against `avrana/web/devserver.py` on 127.0.0.1 (a secure context, like the real origin) | Cloud, CI, laptop |
| **3: hardware** | the Pi, real phones, the AP, HDMI, the H.264 encoder, power: `tests/*.spec.ts` (live), runbooks | Party Wi-Fi only; never claimed from a lower tier |

| Suite | Tier | Command | Recorded automated result (initial foundation rows: Cloud 2026-09-26) |
|---|---|---|---|
| Contracts (vocabulary, Game Contract v0, appliance profile, catalog freshness, grants, adapters named in the profile) | 1 | `python3 -m unittest discover -s tests/unit` | all pass (with the suites below: 62) |
| Seat evaluation: 18 shared vectors, fuzzed properties (a weak seat never changes another; unknown ≠ no) | 1 | same | pass |
| Providers: uinput adapter checked against the original `Pad` over random input; RetroArch lifecycle incl. kill on ignored SIGTERM | 1 | same | pass |
| `arcade/stream.py` wiring with GStreamer/aiohttp stubbed: imports without evdev; layout = contract = page; startup/`/stats`/cleanup drive the providers | 1–2 | same | pass |
| Web build, precache completeness, CSP-safe pages, no credentials in URLs, install/kill/rollback script | 1 | same | pass |
| nginx: static rules + a **real nginx** run (HTTP captive/apps unchanged; `/party/` HTTPS-only with headers; origin JSON) | 1 + 2 | same, with `AVRANA_REQUIRE_NGINX=1` (skips without nginx otherwise) | pass (nginx 1.24) |
| Browser modules: probe (fake browsers), evaluation vectors, keep-awake lifecycle, service worker in a VM | 1 | `node --test 'tests/offline/*.test.mjs'` | 41 pass |
| Full Mode page, diagnostics, arcade page states (fake signalling), offline copy with Chromium offline mode | 2 | `npx playwright test -c playwright.offline.config.ts` (Cloud: `PW_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium`) | 42 pass (2 Chromium projects) |
| Party Core v0 (`avrana.party`): guarded join/resume API (automatically called by profile-backed pages in ADR 0011 source), server-issued device cookie, presence as liveness (a player in the game stays `playing`), host grace/succession, versioned host actions, one session launching→active→ending→ended, stale reports refused, 150-seed fuzz; HTTP guards (Host, Origin, JSON, size), no token in bodies/logs, long poll | 1 | same (`test_party_core`, `test_party_service`) | 47 pass (laptop + Linux + CI, 2026-09-27; PR #12) |
| Console model (ADR 0011): one `location` (home/setup/game/results) moved only by the host (host-only Party Home from results, Play again as a new setup, End home, a direct game), the same for every phone; avatars are bundled Gaze ids only; `destination()` for every page and location (Party Home, the round's game, other party games, standalone titles; host and follower alike; no profile or an old Party Core moves nobody); the follower's routing on load and on every move, automatic presence with a profile, the host API; games: held Party results, host-only end, onboarding facts pinned to the rules | 1 | `test_party_core` `ConsoleLocation`; `node --test tests/offline/party-mode.test.mjs tests/offline/party-follow.test.mjs`; games `tests/test_bluff_party_pregame.py`, `tests/test_bluff_briefing.py` | pass (laptop, 2026-09-29) |
| Party pregame (AVR-129, ADR 0010): a pregame game opens in `setup` (a committed move, nothing at the game); members choose Play or Watch; host-only start with `if_version`; refused while anyone here has not chosen or outside min/max; away members never block, a member joining during setup must choose; choices become the roster roles (players first); `round_on` during a round, late arrivals watch; `setup` tickets for the named game; host End or switch from setup never reaches the game; a failed launch after setup sends everyone home; fuzz with choices/starts; every session-protocol flow test again through setup (`PregameFlow`); `setupPanel()`, arrival/tiles during setup, `choose`/`startRound` (stale retried once, `unresolved` never) | 1 | same (`test_party_core` `Pregame`, `test_party_service` `PregameHttp`, `test_party_session_flow` `PregameFlow`) + `node --test tests/offline/party-mode.test.mjs` | 169 party unit tests and 80 module tests pass (laptop, 2026-09-29) |
| Arcade as a Party-launched provider (AVR-134, ADR 0009): launch starts / end stops the runtime under one lock; forged, replayed, expired or misaddressed messages change nothing; a failed or slow start is stopped again; a launch over a lost end stops the old run first; an end during a start waits for it; stale ends (idle: ok; while a newer run: 409); an unconfirmed stop; abandon reports once and never hangs; loopback/unproxied/size/JSON guard; configure needs key + loopback party URL; cross-component: real Party Core + HTTP link + reference BLUFF + managed arcade over HTTP, one timeline, BLUFF and the arcade never both running across switches, start failure, a start slower than the link (rolled back), restart recovery, abandon to lobby; `stream.py` idle → launch → end → relaunch and the fatal `abandoned` report; Party Core's failed-launch rollback `end`, per-game link timeouts; deploy drop-in/config agreement, nginx never names :8098 | 1 | same (`test_party_managed`, `test_arcade_stream` `ManagedArcade`, `test_party_service`, `test_party_session_flow` `LinkTimeouts`, `test_party_core_deploy`) | 139 party tests pass, 5 runs in a row; arcade tests pass except the 3 known Windows-only ones (laptop, 2026-09-29) |
| Party navigation (AVR-128, ADR 0008): `nav` moves only on committed transitions; host-only switch/end with `if_version`; a switch ends the old game's runtime before the next launch (recording provider link: no overlap), stops if the old game does not confirm; concurrent and stale host tabs leave exactly one activity; non-host/stranger refused; low-level removal never moves the party (no normal Leave UI); a ticket naming another game is refused and old tickets die on a switch; fuzz with switches (`nav` never points at another game than the active one); `follow()` and the in-game follower module | 1 | same (`test_party_core` `Navigation`, `test_party_service` `PartyNavigation`/`UnconfirmedSwitch`, `test_party_session_flow`) + `node --test tests/offline/party-mode.test.mjs tests/offline/party-follow.test.mjs` | 118 party unit tests and 76 module tests pass (laptop, 2026-09-29) |
| Party Core deployment package (AVR-51; deployed 2026-09-29, server-side evidence in `findings/2026-09-29-party-core-deploy.md`; tests here verify source/config): config/unit templates agree with the service, contracts and appliance grants; the committed site carries `deploy/party-core/nginx-party-api.location` verbatim, HTTPS only; key script makes a 0600 key the protocol reads, never prints it, refuses overwrite. `test_nginx_site` Tier 2 runs real nginx with the real party service behind `/party/api/` (state, join POST cookie flags, Origin refusal, long poll, `/internal/` never reaches the party) | 1–2 | same (`test_party_core_deploy`, `test_nginx_site`; Tier 2 and the key script need Linux, CI requires nginx) | Tier 1 on Windows; Tier 2 + key script: CI |
| Log and telemetry bounds (AVR-30): the telemetry logrotate rule covers exactly the sampler's file (never hand-made evidence) and the installer installs it; journald caps are explicit; `docs/runbooks/logs-and-retention.md` names every source; the arcade's client-stats log rotates and keeps the newest record; real logrotate rotates past 10 MB and the sampler's `>>` appends again | 1–2 | same (`test_log_bounds`, `test_arcade_stream` ClientStatsLog; real logrotate needs Linux, CI requires it) | Tier 1 on Windows (2026-09-29); real logrotate: CI |
| Party session protocol v0 (`avrana.party.protocol`, ADR 0006): shared vectors, ticket audience/session/expiry/tamper/type confusion, stable game token, replay, `GameSide`; end to end over HTTP with a reference game: launch roster, ticket admit + reconnect = same identity, spectator, server-to-server completed/abandoned, browser-forged/stale/replayed reports refused, end for everyone | 1–2 | same (`test_party_protocol`, `test_party_session_flow`) | 32 pass (laptop + Linux + CI, 2026-09-27; PR #13) |
| Catalog is fresh | 1 | `python3 -m avrana.contracts.catalog --check` | clean |
| Generated UI assets are fresh (`web/party/styles.css` from `web/src/party.css`, `web/party/lib/icons.js` from Lucide; `docs/UI-DESIGN-SYSTEM.md`) | 1 | `npm run check:ui` | clean (laptop, 2026-09-27) |

`npm run test:offline` runs the three offline runners in order. `npm run dev` serves the simulated
Party at `http://127.0.0.1:8180/party/`. Party CI runs this repository’s offline runners
(see `.github/workflows/offline-checks.yml`); Games-side tests run in Games CI, and the
combined provider harness is separate explicit-checkout verification. WebKit is not used offline: Playwright's WebKit on
Linux is not iPhone Safari. Tier 3 for these features is the phone checklist in
`docs/runbooks/party-https.md`.

## The games fork (Avrana Party Games — a separate repository)

Private GitHub `rcnechamkin/avrana-party-games` is canonical, with independent CI. Use an explicit
local checkout for cross-repository tests (see below), not production paths. Games PR #13 is
merged source for ADR 0011; verified deployment remains `c6d7b52` in SYSTEM. Never use its
`abandoned/classic-diplomacy` branch. The following table is historical 2026-09-24 evidence,
including failures against then-main; it is not a current-main failure report.

| Suite | Branch | Command | Result 2026-09-24 |
|---|---|---|---|
| All Python tests (BLUFF 391 of them) | `main` @ 2cf4831 | `.venv/bin/python -m pytest -q tests/` | 1197 pass |
| … plus lifecycle log events | `playtest-readiness` @ 6d795a7 | same | 1198 pass (laptop); BLUFF + lifecycle subset 392 pass on the Pi |
| hubnet reconnect (fake WebSocket, Node) | `playtest-readiness` | `node tests/hubnet_reconnect_test.mjs` | 3/3 (fails on `main`: the bug it pins) |
| Browser playtests (puppeteer-core) | `main` | `node tests/playtest_<game>.mjs` | not run today; there is no BLUFF browser playtest yet |

## What is NOT covered by any automated test (manual only)

Live-appliance Playwright can verify browser/server behavior against a deployed Pi, but does
not establish human interaction on actual iPhone/Android hardware. Record release hashes,
network path and real devices separately before claiming phone acceptance.

Real iPhone Safari and Android Chrome behaviour (captive probes offline, `party.local`, sleep/wake,
WebRTC on iOS), real Wi-Fi with several phones (the AP's client ceiling), H.264 on the Pi's encoder,
input-to-photon latency, and power under load. The runbooks in `docs/runbooks/` are the manual tests.

## LAN Games provider cross-repository tests

Private source: rcnechamkin/avrana-party-games. Use two explicit local checkouts,
never a live donor or production path. In games:

```
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
python ops/export_avrana_catalog.py --check provider/catalog.json
python ops/export_avrana_catalog.py --check ../avrana-party/contracts/catalogs/lan-games.json
node --test tests/avrana_worker.test.mjs
bash ops/check_static.sh
bash ops/test_release_safety.sh
```

In Avrana (npm ci and Chromium installed as above):

```
AVRANA_GAMES_REPO=../avrana-party-games AVRANA_PROVIDER_PYTHON=../avrana-party-games/.venv/bin/python npx playwright test -c playwright.provider.config.ts
```

Windows uses .venv/Scripts/python.exe and PowerShell $env:NAME assignments. The
harness binds 127.0.0.1:8182, imports actual donor routes/chat/game sockets and serves
the real shell with its CSP. A second instance on 127.0.0.1:8183 (`--party-session`,
`tests/provider/party_harness.py`) also runs the real Party service behind `/party/api/`
(the games server gets a throwaway BLUFF key and the Party's loopback URL).

Current source coverage:

- `party-session.spec.ts`: protocol join/resume, launch, tickets and End with real BLUFF;
  reload and lost/timed-out ticket requests keep identity/hand. Forged/stale tickets, legacy
  tokens and strangers cannot take another seat or see private state.
- `party-home.spec.ts`: profile-backed automatic presence, host-only direct launch and End,
  authoritative follow on reload/reopen, blocked follower browsing, stale start, switch ordering,
  failure rollback and no-Core/standalone compatibility. Host succession uses the lower-level
  removal API in a test; it does not imply a Leave UI.
- `party-pregame.spec.ts`: `?pregame=1` exercises the ADR 0011 full-screen setup on **Party Home**,
  How to play before first Play, Play/Watch choices, host-only Start and refusal reasons,
  player-only private hands versus the Party spectator view, role lock, late arrival/reconnect,
  host End and held results with host Play again/Party Home. Party round BLUFF has no independent
  ready/start or automatic results-to-lobby timer.

These are localhost Chromium tests with phone-size viewports, not real iPhone/Android runs.
Recorded pre-ADR-0011 provider counts (31 passed/19 skipped, 2026-09-29 AVR-129) are historical;
consult the current run rather than treating those totals as current console acceptance.
The [phone runbook](runbooks/bluff-party-reconnect.md) includes older release-specific checks;
apply ADR 0011 acceptance via AVR-212 once that release is deployed. Arcade health is simulated;
AVR-130 reservation source merged in PR #35; physical acceptance remains pending. The harness rejects metadata drift, uses
synthetic identities and keeps generated avatar/media data ignored in the local Games checkout.
No Pi, WLAN, TV, ROM or emulator is used.

CI independently checks each repo; private cross-repo checkout credentials are not
introduced. Linux CI supplies nginx/rsync/bash gates unavailable on this Windows host.
