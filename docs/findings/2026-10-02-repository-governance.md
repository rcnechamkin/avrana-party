# Repository governance audit — 2026-10-02

Historical source/metadata evidence only. No Pi connection, deployment or hardware validation.

## Baseline and boundaries

- GitHub main inspected and fetched: `bb7364c6e3bc2151ee74491f854d240b64cde522`. Main offline CI was green (run 36963633080).
- PR #36 was OPEN at `718984faf340f5a2169293fd458b7b027e5cc578`, with green offline CI
  (run 36964600500). This migration stacks on its reconciled authority model; it does not merge it.
- Linear AVR-213 records separate outstanding production-evidence/Games follow-ups. The shared
  checkout's untracked worktrees and AVR-130 staging finding were left untouched. Published SYSTEM
  evidence was not advanced from assumptions or uncommitted material.
- Local branches/worktrees and origin refs were inspected. The cached `party-dev` refs are
  historical only; that SSH remote was not fetched or contacted. No local branches/worktrees deleted.

## Inventory and classification

The complete documentation classification is in [manifest](../manifest.json). At migration:

| Area | Role / treatment |
|---|---|
| Root README and agent files | Human entry; one AGENTS operational authority, brief compatibility pointers |
| `avrana/`, `web/`, `arcade/`, `portal/`, `contracts/` | Working source/contracts; no product edits or arbitrary code moves |
| `docs/design`, ADRs, strategy, SYSTEM, TESTING | Domain-scoped truth; mixed/proposed status retained |
| Findings and old handoffs | Dated evidence; handoffs moved to archive with Git history |
| Broad substrate/reference research | Moved under `docs/research`; no architecture promotion |
| `experiments/diplomacy` | Explicitly abandoned; moved intact under `experiments/archive/diplomacy` |
| `assets/vendor`, generated CSS/icons/avatars/art/catalog | Provenance and existing freshness checks recorded |
| `deploy`, `ops`, telemetry, root config/installers | Owner-run operational assets; root paths deliberately retained for consumers/byte identity |
| `tests`, GitHub offline workflow, package tooling | Existing offline lanes plus governance checks; live suites remain separate |
| Ignored release/test output, caches, runtime files | Not source; not added or recursively scanned |

## Remote branch deletion proof

For **each** ref below, freshly fetched main was `bb7364c6e3bc2151ee74491f854d240b64cde522`; `git rev-list --count main..HEAD`
returned **0** and `git merge-base --is-ancestor HEAD main` succeeded. GitHub branch protection
was false, effective branch rules empty, no repository/parent rulesets existed, and no open PR
used the ref. None is in the retained research inventory. Main/ref SHAs, protection, effective
rules and open PR heads were checked again immediately before deletion. GitHub readback confirmed
the refs absent. Their commits remain reachable from main; no unique commits or history deleted.

| Deleted remote branch | Full head SHA contained in main | Commits ahead |
|---|---|---|
| `chore/avr-51-deploy-prep` | `cbef3b49d09d5af13ff44653defd433963852253` | 0 |
| `chore/avr-51-nginx-party-api` | `7da654daaf3d66ed11dcb28fe2125b2f6cc90b5e` | 0 |
| `docs/avr-51-restart-rollback` | `4ce3b387a2c0acb08eabe50b3f3554e092b5d120` | 0 |
| `docs/avr-91-bluff-party-home-finding` | `9ebffcb2086c65333516d57971fe254325936c96` | 0 |
| `docs/2026-09-29-avr128-134-deploy` | `3e6bfbef5774fae315cb642ecd9703957262cb0a` | 0 |
| `docs/2026-09-29-deploy` | `28933ceb15878b4ab2031dc8ef0276c19957823b` | 0 |
| `feat/avr-129-party-pregame` | `738a2efac1f2b511f6728ae8fa2189fc80db55e5` | 0 |
| `feat/party-console-model` | `6794281f84353bdd11893d375267dd81b2d6c3b6` | 0 |
| `fix/avr-20-127-host-launch` | `b374964480d585935a3a4630ff168ccac5267504` | 0 |
| `fix/avr-30-log-bounds` | `a6eeef4048693cefa5fceb879b909d94460655c6` | 0 |
| `fix/avr-91-bluff-party-home` | `5f0c05c2a0e5db909cf3b07700ea9643a54626aa` | 0 |
| `fix/avr-92-gauntlet-launch` | `973893a4a002f0374f6aafcf52c5bbc2173a324b` | 0 |
| `fix/avr-128-party-navigation` | `ace8056d65e089be2e319d738fb8497d9e4779fa` | 0 |
| `fix/avr-130-arcade-seat-reconnect` | `249d23e9994297f2f3f034219a09d175e08c0a35` | 0 |
| `fix/avr-134-arcade-provider` | `3d929bce9fae9664ed0f77a9e642dcd0f8552a1f` | 0 |
| `fix/party-protocol-unb64-invalid` | `12aaf44a12b9246fc1a5ad2547d6b390c53c5af6` | 0 |
| `fix/provider-tests-briefing-ack` | `80749507c92290bbb5caef84dbd4349a61e39214` | 0 |

The five divergent branches in [branches.json](../branches.json) were deliberately retained,
with full heads and ahead/behind counts. PR #36's active head was retained. That inventory is a
dated retention record, never live task sequencing. Do not wholesale-merge preserved experiments.

## Presentation and package metadata

- GitHub description set to: Portable, local-first multiplayer appliance hosted on Raspberry Pi. Phones play in a browser; no internet or app required for core play.
- Topics: raspberry-pi, local-first, multiplayer, browser-games, webrtc, self-hosted.
- Homepage remains empty; the Party-network runtime hostname is not a public marketing site.
- Root npm tooling marked private; nonexistent `main`, empty author/keywords removed; Node 22
  engine recorded to match the CI major. Version/dependency versions and existing scripts preserved.
- `ISC` package license left unchanged; no repository LICENSE exists. Owner decision required.
- No SECURITY contact/address invented; contribution guidance explains conditional private reporting.

## Deliberately unresolved

ADR 0004 preserves mixed accepted/proposed status text alongside its merged-PR note. The manifest
flags that ambiguity without reinterpreting decisions. PR #36 and Linear own the pending deployment
evidence follow-up; this migration does not claim its completion or physical-phone acceptance.
Test results for the migration belong to its PR/CI revision, not this branch-retention proof.
