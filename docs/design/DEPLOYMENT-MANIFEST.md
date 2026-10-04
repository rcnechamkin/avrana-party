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
`/var/backups/avrana-party/deploy-<UTC stamp>/`.

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

`dirty` is recorded, never hidden: `ops/deploy.sh` refuses a dirty checkout unless
`--allow-dirty` is given, and the manifest then says so.

## Tooling

```sh
python3 -m avrana.ops.manifest validate                 # exit 1 and a reason when malformed/missing
python3 -m avrana.ops.manifest write --out PATH --party DIR --games DIR --web-root DIR
python3 -m avrana.ops.manifest smoke PATH passed|failed|skipped
```

`avrana/ops/manifest.py` is stdlib-only; `tests/unit/test_ops_manifest.py` covers observation,
validation, atomic writes and the CLI. A validation failure names the field.

## What it is not

Not deployment authorization, not phone acceptance, not a replacement for dated findings when a
deployment goes wrong. A manifest with `smoke.status = failed` is a deployed system that failed its
checks; the decision to fix forward or roll back stays with the owner
([runbook](../runbooks/deploy.md)).
