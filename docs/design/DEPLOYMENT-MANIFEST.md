# Deployment manifest (`avrana.deployment/v0`)

Status: **implemented on main (AVR-232)**; written by `ops/deploy.sh` on the Pi; read by
`/party/api/status`, the smoke checks and the drift reconciliation. Whether a given appliance has
one depends on whether it has been deployed with `ops/deploy.sh`: [SYSTEM](../SYSTEM.md) records
verified production state.

## Why

The running appliance is the authority on what is running. Before this file existed, the deployed
revision lived in people's memory, dated findings and a hand-edited table in SYSTEM. A moving Git
tag was rejected: it lives in the repository, not on the machine, and it says nothing about the
Games checkout, the web release, dirtiness or the smoke result. The manifest is runtime-owned
state; documentation is updated *from* it.

## Where

`/var/lib/avrana-party/deployment.json`, mode 0644, root-owned, written atomically. The
directory also holds the root-only ACME state (`lego/`, 0700) and was created 0700, so
`ops/deploy.sh` grants search without listing on it (0711) for the service user that serves
`/party/api/status`; it leaves the directory closed, with a warning, when a subdirectory there
is open to group or other. Every
deployment also keeps `before.json`, `after.json` and `smoke.txt` under
`/var/backups/avrana-party/deploy-<UTC stamp>/`, and beside the manifest the
[last-known-good record](#last-known-good-record).

## Schema

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | always `avrana.deployment/v0` |
| `deployed_at` | ISO 8601 UTC (`...Z`) | when the manifest was written (after services restarted) |
| `deployed_by` | string | the operator's login (`$SUDO_USER`); never a secret |
| `tool` | `{name, party_sha}` | `ops/deploy.sh` and the Party commit whose release supplied the manifest and smoke tooling: the deployed commit, or the previously running one when the deployed commit predates `avrana.ops` |
| `party`, `games` | `{sha, short, dirty, untracked, ref, checkout}` | the observed production checkouts: `dirty` means tracked files were modified, `untracked` counts untracked non-ignored files, `ref` is `null` for a detached checkout (the normal state after `ops/deploy.sh`) |
| `web_release` | `{path, build, commit}` or `null` | the installed `/party/` release's `version.json` |
| `contract` | `{party_games, party_session, lan_launch}` | the identifiers from [the contract declaration](PARTY-GAMES-CONTRACT.md) |
| `restarted` | `[unit, ...]` | the systemd units this deployment restarted (only those whose code changed) |
| `smoke` | `{status, at}` | `pending` while the deployment runs, then `passed`, `failed` or `skipped` |
| `contract_check` | `{status, at}`, optional | how `ops/deploy.sh` judged the Party/Games pair with `tools/contract_check.py` on the two exact commits: `compatible`, `not_checkable` (a commit predates the checker or the declaration) or `skipped` (`--skip-contract-check`). Absent in manifests written before this field existed |
| `nginx_site` | `{status, sha256, at}`, optional | what `ops/deploy.sh` did with the nginx site file: `installed`, `unchanged` (already equal to the deployed commit's `avrana-party.nginx`), `skipped` (`--skip-nginx-site`) or `not_managed` (the commit has none); `sha256` is the hash of the live file afterwards (AVR-271) |
| `deploy_options` | `{skip_smoke, skip_contract_check, no_auto_rollback, force_busy, allow_dirty, allow_branch, skip_nginx_site, rollback}`, optional | every flag the run was given (booleans) and `rollback`: `null` for an ordinary deployment, `manual` (`--rollback`), `recover` (`--recover`) or `auto` (the rollback after a failed smoke) |

`dirty` is recorded, never hidden: `ops/deploy.sh` refuses a dirty checkout unless
`--allow-dirty` is given, and the manifest then says so.

## Tooling

```sh
python3 -m avrana.ops.manifest validate                 # exit 1 and a reason when malformed/missing
python3 -m avrana.ops.manifest write --out PATH --party DIR --games DIR --web-root DIR
python3 -m avrana.ops.manifest smoke PATH passed|failed|skipped
python3 -m avrana.ops.manifest contract-check PATH compatible|not_checkable|skipped
python3 -m avrana.ops.manifest deploy-info PATH --nginx-status installed --nginx-sha256 HEX [--option skip_smoke ...] [--rollback-kind auto]
python3 -m avrana.ops.manifest last-known-good record|seed MANIFEST OUT [--party DIR --games DIR]
```

`avrana/ops/manifest.py` is stdlib-only; `tests/unit/test_ops_manifest.py` covers observation,
validation, atomic writes and the CLI. A validation failure names the field.

## Last-known-good record

`/var/lib/avrana-party/last-known-good.json` (beside the manifest, mode 0644, schema
`avrana.last-known-good/v0`) names the last deployment whose smoke checks **passed**:
`party_sha`, `games_sha`, `web_release` (`{build, commit}`), `nginx_site_sha256`, `deployed_at`,
`smoke_at`, `recorded_at` and `seeded_from_running_deployment`. It is written only after a passed
smoke and never by a failed or skipped-smoke deployment; `ops/deploy.sh --rollback` and the automatic
rollback after a failed smoke deploy exactly this pair. An appliance deployed before the record
existed gets it seeded once from its running deployment, when that manifest says `passed` and both
checkouts are still at its commits. `/party/api/status` shows it as `last_known_good`.

## What it is not

Not deployment authorization, not phone acceptance, not a replacement for dated findings when a
deployment goes wrong. A manifest with `smoke.status = failed` is a deployed system that failed its
checks. Since AVR-271 `ops/deploy.sh` rolls such a deployment back to the last known good by
default (`--no-auto-rollback` keeps it for debugging, and the manifest records that); fixing forward
instead stays the owner's decision ([runbook](../runbooks/deploy.md)).
