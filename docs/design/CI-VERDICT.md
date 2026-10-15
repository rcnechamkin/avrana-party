# One CI verdict check (proposal)

Status: **ACCEPTED architecture (owner decision 2026-10-14) · native-game deferred · not yet verified by a hosted run; nothing is required yet**

AVR-305. Pull requests need one check that always reports and says whether the lanes that apply
to the change passed, so that it can be made required without path-filtered workflows leaving
unrelated pull requests waiting for a check that never appears.

## What is built

`.github/workflows/ci-verdict.yml` runs on every pull request and calls the lanes as reusable
workflows (`workflow_call`): `Offline checks`, `Cross-repo contract`, and `Service trust proof`
when the change touches a platform path (its `native-game` job is deferred, below). Its last job is named
**`CI verdict`** and runs `tools/ci_verdict.py` with `if: always()`, so it reports even when a
lane fails, is cancelled or is skipped. The decision is a pure function, covered by
`tests/unit/test_ci_verdict.py`:

- `Offline checks` and `Cross-repo contract` apply to every pull request and must have succeeded.
- A platform path changed: `Service trust proof` must have succeeded. Its `native-game` job is
  **deferred** (owner decision 2026-10-14): not run from the verdict and not required until Actions
  billing, runner availability and a hosted verification run are resolved. Turning it on is two
  coordinated edits: `NATIVE_GAME_REQUIRED = True` in `tools/ci_verdict.py` and `native_game: true`
  in `ci-verdict.yml`. A native-game run that does happen (manual dispatch) and fails still fails.
- No platform path changed: they are not required, and a docs-only change passes without them. If
  one ran anyway and failed or was cancelled, the verdict fails.

Platform paths are the `paths:` filter the `Service trust proof` workflow had on pull requests
(`tools/ci_verdict.py` `PLATFORM_PATHS`, kept equal by a test). It is a superset of the five areas
named in AVR-305 (`avrana/`, `contracts/`, `deploy/`, `ops/provision-game`, `experiments/`); the
rest are the installers, `web/party/`, the nginx site, `tests/package/`, the node fixture, the
appliance fixtures and the workflow file itself.

## Changes to the lane workflows

- `pull_request` is removed from `offline-checks.yml`, `cross-repo.yml` and
  `service-trust-proof.yml` (and the proof's `paths:` filter, kept as a comment). Otherwise each
  lane would run twice per pull request, once by itself and once from the verdict workflow. Their
  `push` (main) and `workflow_dispatch` triggers and every job are unchanged.
- `service-trust-proof.yml` gains `workflow_call` with a `native_game` input and a
  `native_game_result` output. `native-game` used to run only on manual dispatch (workflow v3);
  its `if:` also accepts `native_game`, which the verdict workflow passes as `false` while the job is
  deferred. A small `native-game-result` job reports the job's result, because a skipped job
  otherwise looks like success to the caller. What it tests is unchanged; it costs nothing extra
  until it is switched on.
- Check names change: the lanes' jobs now appear as `CI verdict / ...` in the checks list.

## Proposed setting (nothing is switched on)

Repository ruleset for `main` (Settings, Rules, Rulesets) or the equivalent branch protection
rule: enable **Require status checks to pass**, and add the single check named **`CI verdict`**
(the job in `ci-verdict.yml`; GitHub Actions as its source). Do not add `Offline checks`,
`Cross-repo contract` or `Service trust proof` as required checks; the verdict covers them.
Enable it only after the verdict has been seen green on a docs-only pull request, red on a pull
request with a failing lane, and green on a platform-path pull request. Hosted runs for those three were not possible when this was written (the account's
Actions billing is blocked), so they remain open.
