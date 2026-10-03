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

## Starting work

<<<<<<< HEAD
Given `Implement AVR-N` (`python tools/avr_context.py AVR-N` gathers the issue, paired
branches, PRs and the deployed build in one read-only pass):
=======
- This repository owns the appliance platform, Party Core, shell, contracts, arcade integration,
  tests and operations tooling. [Games](https://github.com/rcnechamkin/avrana-party-games) is a
  separate repository with independent CI. See [provider ownership](docs/design/LAN-GAMES-PROVIDER.md).
- Fetch GitHub `origin`, inspect status, current main and open PRs, then create an issue-scoped
  `docs/avr-N-*`, `chore/avr-N-*`, `fix/avr-N-*`, `feat/avr-N-*` or `experiment/avr-N-*` branch.
  Use a descriptive scope when no issue exists. Disclose a stacked PR's dependency and base.
  Preserve unrelated changes. Review/test through a PR; never force-push or rewrite history.
- No deployment, production checkout edits/pulls, service restarts, sudo, live nginx/DNS,
  NetworkManager, systemd, certificate or Wi-Fi changes without an explicit owner deployment
  instruction. The Pi is a deployment/test target, never a development workspace. Operations
  commands in a document are not permission to run them. See [deployment index](deploy/README.md).
- Keep `avrana-party.nginx` and `arcade/nginx-site` byte-identical. Live-site equality requires
  separate authorized evidence. Preserve the deployed ADR 0004 behavior — HTTPS-only `/party/`,
  service-worker scope, no HSTS / `Service-Worker-Allowed`, capability vocabulary and
  contract/grant boundary — in unrelated work. HTTPS-only `/party/` is current behavior, not a
  permanent invariant: [ADR 0012](docs/adr/0012-limited-mode-party-survives-https-loss.md)
  accepts Limited Mode, and its scoped Linear issue (AVR-225) may change it deliberately. Never
  weaken the `Secure` Party cookie or add HSTS to get there.
- Preserve platform ownership of cross-game identity, presence, chat, library, navigation and
  durable results/history; do not add parallel stores/tokens in Games. Device, Profile, Presence
  and Seat are distinct; a browser-stored name/avatar is not a durable Profile. Admin is distinct
  from Party Host. See [platform design](docs/design/PARTY-PLATFORM.md).
- ADRs 0012–0014 are accepted direction, not deployed: Limited Mode, a separate game origin and
  isolated native-game processes. The LAN Games fork is still the deployed runtime but is
  retiring; do not build new native games as LAN Games modules or treat standalone LAN Games,
  `wc-token` admission or a shared Party/game origin as requirements to preserve in new design.
- Never commit or print credentials, private keys, Wi-Fi secrets, ROMs, BIOS, emulator cores,
  saves, runtime databases, personal telemetry or raw measurement logs. Inspect diffs and file
  lists for these before every push. Use synthetic test identities and temporary data.
- [Retained research branches](docs/branches.json) are noncanonical evidence, not a merge queue.
  Never wholesale-merge them or resurrect [abandoned Diplomacy](experiments/archive/diplomacy/README.md).
  Hardware/emulator runs must be bounded and supervised; heavy load needs owner authorization.
  Never poll SSH or run parallel work during power measurements.
>>>>>>> origin/main

1. Read the Linear issue. It is the desired delta: Outcome, Acceptance Criteria, Out of Scope,
   Repositories, Tests Required, Dependencies, Open Decisions. If Open Decisions holds an
   unresolved product question, stop and ask; do not guess.
2. Read the current implementation first: the source and tests the issue touches. Then only the
   canonical docs and ADRs those files cite. Use [Graphify](docs/GRAPHIFY.md) for navigation
   when the search is broad; verify everything it returns.
3. Check what is deployed when behavior on the appliance matters: `/party/api/status` (or SYSTEM
   when the Pi is unreachable).
4. Decide whether [Games](https://github.com/rcnechamkin/avrana-party-games) must change
   ([CROSS-REPO](docs/CROSS-REPO.md)); if so, pair branches with the same `avr-N`.
5. Name the tests that will prove the change before editing; add or extend them with the code.
6. Branch from fetched `origin/main` as `type/avr-N-short-description`
   (`feat|fix|chore|docs|experiment`). Keep unrelated changes out; preserve others' work.

## Safety

Never, unless the task explicitly authorizes it in writing:

- merge a PR, force-push, rewrite history, or delete branches;
- deploy, pull, restart, edit or `sudo` anything on the Pi; touch nginx, DNS, NetworkManager,
  systemd, certificates or Wi-Fi (operations commands in a document are not permission);
- edit historical documents (`docs/archive/`, dated findings) as if they were current; write a
  new dated finding or update the canonical document instead (CI gates this);
- change a public contract silently: the session protocol, routes, launch integration, catalog
  snapshot, capability vocabulary, `/party/` service-worker scope or the HTTPS-only boundary
  (ADR 0004) change only through the contract declaration, tests and paired PRs;
- skip a required test because it is inconvenient; report it as not run instead;
- commit or print credentials, keys, Wi-Fi secrets, ROMs, BIOS, cores, saves, runtime data,
  personal telemetry or raw logs; hand-edit generated files ([GENERATED](docs/GENERATED.md)),
  Graphify outputs or the two byte-identical nginx files (`avrana-party.nginx`, `arcade/nginx-site`).

Platform ownership stays with Party (identity, presence, chat, library, navigation; Device,
Profile, Presence and Seat are distinct; Admin is not Host): see
[PARTY-PLATFORM](docs/design/PARTY-PLATFORM.md). Retained research branches
([inventory](docs/branches.json)) are evidence, never a merge queue. Hardware and emulator runs
are bounded and supervised; never during a power measurement.

## Derived context (Graphify)

[Graphify](docs/GRAPHIFY.md) is derived navigation, never a source of truth. Before a broad
search or an architecture question, run `python tools/graphify_context.py ensure --architecture`
and a scoped `python tools/graphify_context.py query "question" --architecture`; then read the
cited source, tests and canonical docs. Its corpus excludes findings, archives and research, so
it returns current architecture by default. Linear owns live work; a generated Linear snapshot
older than six hours is stale. Inferred edges are hypotheses. Never edit generated graphs,
receipts or snapshots. Focused reads, debugging and targeted tests go straight to the source.

## Completion

Done means all of:

- the requested behavior is implemented and nothing out of scope changed;
- behavior tests were added or updated, and the relevant local suites pass
  (`npm run check:repo`, `npm run test:unit`, `npm run test:modules`, `npm run test:offline-browser`;
  `python tools/contract_check.py --games ...` when the boundary moved). Windows may skip or fail
  Linux-only tests: say so; Linux CI is authoritative;
- Linux CI, including `Cross-repo contract`, is expected to pass;
- cross-repo compatibility is handled (paired PR, or an explicit "Games unaffected because ...");
- canonical docs and the manifest are updated when behavior or architecture changed;
- the [implementation report](docs/agents/IMPLEMENTATION-REPORT.md) is in the PR and the final
  message, and the issue is In Review (not Done) while review, CI or phones remain.

## Cross-repo behavior

The Party ↔ Games boundary is one declared, versioned contract checked by both CIs:
[PARTY-GAMES-CONTRACT](docs/design/PARTY-GAMES-CONTRACT.md). Party owns identity, presence,
chat, library, navigation and platform contracts; Games owns rules and game servers and never
receives device identity. Pairing, merge order and local commands: [CROSS-REPO](docs/CROSS-REPO.md).

## Deployment

Humans deploy: `ops/deploy.sh` with explicit SHAs ([runbook](docs/runbooks/deploy.md)); the Pi
writes the manifest and runs `avrana.ops.smoke`; `/party/api/status` reports the result
([STATUS-ENDPOINT](docs/design/STATUS-ENDPOINT.md)). Agents build and test the machinery; they do
not run it against production. Physical acceptance on real phones is a human step.
