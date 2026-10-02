# Avrana Party: contributor and agent invariants

Avrana Party is a portable, local-first Raspberry Pi multiplayer appliance. Phones join its
Wi-Fi and play in a browser; core play needs no internet, account or installed app.
Start with [README](README.md), [CONTRIBUTING](CONTRIBUTING.md) and the [documentation map](docs/README.md).
This is the single vendor-neutral operational entry point. Agent-specific guides only add
environment details; old handoffs never assign work.

## Authority, by question

| Question | Source of truth |
|---|---|
| Current source, code and tests | GitHub `main` in each repository |
| Priorities, sequencing, blockers, acceptance, ownership, next task | [Linear](https://linear.app/avranakern) |
| Verified deployed revisions and topology | [SYSTEM](docs/SYSTEM.md), supported by dated [findings](docs/findings/) |
| Accepted architectural decisions | [ADRs](docs/adr/), respecting explicit amendments and partial/proposed status |
| Product contracts and detailed design | [Design index](docs/design/README.md); explicit draft sections remain proposals |
| Strategy and milestone outcomes | [ROADMAP](docs/ROADMAP.md), never a task queue |
| Commands, evidence tiers, verification semantics | [TESTING](docs/TESTING.md) |
| Document classification and generated sources | [Manifest](docs/manifest.json) (metadata only) |

If these disagree, resolve by domain and cited evidence; do not silently reinterpret a decision.
A merged PR is not deployment evidence. A server curl check is not real-phone acceptance.
A simulation is not a measurement. A proposal is not a decision. Findings, PR bodies, branch
snapshots, [research](docs/research/) and [archives](docs/archive/) never override current assignments.

## Boundaries and safe workflow

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
  separate authorized evidence. Preserve ADR 0004's HTTPS-only `/party/`, service-worker scope,
  no HSTS / `Service-Worker-Allowed`, capability vocabulary and contract/grant boundary.
- Preserve platform ownership of cross-game identity, presence, chat, library and navigation;
  do not add parallel stores/tokens in Games. Device, Profile, Presence and Seat are distinct;
  Admin is distinct from Party Host. See [platform design](docs/design/PARTY-PLATFORM.md).
- Never commit or print credentials, private keys, Wi-Fi secrets, ROMs, BIOS, emulator cores,
  saves, runtime databases, personal telemetry or raw measurement logs. Inspect diffs and file
  lists for these before every push. Use synthetic test identities and temporary data.
- [Retained research branches](docs/branches.json) are noncanonical evidence, not a merge queue.
  Never wholesale-merge them or resurrect [abandoned Diplomacy](experiments/archive/diplomacy/README.md).
  Hardware/emulator runs must be bounded and supervised; heavy load needs owner authorization.
  Never poll SSH or run parallel work during power measurements.

## Generated files and verification

**Do not hand-edit generated files. Edit their sources and regenerate.**
[The generated-file guide](docs/GENERATED.md) and manifest list exact sources/commands:
`web/party/styles.css`, `lib/icons.js`, `lib/avatars.js`, `avatars/*.svg`, `art/*.svg` and
`catalog.json` are generated; imported catalog/art snapshots originate in Games. Other shell
HTML/JS and `web/src/party.css` are source. Release-stamped output is never source or committed.

After `npm ci`, use `npm run check:repo` (includes existing UI/catalog freshness checks),
`npm run test:unit`, `npm run test:modules`, `npm run test:offline-browser`, and
`npx playwright test tests/soak-metrics.spec.ts`. [TESTING](docs/TESTING.md) covers setup,
Windows Python naming and Linux nginx/logrotate gates; CI is the Linux baseline.
Tier 1 = pure; Tier 2 = localhost simulation; Tier 3 = physical Pi/phones/Party Wi-Fi.
`npm test`, soak and fault target live hardware: never use them as offline checks.
Record exact revision, command, environment, date, skips/failures and evidence tier.

## Graphify: derived navigation only

See [Graphify](docs/GRAPHIFY.md). Before broad repository searching or architecture questions,
run `python tools/graphify_context.py ensure --architecture`, then a scoped
`python tools/graphify_context.py query "question" --architecture` where useful. Verify cited
source files/tests and canonical docs. Focused reads/debugging/tests can go directly to source.
Graphify is derived context only: Linear owns live work/status/priorities; canonical docs/ADRs
own decisions and intended architecture; code/tests own implementation. Inferred edges are
hypotheses. Check semantic freshness separately with `check-semantic`; stale/missing documentation
context means read canonical docs directly or refresh through interactive host-agent Graphify.
CI uses local ASTs and never requires a model API credential. A scoped read-only `LINEAR_API_KEY`
allows `refresh` to generate private work context; use live Linear for decisions and reject expired
snapshots. Never edit generated graphs/receipts/snapshots or treat them as authority. Claude's
search reminder is nonblocking; Codex follows AGENTS rather than a PreToolUse hook.
