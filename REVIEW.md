# Review instructions

Use risk-based review. Routine UI/content/isolated bugfix work needs one
focused diff review by the implementing session and passing relevant tests.
High-risk changes (security/trust, identity, protocol/contract, persistence,
deployment, lifecycle) **require** a reviewer who did not write the change.
A reviewer who fixes a finding is no longer independent. Only the owner
merges or deploys. See [AGENTS.md](AGENTS.md) and [WORKFLOW](docs/WORKFLOW.md).

## High-risk review passes

- **Bugs:** logic errors, broken edge cases, regressions, weakened tests.
- **Trust:** identity, origin, cookie, listener, Unix-socket, secrets and data boundaries
  in ADRs 0006, 0013 and 0016; paired Party/Games compatibility.
- **Fit:** explicit acceptance criteria, accepted ADRs, true deployed state,
  and no out-of-scope work.

Tag only actionable findings. Important means broken behavior, weakened
security, false validation/deployment claims, or incompatible paired changes.
Cap style nits at five; do not restate what CI already proves.

## Change class

**Owner attention required:** an architecture/ADR decision, security or trust
change, public protocol/contract, operations/deploy/nginx changes, product
decision, or anything explicitly marked Needs Cody.

**Routine:** everything else. Owner still authorizes merge; agent does not
treat theoretical auto-merge eligibility as permission.

Paired Party/Games work is a single merge set. Say which PRs are open,
which checks passed, and the merge order. Do not call one half ready alone.
