# Development workflow: simple by default

One task -> one agent -> targeted local tests -> one PR -> owner review ->
deliberate Pi/phone acceptance.

## Working mode

- No orchestrator, mandatory subagents, mandatory AI-workflow claims, Graphify
  refresh, Linear issue ceremony, detailed report or ticket explosion.
- Read only affected code, tests and relevant architecture.
- Implement one observable change on a branch. Use local tests while coding.
  Push only when the change is ready for review.
- Handoff in no more than five short lines: change, evidence, risk, PR, next step.
- Review high-risk changes independently. Owner approves merges and releases.
- Never auto-deploy. Real phones/Pi are the acceptance standard for the
  physical behaviors automation cannot simulate.

## CI

Pull requests run fast checks. The existing full offline, cross-repo,
systemd/package and game-server suites remain available via **Run workflow**
(`workflow_dispatch`). Run full relevant verification for security,
admission/identity, protocols/contracts, native games, SDK packages,
installation/deployment, major refactors or release candidates.

Fast CI is not proof that a risky change is release-ready. Do not merge a
high-risk change before its required full checks pass. A green Linux runner
still is not a Wi-Fi or iPhone test.

Cancel outdated PR runs. Do not manually dispatch repeated checks while
editing or treat every exploratory commit as a candidate release.

## Sources of truth

Code/tests: current GitHub checkout. Product decisions: the explicit request
or relevant Linear issue. Architecture: accepted ADRs and current docs.
Production: Pi status and deployment manifest. Physical acceptance: real
device observation.

## Local migration from the previous workflow

- Update each checkout to the merged workflow and **start a new Claude Code
  session**, so prior task context cannot keep driving the old process.
- If AI-workflow installed Git commit hooks on your machine and you no longer
  need multi-agent claims, run `python aw.py setup --uninstall` from the sibling
  `AI-workflow` checkout. It removes only its managed hooks.
- Check user-level Claude hooks/settings and any workspace-level overrides.
  This repository does not control user-level `~/.claude/settings.json` or
  `.claude/settings.local.json`. Remove obsolete Graphify/task-management
  hooks there if present; do not remove unrelated safeguards.
- `AI-workflow`, Graphify, optional specialist agents and Linear remain
  available **on demand**. Nothing needs deleting to stop depending on them.

This is a coding workflow, not a business-process framework.
