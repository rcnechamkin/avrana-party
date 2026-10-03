# Implementation report (the one completion format)

An agent or contributor ends a task with this report, in the PR description and in the final
message. Short is fine; missing fields are not. "Not applicable" and "not run" are valid values;
a claim is not. [AGENTS](../../AGENTS.md) defines Done; this is how Done is shown.

```markdown
## Implementation report: AVR-NNN <title>

- **Repositories:** avrana-party, avrana-party-games
- **Branches:** <type>/avr-NNN-<desc> (party), <type>/avr-NNN-<desc> (games)
- **Commits:** <sha> ..., <sha> ...
- **PRs:** rcnechamkin/avrana-party#NN, rcnechamkin/avrana-party-games#NN (merge order)
- **Behavioral changes:** one line per observable change; "none" for pure refactors/docs
- **Tests run:** exact commands and results (counts, failures, skips), per repository and OS
- **CI:** green / red / not yet run, with the run link when known
- **Documentation changed:** files, and which canonical doc now describes the behavior
- **Deployment performed:** no | yes, by <who>, `ops/deploy.sh --party <sha> --games <sha>`
- **Deployed SHA:** only when actually deployed, from `/party/api/status`
- **Unresolved blockers:** what needs Cody (product decision, credential, physical test)
- **Follow-up work discovered:** new issues created or proposed, one line each
```

Rules:

- Tests you did not run are "not run". Linux-only failures seen on Windows are listed as such;
  Linux CI is authoritative.
- "Deployment performed: no" is the normal answer. An agent never deploys production.
- Physical acceptance is reported as pending unless a human did it.
- Linear status after the report: **In Review** (or the playtest state in
  [WORKFLOW](../WORKFLOW.md)), never Done, when review, CI or phones remain.
