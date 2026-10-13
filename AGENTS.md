# Avrana Party: instructions for coding agents

Avrana Party is a local-first multiplayer appliance. Phones join its Wi-Fi and
play browser-based games without an internet connection. The TV is optional.

## Default: build one useful change

- Follow the current user request. Read the affected code, nearby tests, and
  only the architecture docs relevant to the change.
- Work as one agent on one branch. Do not launch an orchestrator, subagents,
  Graphify scans, ticket sweeps or other process unless the task requires them.
- Implement the smallest working result. Run targeted local tests as you edit.
  Before handoff run any additional tests warranted by the changed behavior.
- Push/open a PR only when reviewable. Do not manually dispatch Actions,
  repeatedly rerun green tests, or push exploratory commits merely for CI.
- Handoff in at most five short lines: what changed, tests (including not run),
  known risk, PR link, and one next action. No duplicate reports or backlog churn.

## Non-negotiable safeguards

- Never merge, deploy or alter the live Pi without explicit owner approval.
  Never force-push, rewrite shared history, or commit secrets, private data,
  credentials, ROMs or runtime state.
- If changing login/identity, cookies, origins, game protocol, persistence,
  service isolation, game installation or deploy scripts: run relevant tests,
  arrange independent review, and ask before changing approved architecture.
- Party owns cross-game identity, sessions and navigation. Coordinate a paired
  Games change for incompatible contract changes; do not silently change one
  side. Keep deployed reality separate from merged source and simulated tests.
- Only real Pi/phone testing proves Wi-Fi, iPhone/Safari and hardware behavior.
  Mark these untested unless physically verified.

## Reference when needed

- Source and tests: current checkout
- Product decisions: the request or relevant Linear issue
- Architecture: `docs/adr/`, `docs/design/`, `docs/SYSTEM.md`
- Tests: `docs/TESTING.md`
- Cross-repo changes: `docs/CROSS-REPO.md`
- Deployment: `docs/runbooks/deploy.md`
- Optional process and CI notes: `docs/WORKFLOW.md`

No required AI-workflow CLI, worktree claims, external graph generation,
implementation-report template, or automatic multi-agent review.
