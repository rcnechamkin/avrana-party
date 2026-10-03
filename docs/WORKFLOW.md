# Development workflow: from decision to deployed, with agents in the loop

This is how a change moves through Avrana Party, which systems hold which truth, and where a
human must act. [AGENTS](../AGENTS.md) is the agent entry point; this page is the whole loop.
Linear workflow details that only the owner can change are marked **(manual)**.

## Source-of-truth hierarchy

Highest authority first. When two disagree, the higher one wins for its own question; most
apparent conflicts are different questions (merged source may be ahead of production).

1. Code and automated tests on GitHub `main` (what is implemented)
2. Canonical repository documentation (manifest class `canonical`, status `current`)
3. Accepted ADRs (`docs/adr/`, reading each status and amendment)
4. The current Linear issue (the desired delta: what should change, and how success is judged)
5. Draft/proposed documentation (direction, not contract)
6. Historical documentation: findings, archives, old handoffs (evidence of what was true when written)

The deployed appliance is authoritative about what is running: the
[deployment manifest](design/DEPLOYMENT-MANIFEST.md) and `/party/api/status`
([STATUS-ENDPOINT](design/STATUS-ENDPOINT.md)). Chat history is never a source of truth.

## The loop

| # | Step | Who | Where it is recorded |
|---|---|---|---|
| 1 | Product discussion | Cody (+ assistants) | nowhere authoritative |
| 2 | Decision becomes a Linear issue and, for architecture, an ADR | Cody | Linear; `docs/adr/` |
| 3 | Issue reaches **Ready for Agent** (see states below) | Cody | Linear state |
| 4 | Agent receives only the AVR number | Cody | the task |
| 5 | Agent reads the issue, source, tests, relevant canonical docs, `/party/api/status` | agent | [AGENTS](../AGENTS.md) §Starting work |
| 6 | Agent implements and tests on `type/avr-N-desc` branches (paired across repos when needed) | agent | branches, [CROSS-REPO](CROSS-REPO.md) |
| 7 | PR opens with the [implementation report](agents/IMPLEMENTATION-REPORT.md); issue moves to **In Review** | agent | GitHub PR, Linear |
| 8 | CI validates the repository and the Party ↔ Games contract against the paired branch | CI | GitHub checks |
| 9 | Review and merge | Cody | GitHub |
| 10 | Deterministic deploy of named SHAs | Cody, on the Pi | `ops/deploy.sh` ([runbook](runbooks/deploy.md)) |
| 11 | The Pi writes the deployment manifest | `ops/deploy.sh` | `/var/lib/avrana-party/deployment.json` |
| 12 | Smoke checks run and are recorded in the manifest | `ops/deploy.sh` | manifest `smoke`, backup dir |
| 13 | Issue moves to **Ready for Playtest** | Cody | Linear |
| 14 | Physical test on real phones | Cody | findings when noteworthy |
| 15 | Findings become a new issue, or the issue becomes **Done** | Cody | Linear |
| 16 | Scheduled reconciliation catches drift between Linear, GitHub, docs and the deployed build | CI (weekly) | `Drift reconciliation` workflow report |

Steps 1 to 4, 9, 10, 13 to 15 are deliberately human. Everything else should need no manual
translation between systems.

## Linear states

Team AvranaKern today: `Backlog`, `Todo`, `In Progress`, `In Review`, `Done`, `Canceled`,
`Duplicate`. The loop uses them as:

| Loop state | Linear today | Meaning |
|---|---|---|
| Needs Cody | `Backlog` (or `Todo` with unresolved **Open Decisions**) | not ready for an agent |
| Ready for Agent | `Todo` with an empty **Open Decisions** section | an agent may start |
| In Progress | `In Progress` | someone is working it |
| PR / CI | `In Review` | PR open, CI/review pending |
| Ready for Playtest | `In Review` + label `Human Validation` | merged (and usually deployed); phones pending |
| Done | `Done` | acceptance criteria met with evidence |

**(manual)** Linear's connected MCP cannot create workflow states or issue templates. If the
owner wants the names to match, add states `Ready for Agent` (type unstarted, after `Todo`) and
`Ready for Playtest` (type started, after `In Review`) in Team settings → Workflow, then update
this table. Until then the mapping above is the contract.

The rule either way: **an issue is not Ready for Agent while its Open Decisions section holds an
unresolved product decision.** An agent that finds one stops and asks instead of guessing.

## Implementation issue structure

Every implementation issue carries these sections (the team document *Issue templates* in
Linear mirrors this; the `avr-issue` skill writes them). An agent treats the issue as the desired
delta, not as a second architecture document: canonical docs and code describe the present.

- **Outcome**: the desired end state, one paragraph.
- **Acceptance Criteria**: observable conditions; each becomes evidence in the report.
- **Out of Scope**: what must not change.
- **Repositories**: `avrana-party`, `avrana-party-games`, or both (paired PRs).
- **Tests Required**: the behavioral/integration tests that must exist or pass.
- **Dependencies**: AVR issues (`blockedBy` relations), PRs, contract versions, infrastructure.
- **Open Decisions**: questions for Cody. Must be empty for Ready for Agent.

Research and Human Validation issues keep their own templates (Question / Method / Decision
criterion; Build under test / Steps / Evidence boundary).

## Branches, PRs and pairing

`type/avr-N-short-description` in both repositories. CI pairs branches by the `avr-N` token;
without a match the other repository is `main`. PR bodies link their pair and name the merge
order. See [CROSS-REPO](CROSS-REPO.md). Never force-push; never merge your own PR as an agent.

## What CI enforces (agent-neutral)

| Check | Where | Fails when |
|---|---|---|
| Repository integrity: manifest, links, classes, generated freshness, nginx pair, agent layers | `npm run check:repo` (offline lane) | structure or authority rules break |
| Historical documents edited without intent | offline lane, PRs only | `docs/archive/**` or an existing finding is modified and the PR lacks the `historical-edit` label |
| Unit, module and offline browser suites | offline lane | behavior regresses |
| Party ↔ Games contract and session protocol | `Cross-repo contract` (Party), `cross-repo` (Games) | declarations drift from code or from each other; the real-service test fails or would skip |
| Deployment manifest / status schemas | unit tests | shapes change without tests |
| Drift report | `Drift reconciliation`, weekly and on demand | never fails the build; publishes actionable / informational / could-not-run |

Documentation staleness (`last_verified`) is reported, never enforced.

## Deployment and physical testing

`sudo bash ops/deploy.sh --party <sha> --games <sha>` is the only deployment path for routine
releases ([runbook](runbooks/deploy.md)). It refuses dirty or unexpected state, restarts only
what changed, writes the manifest and runs the smoke checks. First-time installation steps
(units, keys, nginx, certificates) stay in their runbooks. Real phones, Party Wi-Fi, streaming
and power remain Tier 3 evidence that only a human produces ([TESTING](TESTING.md)).

## Field reports

`https://party.avrana.net/party/diag/` shows the running build (Party and Games SHAs, contract,
service summary, browser, time) with a copy button. Nothing is uploaded; the person pastes it
into the issue.

## Agent tooling (convenience, never enforcement)

`python tools/avr_context.py AVR-N` prints the issue's sections, the paired branches and PRs in
both repositories and the deployed build, read-only, and says plainly what it could not reach.
For Claude Code, `.claude/settings.json` runs `tools/claude_gate.py` before Bash and edit tools:
a merge, force-push, history rewrite or production command becomes a question to the person at
the keyboard, and editing a contract file, a generated file or an existing historical document
adds a reminder. Every rule it mentions is enforced elsewhere (branch protection and review for
merges, the owner's sudo for the Pi, CI for contracts, generated files and history).

## Derived context

Graphify ([GRAPHIFY](GRAPHIFY.md)) indexes code and current documentation and excludes findings,
archives and research by configuration, so default retrieval returns current architecture. It is
navigation, never authority: verify in code, tests and canonical docs.
