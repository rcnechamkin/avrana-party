# Review instructions

Every pull request is reviewed by a session or subagent that did not write it
(`.claude/agents/reviewer.md`). The author never reviews their own change, and a reviewer who
fixes a finding is no longer that change's reviewer. Review informs the merge; it does not
perform it. [AGENTS.md](AGENTS.md) holds the rules this file checks against.

## Passes

Run three passes and tag each finding with its pass.

- **Bugs**: logic errors, broken edge cases, regressions, a test that cannot fail, a test
  weakened to make a change pass.
- **Trust**: anything that moves a boundary in ADR
  [0006](docs/adr/0006-party-session-protocol.md), [0013](docs/adr/0013-party-and-game-browser-origins.md)
  or [0016](docs/adr/0016-service-identities-and-local-trust-boundary.md): who may call what,
  cookies and origins, key files and their modes, listeners and sockets, what a game can make
  the Party do. Secrets or private data in logs, fixtures or docs.
- **Fit**: the change does what the Linear issue's acceptance criteria and the approved plan
  say and nothing outside them; it agrees with accepted ADRs; `docs/SYSTEM.md` still describes
  deployed reality only; a contract change has its paired change in Games
  ([CROSS-REPO](docs/CROSS-REPO.md)).

## What Important means here

Reserve Important for a finding that would break behavior, weaken a trust boundary, change an
accepted decision without an amendment, describe something as deployed or validated that is
not, or land one half of a paired cross-repo change. Naming, wording and style are nits.

## Change class

End every review by naming the class, because it decides who merges.

- **Owner merges**: an architecture or ADR change; a security or trust change; a Party and
  Games protocol or contract change; anything under `deploy/`, `ops/` or the nginx site files;
  a product decision; anything marked Needs Cody.
- **Routine**: everything else. Docs-only, current with `main` and green may merge without the
  owner once branch protection and required checks exist.

A paired change is one merge set: name both pull requests and say whether both are open, green
and current. Never call one half mergeable alone.

## Cap the nits

Report at most five nits; give the rest as a count.

## Do not report

Generated files ([GENERATED](docs/GENERATED.md)), anything `npm run check:repo` or CI already
enforces, historical documents under `docs/archive/` and `docs/findings/`, and Windows-only
test failures that Linux CI does not show.
