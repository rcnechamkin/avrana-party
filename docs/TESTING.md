# Testing: every suite, where it lives, how to run it

Status: verified 2026-09-24 (counts are from that day's runs). Laptop commands run from the repo
root of the branch named; "Pi" means `ssh party` (only for suites that need Linux or the appliance).
**Never run heavy suites on the Pi during a power measurement** — each SSH session is a CPU burst
(`docs/findings/2026-09-24-new-psu-power-baseline.md`).

## This repository (`rcnechamkin/avrana-party`)

| Suite | Branch | Command | Where | Needs | Result 2026-09-24 |
|---|---|---|---|---|---|
| Live appliance E2E (captive probe, hub, arcade, streaming, stats, 2 players) | `main` | `npm test` (fast), `npm run test:all` | laptop **joined to the Avrana Party Wi-Fi** | the live Pi; a hosts-file line `10.42.0.1 party.avrana` (Windows: `C:\Windows\System32\drivers\etc\hosts`, edited as administrator) | not run today (would take the laptop off the home network) |
| Soak / fault harness (`@heavy`) | `main` | `npm run soak`, `npm run fault` | laptop on the Party Wi-Fi | live Pi; owner go-ahead for load | not run |
| Soak metric maths | `main` | `npx playwright test tests/soak-metrics.spec.ts` | laptop | — | — |
| Arcade AP-address detection | `fix/arcade-ap-interface` | `python arcade/test_ap_addresses.py` | laptop or Pi | — | 3 pass |
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
| Topology check (read-only) | `docs/party-platform` | `tools/avrana-topology-check` | **Pi** | — | see `docs/runbooks/network.md` |
| Radio capacity sampler (read-only) | `docs/party-platform` | `tools/radio-watch SECONDS [INTERVAL] [OUT]` (run detached on the Pi) | **Pi** | phones kept awake (a sleeping iPhone ignores ping) | tried 2026-09-24 (1 station); capacity test not run |

From a worktree without `node_modules`, borrow the main checkout's:
`NODE_PATH=<main checkout>/node_modules <main checkout>/node_modules/.bin/playwright test -c …`.
Delete `test-results/` afterwards.

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
