# Claude Code Cloud handoff

## Repository state (audited 2026-09-25)

GitHub `rcnechamkin/avrana-party` is canonical. At the audit start, GitHub `main`,
laptop `main`, and the clean Pi production checkout were all at
`f93f0fcf5c6dc821553996226726a9ec70e31917`. That was a historical synchronization, not an automatic
deployment policy. Confirm the exact SHA with
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

Party HTTPS (`fix/party-https`) was merged to `main` as PR #2 on 2026-09-26 (`d092ffd`). It
provides `https://party.avrana.net/`, served over local Party DNS with a Pi-only Let's Encrypt
DNS-01 certificate. This is the canonical Full Mode origin (ADR 0004 D1). Status, evidence, the
renewal blocker and rollback are in `docs/runbooks/party-https.md`. Automatic renewal is still off,
and the certificate expires 2026-12-25.

The 2026-09-26 foundation sprint (branch `claude/dreamy-carson-sja5mq`, merged as PR #3 at a671955) added:
- platform contracts (`contracts/`, `avrana/`);
- provider adapters, which the arcade now uses;
- the Full Mode web shell (`web/party/`);
- Tier 1–2 offline suites.

It includes PR #1's CI lane. Start from `docs/findings/2026-09-26-architecture-sprint.md` and
ADR 0004.

The Shell Assimilation sprint builds on merged PR #3. Read
`docs/design/LAN-GAMES-ASSIMILATION.md` for the donor inventory, compatibility
keys, metadata provenance and ownership rules. Avrana owns global product
functionality; LAN Games is a temporary game/service provider. Do not add a second
profile or chat store. Source on main is not proof of deployment: the Pi has not
been updated by this sprint. PS1 entries are experimental metadata, not installed
or hardware-validated runtimes.

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
`npx playwright test tests/soak-metrics.spec.ts` and `npm run test:offline`: Python unit tests,
`node --test` and the offline Chromium suite against a simulated Party on 127.0.0.1.

**Browser and nginx setup in Cloud:**
- The image's pre-installed Chromium doesn't match Playwright 1.63, and downloading browsers may
  be blocked. Run the offline browser suite with
  `PW_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium`.
- The real-nginx Tier 2 test runs when `nginx` is installed (`apt-get install nginx`; it is used
  only as a test binary, never started as a service) and skips otherwise. CI sets
  `AVRANA_REQUIRE_NGINX=1`. See
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
is a separate private GitHub repo with independent CI; combined browser tests
require both explicit checkouts as documented below.

**First Cloud task (done 2026-09-26, the lane above):** on a new branch, add a
small, safe offline CI lane for existing pure tests and document its exact setup.
Keep the live Playwright suite manual and leave production services, network
configuration, and experimental game behavior untouched.

## Browser provider continuation (2026-09-26)

Assimilation PR #5 merged at 459d4cd; read-only inspection confirmed that installed
/party/ release on the Pi before this sprint. Providerization is separate review
work, not deployed. Read docs/design/LAN-GAMES-PROVIDER.md, ADR 0005 and
CODEX-HANDOFF.md before continuing. Private games source is now
rcnechamkin/avrana-party-games (existing main 2cf4831; feature work on a branch).
Review donor first, platform second; platform version-gates integrated launches.
No experimental branch is required or merged. Party Home remains isolated.
The full local cross-repo browser harness and hardware checklist are documented in
docs/findings/2026-09-26-lan-providerization.md. Do not claim Cloud validates phones.
