# Claude Code Cloud handoff

## Repository state (audited 2026-09-25)

GitHub `rcnechamkin/avrana-party` is canonical. At the audit start, GitHub `main`,
laptop `main`, and the clean Pi production checkout were all at
`f93f0fcf5c6dc821553996226726a9ec70e31917`. The current deployed **source**
commit after this handoff is the GitHub `main` commit; confirm the exact SHA with
`git rev-parse main` locally and `git -C /home/cody/avrana-party rev-parse HEAD`
on the Pi. A source fast-forward does not restart live services.

`main` contains the production arcade and portal source, plus the current roadmap,
system map, runbooks, and design documentation. The live LAN Games server and the
Avrana Party Games fork are separate repositories. The published
`experiment/party-sim`, `experiment/party-service`,
`experiment/ps1-title-profiles`, `ps1-emulation`, and
`fix/arcade-ap-interface` branches preserve work that is not deployed.
`docs/party-platform` preserves its original history, including historical raw measurement evidence;
summaries are on `main`, while logs and JSONL samples stay out of `main`.
The architecture and experience documents are in `docs/` with status notes.
`docs/AVRANA-OPEN-SOURCE-SUBSTRATE.md` is current project research on proposed
reusable subsystems and implementation/reference candidates.

## Start here

Read `CLAUDE.md`, `README.md`, `docs/ROADMAP.md`, `docs/SYSTEM.md`,
`docs/TESTING.md`, and then the relevant `docs/design/` or `docs/runbooks/`
page. `docs/ROADMAP.md` controls sequencing; dated findings record measurements.
Treat proposed capabilities and branch experiments as distinct from what is live.
Before architecture or dependency work, read `docs/AVRANA-OPEN-SOURCE-SUBSTRATE.md`
with `docs/GAME-PLATFORM-ARCHITECTURE.md`,
`docs/OFFLINE-TRUST-AND-RECOVERY.md`,
`docs/PERSONAL-VIEWPORT-AND-EMULATION.md`, and
`docs/REFERENCE-IMPLEMENTATIONS.md`.

## Branch workflow

1. Clone the private GitHub repository and verify `main` is current. Create a
   short-lived branch from `origin/main` for each task; never edit `main` directly.
2. Inspect existing branch work before reimplementing it. Keep experiments on
   their branches until reviewed; use a PR to merge tested changes.
3. Run offline checks in Cloud. Review the diff for generated files, credentials,
   ROMs, BIOS, emulator cores, runtime databases and logs before pushing.
4. Push the branch, review and merge through GitHub. Fast-forward the Pi's clean
   production checkout to the exact merged SHA only after a deploy decision.
   Live config changes and service restarts are separate owner-approved steps.

## Safe testing

`npm ci` installs the lockfile's Playwright dependency. Offline logic checks include
`npx playwright test tests/soak-metrics.spec.ts`; install Playwright browsers
with `npx playwright install` if a browser-only test needs them. See
`docs/TESTING.md` for commands on each experiment branch. Python unit tests on
those branches use standard-library stubs where documented. This repo does not
yet provide one reproducible Linux image or dependency lock for all Pi media
components (RetroArch, GStreamer, system packages).

`npm test`, `npm run soak`, and `npm run fault` target the live appliance via
`party.avrana` on the Party Wi-Fi. Do not use them as Cloud checks. Real iPhone
Safari, captive portal, Wi-Fi capacity, WebRTC hardware encoding, emulator
performance, power, and offline recovery require bounded Pi/phone validation
using `~/avrana-lab/` and the runbooks. Heavy tests require the owner.

## Blockers and first Cloud task

Cloud cannot reach the Party LAN or reproduce the Pi's hardware media stack.
The first offline CI lane (`.github/workflows/offline-checks.yml`, Node 22.22.2)
runs the offline checks on `main`; its exact commands and the classification of
every other test are in `docs/TESTING.md` ("Offline CI lane"). The games fork
is a separate repo and is not yet available through the same GitHub workflow.

**First Cloud task (done 2026-09-26, the lane above):** on a new branch, add a
small, safe offline CI lane for existing pure tests and document its exact setup.
Keep the live Playwright suite manual and leave production services, network
configuration, and experimental game behavior untouched.
