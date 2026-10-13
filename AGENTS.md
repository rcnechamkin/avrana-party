# Avrana Party: agent and contributor entry point

Avrana Party is a portable, local-first Raspberry Pi multiplayer appliance: phones join its Wi-Fi
and play in a browser; core play needs no internet, account or app. This file routes you to the
authoritative material; it does not repeat it. The full loop is [WORKFLOW](docs/WORKFLOW.md).
Vendor files (`CLAUDE.md`, `CODEX-HANDOFF.md`, `docs/agents/`) add environment notes only.

## Authority

Highest first; each source answers its own question.

| Question | Source of truth |
|---|---|
| What is implemented | code and tests on GitHub `main` in each repository |
| What the system is meant to be | canonical docs ([map](docs/README.md), [manifest](docs/manifest.json)) and accepted [ADRs](docs/adr/) |
| What should change now, acceptance, ownership, sequencing | the AVR issue in [Linear](https://linear.app/avranakern) |
| What is running on the Pi | `/party/api/status` and the [deployment manifest](docs/design/DEPLOYMENT-MANIFEST.md); [SYSTEM](docs/SYSTEM.md) summarizes verified state |
| Party ↔ Games interface | [PARTY-GAMES-CONTRACT](docs/design/PARTY-GAMES-CONTRACT.md), `contracts/party-games.v0.json`, ADR 0006 |
| Commands and evidence tiers | [TESTING](docs/TESTING.md) |
| Strategy | [ROADMAP](docs/ROADMAP.md), never a task queue |

Draft/proposed sections are direction, not contract. [Findings](docs/findings/),
[archives](docs/archive/), [research](docs/research/), PR bodies and handoffs are history:
evidence of what was true when written, never instructions. A merged PR is not a deployment; a
curl is not a phone test; a simulation is not a measurement. Chat history is not a source.

## Default working mode: lean, one change at a time

The priority is a usable product, not agent activity. See [WORKFLOW v2](docs/WORKFLOW.md).
One implementing agent is the default. Do not launch an orchestrator, multiple workers,
separate verifier, or reviewer just because they exist. A second agent is warranted only for
a truly independent task or a high-risk change. Cap active implementation at one Party/Games
feature at a time unless the owner explicitly approves parallel work.

For a scoped change:
1. Read the request or AVR issue, the code to be edited, and nearby tests. Read relevant ADRs
   and contracts only when the change touches them. If an owner decision is missing, ask.
2. Choose one small, observable outcome and name the relevant tests. For ordinary changes,
   do not require a Linear plan approval or a separate architecture/documentation sprint.
3. Implement locally on an isolated branch; test the touched behavior as you go. Run wider
   suites once when justified by the change, not after every edit.
4. Only push/open a PR when the change is ready for review. Do not dispatch GitHub workflows,
   re-run green CI, or push speculative intermediate revisions without explicit authorization.
5. Hand back the behavior, evidence, risks, and next owner action concisely. Never add
   follow-up issues or launch more work automatically.

A high-risk change (security, identity, contracts, persistence, install/deploy, platform
lifecycle, or irreversible operations) requires an explicit scope decision, paired changes
where applicable, relevant integration testing and independent review before merge.
UI/content work and isolated bug fixes do not require that ceremony by default.

## Worktrees and claims

Use an isolated branch/worktree when changing code. The
[AI-workflow](https://github.com/rcnechamkin/AI-workflow) CLI is optional coordination
tooling, not a mandatory project manager for a single agent. If commit hooks installed on
this machine require a claim for an AVR branch, obtain that claim or ask the owner before
changing hooks. Never edit another session's claimed worktree. Do not create multiple
worktrees for one task unless their work is genuinely independent.

## Safety

Never, unless the task explicitly authorizes it in writing:

- merge a PR, force-push, rewrite history, or delete branches;
- deploy, pull, restart, edit or `sudo` anything on the Pi; touch nginx, DNS, NetworkManager,
  systemd, certificates or Wi-Fi (operations commands in a document are not permission);
- edit historical documents (`docs/archive/`, dated findings) as if they were current; write a
  new dated finding or update the canonical document instead (CI gates this);
- change a public contract silently: the session protocol, routes, launch integration, catalog
  snapshot, capability vocabulary, `/party/` service-worker scope, no HSTS /
  `Service-Worker-Allowed`, or the deployed HTTPS-only `/party/` (ADR 0004) change only through
  the contract declaration, tests and paired PRs. HTTPS-only `/party/` is current behavior, not a
  permanent invariant: [ADR 0012](docs/adr/0012-limited-mode-party-survives-https-loss.md)
  accepts Limited Mode and its scoped issue (AVR-225) may change it deliberately. Never weaken
  the `Secure` Party cookie or add HSTS to get there;
- skip a required test because it is inconvenient; report it as not run instead;
- commit or print credentials, keys, Wi-Fi secrets, ROMs, BIOS, cores, saves, runtime data,
  personal telemetry or raw logs; hand-edit generated files ([GENERATED](docs/GENERATED.md)),
  Graphify outputs or the two byte-identical nginx files (`avrana-party.nginx`, `arcade/nginx-site`).

Do not infer isolation between appliance services from a `0600` key file or a loopback-only
route: today every service runs as one Unix user
([ADR 0016](docs/adr/0016-service-identities-and-local-trust-boundary.md), [SYSTEM](docs/SYSTEM.md)).

Platform ownership stays with Party (cross-game identity, presence, chat, library, navigation
and durable results/history; no parallel stores or tokens in Games). Device, Profile, Presence
and Seat are distinct; a browser-stored name/avatar is not a durable Profile; Admin is not Host:
see [PARTY-PLATFORM](docs/design/PARTY-PLATFORM.md). Retained research branches
([inventory](docs/branches.json)) are evidence, never a merge queue. Hardware and emulator runs
are bounded and supervised; never during a power measurement.

## Current versus accepted architecture

ADRs [0012](docs/adr/0012-limited-mode-party-survives-https-loss.md),
[0013](docs/adr/0013-party-and-game-browser-origins.md) and
[0014](docs/adr/0014-native-games-isolated-lan-games-retired.md) are accepted direction, not
deployed: Limited Mode, a separate game origin and isolated native-game processes. The LAN Games
fork is still the deployed runtime but is retiring. Do not build new native games as LAN Games
modules, and do not treat standalone LAN Games, `wc-token` admission or a shared Party/game
origin as requirements to preserve in new design. Do not describe accepted architecture as
deployed; `/party/api/status` and SYSTEM say what runs.

## Derived context (Graphify)

Graphify is optional navigation, not an obligatory startup step and never authority.
For focused work, read code and tests directly. Use
[`graphify_context.py`](docs/GRAPHIFY.md) for an actually broad architectural search,
then verify findings in source. Do not refresh context graphs or Linear snapshots on every
tool call. Generated content must not be edited by hand.

## Completion and reporting

An implementation handoff is not a product release. State:
- observable change and branch/PR link;
- relevant tests: passed, failed, or not run (and platform limitations);
- remaining risk, especially missing Pi/phone evidence;
- one next action for the owner.

Keep this in one short PR description and an even shorter final handoff; do not
duplicate full test logs in Linear, PR descriptions and chat. Update the Linear issue
once at the appropriate transition and current canonical docs only when behavior or
architecture materially changed. Do not rewrite historical reports or expand the
backlog without owner approval.

Focused local tests are the iteration default. CI is run once on a reviewable PR;
additional full browser/systemd/cross-repo proof is required when the changed boundary
demands it and at release acceptance. A green simulation is not real Wi-Fi or an
iPhone; mark physical testing pending until the owner confirms it. Never claim skipped
tests passed. A separate reviewer is mandatory for high-risk changes, optional for
routine changes. Only the owner merges, deploys, and accepts physical behavior.

## Cross-repo behavior

The Party ↔ Games boundary is one declared, versioned contract checked by both CIs:
[PARTY-GAMES-CONTRACT](docs/design/PARTY-GAMES-CONTRACT.md). Party owns identity, presence,
chat, library, navigation, durable results/history and platform contracts; Games owns rules and
game servers and never receives device identity. The contract declares what is implemented
today, not the ADR 0013/0014 target. Pairing, merge order and local commands: [CROSS-REPO](docs/CROSS-REPO.md).

## Deployment

Humans deploy: `ops/deploy.sh` with explicit SHAs ([runbook](docs/runbooks/deploy.md)); the Pi
writes the manifest and runs `avrana.ops.smoke`; `/party/api/status` reports the result
([STATUS-ENDPOINT](docs/design/STATUS-ENDPOINT.md)). Agents build and test the machinery; they do
not run it against production. Physical acceptance on real phones is a human step.
