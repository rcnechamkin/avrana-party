# Development workflow v2: ship small, verify deliberately

Avrana Party is a one-owner product with AI help, not a staffed engineering department.
Every step must either produce behavior, detect a meaningful defect, or keep the release
safe. If a step does none of these, it is optional. [AGENTS.md](../AGENTS.md) owns the
agent's entry rules. This workflow also applies to the Games repository.

## The loop

1. **Decide:** The owner gives one outcome, constraints and an observable acceptance test
   (a short prompt or existing AVR issue is enough). Ask only about blocking decisions.
2. **Implement:** One agent reads the touched code and tests, works on one branch and
   runs small, relevant local tests. No default orchestration, committee of subagents,
   Graphify refresh, status sweeps or large report.
3. **Verify:** Fix focused-test failures locally. For risky changes, run the affected
   integration/regression tests and use an independent reviewer. Do not present
   simulations as proof of physical behavior.
4. **Reviewable PR:** Push only when ready. One concise PR description with changed
   behavior, test evidence, risks, and owner action. Let GitHub CI run; do not
   manually dispatch repeats or keep pushing intermediate exploration.
5. **Merge:** The owner reviews and merges, coordinating Party/Games pairs where
   required. A green PR is not authorization to deploy.
6. **Accept:** The owner deploys deliberately, verifies the Pi and real phones,
   and marks the feature accepted or files one specific defect.

**Default WIP:** one feature under active implementation across Party/Games. At most
one additional independent investigation when authorized. Existing PRs can be
triaged separately; do not open new work to fill imaginary agent capacity.

## Two risk lanes

| Routine | High risk |
|---|---|
| UI, copy, isolated bugfix, docs | Identity/auth, trust, private data, protocol/contract, persistence, install/deploy, systemd, Wi-Fi, system lifecycle |
| One implementing agent | One implementing agent; independent reviewer after code is ready |
| Focused tests while editing | Focused tests plus relevant contract, security and integration proofs |
| Short PR description and owner review | Explicit acceptance evidence, paired PRs if required, owner review |
| Physical acceptance if user-visible | Physical/on-appliance acceptance before considered done |

An agent does not self-upgrade routine work into a multi-agent sprint. If the change
crosses into a high-risk category, stop and get the owner's scope decision.

## CI cost and test policy

- **Local iteration:** Run affected lint/unit/module tests after edits. Run a full
  local suite only if the change demands it or before a significant handoff.
- **Hosted CI:** Do not dispatch workflows during development. Use GitHub PR CI on
  a stable candidate. Cancel superseded PR runs; never rerun a green job merely
  to get another green job. Re-run failed checks only after identifying why.
- **Risk and release:** Keep contract checks, trust-boundary proofs, real-browser
  evidence and clean-room checks when applicable. A release may need a complete
  regression run, but ordinary UI changes do not justify repeated full
  systemd/game-package proof.
- **Reality check:** Linux CI cannot prove Pi Wi-Fi, iOS captive portal, real
  multi-phone play or hardware performance. Keep that work in a physical
  acceptance checklist.
- **Cost limit:** No agent may change billing/spending limits, launch an
  expensive manual matrix, or introduce scheduled workflows without the owner's
  explicit approval.
- **Transition:** Existing CI definitions may still execute broad suites on PRs.
  Do not weaken a required status check until a replacement quick/full split
  has been verified against the existing checks and repository settings.

## Context, review and documentation

Read current code and nearest tests before scanning the whole documentation tree.
Canonical architecture and ADRs matter when the touched behavior depends on them.
Graphify is optional search assistance; never auto-run it before every shell command.

Review routine diffs in the same session; for high-risk changes, use a fresh
independent reviewer who did not author the code. A separate verification agent
is not required when test outputs already provide the evidence.

There is one authoritative status per concern:
- **Code and tests:** GitHub.
- **Requested behavior and owner decisions:** Linear when an issue exists; the
  current owner prompt may scope a routine task.
- **Architecture:** canonical docs and accepted ADRs.
- **Deployed reality:** `/party/api/status`, deployment manifest and actual device.
- **Human acceptance:** explicit phone/Pi observations.

Update Linear once when the PR is ready and once after acceptance if necessary.
Do not create issues for every interesting tangent. Do not repeat the entire PR
description in chat, Linear and a final sprint report. For an ordinary task the
handoff should fit in approximately five lines.

## Safety stays non-negotiable

Agents do not merge or deploy without express permission. They never write
secrets, alter production Pi services, silently change a public contract, or
claim a test that did not run. Incompatible Party/Games changes are paired.
Any destructive, security-sensitive or product-direction decision belongs to
the owner. See [AGENTS](../AGENTS.md), [REVIEW](../REVIEW.md),
[CROSS-REPO](CROSS-REPO.md), [TESTING](TESTING.md), and the
[deploy runbook](runbooks/deploy.md).

## Measure whether the reset works

For the next three completed features record only:
- elapsed time from request to reviewable change;
- hosted CI minutes and avoidable reruns;
- agent usage/time spent coordinating versus implementing;
- actual Pi/phone acceptance and regressions.

Success means lower overhead **without** less reliable integration and security.
If an added process does not improve those outcomes, remove it.
