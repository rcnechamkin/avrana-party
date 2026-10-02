# Contributing to Avrana Party

Start with [README](README.md) for the product and repository layout, then
[AGENTS](AGENTS.md) for shared operational rules and [docs](docs/README.md) for the authority map.
Those rules apply to humans and coding agents alike.

## Pick and scope work

[Linear](https://linear.app/avranakern) owns live priorities, sequencing, blockers, acceptance and
ownership. If you cannot access it, ask the maintainer to confirm scope; archived prompts and
ROADMAP milestones are not assignments. Inspect open PRs before starting overlapping work.
Read the relevant [ADRs](docs/adr/) and [design documents](docs/design/README.md). Preserve
accepted decisions; a proposal needs an explicit accepted decision before it changes a contract.

Fetch `origin`, inspect `git status` and current `origin/main`, and create a short-lived branch
such as `chore/avr-123-description` or `fix/avr-123-description`. Use a descriptive branch when
there is no issue. Keep experiments isolated. A stacked PR must identify its base PR and merge
order. Never force-push, rewrite history or develop in a production checkout.

## Set up and test locally

Use Node 22 (CI pins 22.22.2), npm and Python 3.12+. Run from the repository root:

```sh
npm ci
npm run check:repo
npm run test:unit
npm run test:modules
npx playwright install chromium
npm run test:offline-browser
npx playwright test tests/soak-metrics.spec.ts
```

The checker uses `python` on Windows and `python3` elsewhere. Existing `test:unit`, `catalog`
and `dev` scripts use `python3`; Windows installations with only `python` can run
`python -m unittest discover -s tests/unit`, `python -m avrana.contracts.catalog --check` and
`python -m avrana.web.devserver --port 8180` directly. Do not change production commands to suit
a local shell. [TESTING](docs/TESTING.md) is the detailed command/evidence reference.
For offline browsers on Windows, set `$env:AVRANA_PYTHON = 'python'` if `python3` is unavailable.

Choose focused tests for the changed contract, then run the offline lane before review.
Linux CI requires real nginx and logrotate; Windows may skip or fail Linux-specific process,
shell and symlink tests. Report that honestly and wait for Linux CI. Tier 2 browsers at phone
sizes do not prove iPhone Safari, AP behavior, streaming hardware, power or physical acceptance.
Cross-repository provider tests require two explicit local checkouts; Games has independent CI.

`npm test`, `test:all`, soak and fault target the live Pi. Running them requires separate hardware
scope/authorization. No contribution authorizes deployment, service restarts or edits to live
nginx, DNS, NetworkManager, systemd, certificates, Wi-Fi or production checkouts.

## Edit source and documentation

Use [GENERATED](docs/GENERATED.md) before touching built CSS, icons, avatars, artwork or catalogs.
Change the source and commit regenerated outputs together; `check:repo` composes freshness gates.
Keep the two committed nginx files byte-identical. Do not add secrets, ROMs, BIOS, emulator cores,
runtime data, personal telemetry or installer backups. Use synthetic fixtures.

Every Markdown document must have an entry in [manifest.json](docs/manifest.json).
Choose its class, status and limited authority; do not duplicate its contents in the manifest.
Use relative links for local files. Before moving a file, search all tracked references and use
`git mv`; repair links and code-span paths. Preserve historical claims with dates and explicit
archive/evidence labels. Research is context until promoted through an accepted decision.

Record findings as `docs/findings/YYYY-MM-DD-description.md`, with observed date, source/release
SHAs, commands, environment, evidence tier, results and limitations. Never infer deployment from
a merge or phone acceptance from server/browser automation. Update SYSTEM only from deployment
evidence. Keep live work in Linear and strategy in ROADMAP; do not add root handoff logs.

## Submit a PR

Include the problem, resulting behavior, issue link, scope, source/generated changes, test
commands/results and any unverified hardware behavior. For docs, identify authority and moved
paths. For new decisions, explain amendments without silently rewriting earlier ADR decisions.
Before every push, confirm the branch, inspect the complete diff and changed-file list, run
`git diff --check`, and scan for secrets/runtime artifacts. CI must pass before merge.
Merge and deployment remain separate decisions; nothing is released merely because it lands.

## Licensing and sensitive reports

The root package metadata says `ISC`, but there is no repository LICENSE. This discrepancy needs
an owner decision; this guide grants no new license. Preserve existing third-party notices.
Do not put credentials or exploit details exposing a live appliance in a public issue. If GitHub
offers private vulnerability reporting, use the repository Security tab; otherwise ask the
maintainer for a private channel without including sensitive details. No private address or
reporting service is assumed here.
