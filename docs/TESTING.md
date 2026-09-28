# Testing: every suite, where it lives, how to run it

Status: inventory from 2026-09-24 (counts are from that day's runs). Commands run from the repo
root of the branch named; "Pi" means `ssh party` (only for suites that need Linux or the appliance).
Claude Code Cloud can run offline tests after `npm ci` and `npx playwright install` where needed;
the offline checks on `main` also run in GitHub Actions (see "Offline CI lane" below).
The `tests/` browser suite targets the live Pi and requires Party Wi-Fi and local name resolution;
do not run `npm test` in Cloud and treat its failure as a product regression.
**Never run heavy suites on the Pi during a power measurement** — each SSH session is a CPU burst
(`docs/findings/2026-09-24-new-psu-power-baseline.md`).

## This repository (`rcnechamkin/avrana-party`)

| Suite | Branch | Command | Where | Needs | Result 2026-09-24 |
|---|---|---|---|---|---|
| Live appliance E2E (captive probe, hub, arcade, streaming, stats, 2 players) | `main` | `npm test` (fast), `npm run test:all` | laptop **joined to the Avrana Party Wi-Fi** | the live Pi; a hosts-file line `10.42.0.1 party.avrana` (Windows: `C:\Windows\System32\drivers\etc\hosts`, edited as administrator) | not run today (would take the laptop off the home network) |
| Soak / fault harness (`@heavy`) | `main` | `npm run soak`, `npm run fault` | laptop on the Party Wi-Fi | live Pi; owner go-ahead for load | not run |
| Soak metric maths | `main` | `npx playwright test tests/soak-metrics.spec.ts` | laptop, Cloud, **CI** | — (no browser binaries) | 10 pass (5 × 2 projects; Cloud 2026-09-26) |
| Arcade AP-address detection | `fix/arcade-ap-address` | `python3 -m unittest discover -s tests/unit -k ApAddresses` (also in the full unit run and **CI**) | laptop, Pi, CI | — (GStreamer/aiohttp stubbed) | 4 pass (2026-09-27) |
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

## Offline CI lane and what Cloud can run (`main`, TESTED 2026-09-26)

`.github/workflows/offline-checks.yml` ("Offline checks") runs on every pull request, on pushes to
`main`, and on demand. It pins Node **22.22.2** (npm 10.9.7), the versions of the validated Cloud
run, and executes exactly these commands, which also pass in a Claude Code Cloud checkout:

```sh
npm ci
npx playwright test tests/soak-metrics.spec.ts
cmp avrana-party.nginx arcade/nginx-site
```

`soak-metrics.spec.ts` uses no `page`/`browser` fixture, so no `npx playwright install` is needed;
the `cmp` step is the repository half of the CLAUDE.md byte-identity rule (the live-site half needs
the Pi). Under `CI=true` the config retries twice and forbids `test.only`. Evidence:
`docs/findings/2026-09-26-cloud-offline-ci-lane.md`.

Every other spec in `tests/` on `main` targets the live Pi at `http://party.avrana` and **cannot run
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
**Failing/broken** — none observed. Python files on `main` (`arcade/*.py`, `install-*.py`,
`experiments/diplomacy/validate_engine.py`, `arcade/test-receiver.py`) are Pi tools or installers,
not unit tests (GStreamer, evdev, aiohttp, `/srv` ROM paths, nginx/NetworkManager). The pure suites
listed above on experiment branches are candidates for this lane once those branches are merged.

## Test tiers and the foundation suites (branch `claude/dreamy-carson-sja5mq`, TESTED 2026-09-26 in Cloud)

| Tier | Meaning | Runs in |
|---|---|---|
| **1: pure** | no appliance, no network, no browser (or a VM with fake browser globals) | Cloud, CI, laptop |
| **2: simulated Party** | localhost only: a real nginx with the committed site and stand-in upstreams; real Chromium against `avrana/web/devserver.py` on 127.0.0.1 (a secure context, like the real origin) | Cloud, CI, laptop |
| **3: hardware** | the Pi, real phones, the AP, HDMI, the H.264 encoder, power: `tests/*.spec.ts` (live), runbooks | Party Wi-Fi only; never claimed from a lower tier |

| Suite | Tier | Command | Result (Cloud) |
|---|---|---|---|
| Contracts (vocabulary, Game Contract v0, appliance profile, catalog freshness, grants, adapters named in the profile) | 1 | `python3 -m unittest discover -s tests/unit` | all pass (with the suites below: 62) |
| Seat evaluation: 18 shared vectors, fuzzed properties (a weak seat never changes another; unknown ≠ no) | 1 | same | pass |
| Providers: uinput adapter checked against the original `Pad` over random input; RetroArch lifecycle incl. kill on ignored SIGTERM | 1 | same | pass |
| `arcade/stream.py` wiring with GStreamer/aiohttp stubbed: imports without evdev; layout = contract = page; startup/`/stats`/cleanup drive the providers | 1–2 | same | pass |
| Web build, precache completeness, CSP-safe pages, no credentials in URLs, install/kill/rollback script | 1 | same | pass |
| nginx: static rules + a **real nginx** run (HTTP captive/apps unchanged; `/party/` HTTPS-only with headers; origin JSON) | 1 + 2 | same, with `AVRANA_REQUIRE_NGINX=1` (skips without nginx otherwise) | pass (nginx 1.24) |
| Browser modules: probe (fake browsers), evaluation vectors, keep-awake lifecycle, service worker in a VM | 1 | `node --test 'tests/offline/*.test.mjs'` | 41 pass |
| Full Mode page, diagnostics, arcade page states (fake signalling), offline copy with Chromium offline mode | 2 | `npx playwright test -c playwright.offline.config.ts` (Cloud: `PW_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium`) | 42 pass (2 Chromium projects) |
| Catalog is fresh | 1 | `python3 -m avrana.contracts.catalog --check` | clean |

`npm run test:offline` runs the three offline runners in order. `npm run dev` serves the simulated
Party at `http://127.0.0.1:8180/party/`. CI runs everything in this table (see
`.github/workflows/offline-checks.yml`). WebKit is not used offline: Playwright's WebKit on
Linux is not iPhone Safari. Tier 3 for these features is the phone checklist in
`docs/runbooks/party-https.md`.

## The games fork (Avrana Party Games — a separate repository)

Not on GitHub yet: the laptop backup is the bare repo `~/avrana-party-games.git`, the Pi dev clone is
`~/avrana-lab/avrana-party-games` (see `docs/SYSTEM.md`). Never use its `abandoned/classic-diplomacy`
branch.

| Suite | Branch | Command | Result 2026-09-24 |
|---|---|---|---|
| All Python tests (BLUFF 391 of them) | `main` @ 2cf4831 | `.venv/bin/python -m pytest -q tests/` | 1197 pass |
| … plus lifecycle log events | `playtest-readiness` @ 6d795a7 | same | 1198 pass (laptop); BLUFF + lifecycle subset 392 pass on the Pi |
| hubnet reconnect (fake WebSocket, Node) | `playtest-readiness` | `node tests/hubnet_reconnect_test.mjs` | 3/3 (fails on `main`: the bug it pins) |
| Browser playtests (puppeteer-core) | `main` | `node tests/playtest_<game>.mjs` | not run today; there is no BLUFF browser playtest yet |

## What is NOT covered by any automated test (manual only)

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
the real shell with its CSP. Arcade health is simulated. It rejects metadata drift
before starting. Runtime test avatar/media directories stay ignored in the local
games checkout. Tests use synthetic identities; no Pi, WLAN, TV, ROM or emulator.
CI independently checks each repo; private cross-repo checkout credentials are not
introduced. Linux CI supplies nginx/rsync/bash gates unavailable on this Windows host.
