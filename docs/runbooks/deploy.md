# Runbook: deploy reviewed commits to the appliance with `ops/deploy.sh`

Status: **current procedure (AVR-232, AVR-262); not yet run in production** as of 2026-10-04. The
earlier per-issue scripts and the manual sequences in
[party-core-deploy](party-core-deploy.md) and [games-fork-deploy](games-fork-deploy.md) remain
the reference for first-time installation (units, keys, nginx, drop-ins). This runbook covers
the routine case: both services are installed and a newer reviewed commit should run.

Production deployment is a human decision and a human action. Nothing in CI, in an agent's
task or in this document authorizes it. Merged is not deployed; deployed is not phone-verified.

## Before

1. Both PRs merged; both CI lanes green, including `Cross-repo contract` (Party) and
   `cross-repo` (Games).
2. Write down the two full SHAs: Party `main` and Games `main` (or the exact Games commit the
   Party change was tested against).
3. If the Games commit is not yet on the Pi (its clone comes from a bundle, see
   [games-fork-deploy](games-fork-deploy.md) §1), stage it first.
4. No party in progress: the script refuses while a game session is live.

## First run: a checkout that predates this script

An appliance whose Party checkout is older than AVR-232 has no `ops/deploy.sh` and no
`avrana.ops` (the Pi at `bb7364c` on 2026-10-04). It is deployed with the same script and the
same arguments; only the place the script is read from differs, because the checkout cannot
supply it yet. Take the script from the target commit, without moving the checkout:

```bash
ssh party "git -C /home/cody/avrana-party fetch origin && git -C /home/cody/avrana-party show <PARTY_SHA>:ops/deploy.sh > /tmp/avrana-deploy.sh"
ssh party "bash /tmp/avrana-deploy.sh --party <PARTY_SHA> --games <GAMES_SHA> --dry-run"
ssh -t party "sudo bash /tmp/avrana-deploy.sh --party <PARTY_SHA> --games <GAMES_SHA>"
```

Nothing else is special. The script never runs Python tooling out of the checkout: before it
stops anything it builds the target commit's release under `/opt/avrana-party/releases/<sha>`
and runs the manifest and smoke tooling from there, so the before-state, the manifest and the
smoke result are produced by the commit being deployed. Rollback on a failed start is the same
as in any run. This first run is also what creates `/opt/avrana-party` and
`/opt/avrana-party-games`. Afterwards the checkout has the script and the section below applies.

Going back to such a commit (the command a failed smoke prints) works too: the target then has
no tooling, so the script uses the release that is running and says so. Its smoke run will fail
on `/party/api/status`, which that older commit does not serve; the manifest records `failed`
and the build that is running.

## Deploy

```bash
ssh -t party "sudo bash /home/cody/avrana-party/ops/deploy.sh --party <PARTY_SHA> --games <GAMES_SHA> --dry-run"
ssh -t party "sudo bash /home/cody/avrana-party/ops/deploy.sh --party <PARTY_SHA> --games <GAMES_SHA>"
```

The dry run prints the plan: which checkout moves, which units restart, whether a web release is
built. It reads state and fetches remote refs; it changes no file, checkout, service, backup or
manifest and does not need root. The real run then:

| Step | What happens | Refuses when |
|---|---|---|
| 1 | lock, inspect both checkouts, fetch Party, check the targets | another deploy runs; a checkout is dirty (`--allow-dirty`); the Party SHA is not on `origin/main` (`--allow-branch`); the Games SHA is absent; a session is live (`--force-busy`) |
| 2 | build (not yet link) the target Party release under `/opt`, choose the tooling release (the target's, or the running one when the target predates `avrana.ops`), record `before.json` and the current web release under `/var/backups/avrana-party/deploy-<UTC>/` | neither release carries the tooling: nothing is stopped |
| 3 | stop only the units whose repository changes (Party: `avrana-party-core`, `avranaparty-arcade`; Games: `avranaparty-games`), check both repositories out **detached at exactly the named commits**, build a root-owned code release of each changed repository (`/opt/avrana-party/releases/<sha>`, `/opt/avrana-party-games/releases/<sha>`, each with a `current` link; what the services run after [the service-users migration](service-users-migration.md), unused before it), build an atomic web release (`ops/install-party-web.sh`), start providers then Party Core | a unit does not come back: both checkouts return to the branch or commit they were on (no `--force`, no `reset --hard`), the previous web release and code-release links are restored, units restart, and no manifest is written |
| 4 | write the [deployment manifest](../design/DEPLOYMENT-MANIFEST.md); grant search (`o+x`, not listing) on its directory so the service user can read it, unless a subdirectory there is open to group or other | |
| 5 | run `python3 -m avrana.ops.smoke`, record `passed`/`failed` in the manifest | exit 2 on failure, with the rollback command printed |

Keys, certificates, nginx, NetworkManager, systemd unit files and drop-ins are never touched.
Those remain the first-time runbooks' owner steps.

## After

```bash
curl -s https://party.avrana.net/party/api/status | python3 -m json.tool   # from the Party LAN
```

`summary.state` should be `ok`; `party.deployed_sha` and `games.deployed_sha` are the build.
`avrana-party-certificate.timer` is optional: until automatic renewal is set up
([party-https](party-https.md)) smoke prints `SKIP unit:avrana-party-certificate.timer not installed`
and status lists it under `summary.notes`. The `certificate` check still fails below 21 days.
Then:

1. Move the Linear issue to **In Review** with the `Human Validation` label when phone acceptance
   remains (the `Ready for Playtest` state in [WORKFLOW](../WORKFLOW.md)).
2. Do the physical check on real phones. Findings become a new issue or close this one.
3. Update [SYSTEM](../SYSTEM.md) from the manifest (`python3 -m avrana.ops.manifest validate`
   prints the SHAs) and add a dated finding only when something noteworthy happened.

## When it fails

- **Refused before any stop**: nothing changed. Fix the stated reason.
- **Rolled back**: the log names the failing step; the checkouts are at the before-state and
  units are up. Read `journalctl -u <unit> -n 50`.
- **Smoke failed after deploy** (exit code 2): the new code is running and the manifest says
  `smoke: failed`. Read `smoke.txt` in the backup directory and `/party/api/status`; either fix
  forward with another deploy or go back. Going back is the same command with the earlier SHAs,
  which the failing run prints:

```bash
sudo bash /home/cody/avrana-party/ops/deploy.sh --party <BEFORE_PARTY_SHA> --games <BEFORE_GAMES_SHA>
```

Because every deployment is a detached checkout of a named commit, forward, backward and
rollback are one operation. After the first run the Party checkout is no longer "on `main`":
that is intended; do not `git pull` in it. `--allow-branch` is only for a supervised test of a
commit that is not on `origin/main`.

## Paths and overrides

Defaults match SYSTEM; environment variables override them for a dev/test tree:
`AVRANA_PARTY_CHECKOUT`, `AVRANA_GAMES_CHECKOUT`, `AVRANA_WEB_ROOT`, `AVRANA_DEPLOYMENT_MANIFEST`,
`AVRANA_BACKUP_ROOT`, `AVRANA_PARTY_CORE_URL`, `AVRANA_PARTY_HOST`, `AVRANA_CHECKOUT_USER`.
