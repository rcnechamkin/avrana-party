# Runbook: deploy reviewed commits to the appliance with `ops/deploy.sh`

Status: **current procedure (AVR-232, AVR-262, AVR-271); the hardening of AVR-271 (interruption
handling, last known good, automatic rollback, site-file install, pruning) is proved by the unit
suite on Linux and by no run on the appliance.** The earlier per-issue scripts and the manual
sequences in [party-core-deploy](party-core-deploy.md) and [games-fork-deploy](games-fork-deploy.md)
remain the reference for first-time installation (units, keys, drop-ins); a clean target is
[rebuild](rebuild.md) (proposed, not run). This runbook covers the routine case: both services are
installed and a newer reviewed commit should run.

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
5. Read where the machine stands: `sudo bash /home/cody/avrana-party/ops/deploy.sh --status` prints
   the last known good and how the last run ended. A run that died and was never recovered blocks
   the next deploy until it is (see "A run that died" below).
6. If the site file of the commit refers to a file the appliance does not have yet (the
   `games.avrana.net` certificate, AVR-319), install that first
   ([game-origin](game-origin.md)): `nginx -t` rejects the site otherwise and the deploy fails
   (exit 1, nothing stopped, everything put back).

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
smoke result are produced by the commit being deployed. This first run is also what creates
`/opt/avrana-party` and `/opt/avrana-party-games`. Afterwards the checkout has the script and the
section below applies.

Going back to such a commit (an explicit `--party/--games` deploy of it, or `--rollback` when it is
the last known good) works too: the target then has no tooling, so the script uses the release that
is running and says so. Its smoke run will fail on `/party/api/status`, which that older commit
does not serve; the manifest records `failed` and the build that is running.

An appliance deployed before the last-known-good record existed has none: the first run of this
script seeds it from the running deployment when that deployment's manifest says `smoke: passed`
and both checkouts are still at the commits it names (`last-known-good seeded from the running
deployment` in the output). If it does not apply, the first deploy has nothing to roll back to and
a failed smoke keeps today's behaviour (exit 2).

## Deploy

```bash
ssh -t party "sudo bash /home/cody/avrana-party/ops/deploy.sh --party <PARTY_SHA> --games <GAMES_SHA> --dry-run"
ssh -t party "sudo bash /home/cody/avrana-party/ops/deploy.sh --party <PARTY_SHA> --games <GAMES_SHA>"
```

The dry run prints the plan: which checkout moves, which units restart, whether a web release is
built, whether the nginx site file differs (line counts only: `live N lines, deployed M; +A -R`),
and which old releases and backups would be pruned after a passed smoke. It reads state and fetches
remote refs; it changes no file, checkout, service, backup, journal or manifest and does not need root.

**The run survives a dropped SSH session.** A real run starts itself again in its own session
(`setsid`) with its output in `/var/backups/avrana-party/deploy-<UTC>.log`; the command you typed
only follows that log and returns the run's exit code. If the connection drops (SIGHUP) or you press
Ctrl-C, the deployment carries on; if it finishes with a rollback, the log says so. To see it again:

```bash
sudo tail -f /var/backups/avrana-party/deploy-<UTC>.log     # the log named at the top of the run
sudo bash /home/cody/avrana-party/ops/deploy.sh --status    # phase, last known good, running or dead
```

To stop a run on purpose, send SIGTERM to the pid in the journal (`kill -TERM <pid>`): it rolls back
before the commit point and stops where it is after it. `AVRANA_DEPLOY_DETACH=0` keeps a run in the
foreground (the signal traps still apply, but a dropped terminal is then the only protection).

The real run:

| Step | What happens | Refuses when |
|---|---|---|
| 1 | lock, inspect both checkouts, fetch Party, check the targets | another deploy runs; a previous run died and was not recovered; a checkout is dirty (`--allow-dirty`); the Party SHA is not on `origin/main` (`--allow-branch`); the Games SHA is absent; the two commits disagree on the Party <-> Games contract (`tools/contract_check.py` run on both exact commits; `--skip-contract-check` for a supervised test; a commit that predates the check is warned about, not refused); a session is live (`--force-busy`) |
| 2 | build (not yet link) the target Party release under `/opt`, choose the tooling release (the target's, or the running one when the target predates `avrana.ops`), record `before.json`, the current web release and a copy of this script under `/var/backups/avrana-party/deploy-<UTC>/`, open the journal, seed the last-known-good record if there is none | neither release carries the tooling: nothing is stopped |
| 3a | **nginx site file**: read `avrana-party.nginx` of the target Party commit from Git; when it differs from `/etc/nginx/sites-available/avrana-party`, back the live file up (`nginx-site-before` in the backup directory), write the new one atomically, `nginx -t`, `systemctl reload nginx`. Nothing is stopped yet | root is missing; the commit's `avrana-party.nginx` and `arcade/nginx-site` differ (they must be byte-identical); `nginx` or the site directory is absent; `nginx -t` rejects the file (typically a certificate file that does not exist yet: the old file is put back, tested and reloaded, the output is printed and the missing prerequisite named); the reload fails |
| 3b | stop only the units whose repository changes (Party: `avrana-party-core`, `avranaparty-arcade`; Games: `avranaparty-games`), check both repositories out **detached at exactly the named commits**, build a root-owned code release of each changed repository (`/opt/avrana-party/releases/<sha>`, `/opt/avrana-party-games/releases/<sha>`, each with a `current` link), build an atomic web release (`ops/install-party-web.sh`), start providers then Party Core | a unit does not start or does not stay active: the rollback below |
| 4 | write the [deployment manifest](../design/DEPLOYMENT-MANIFEST.md) (**the commit point**), record the contract-check result, the nginx site file's hash and every flag of the run; grant search (`o+x`, not listing) on the manifest directory so the service user can read it, unless a subdirectory there is open to group or other | |
| 5 | smoke (`python3 -m avrana.ops.smoke`), record `passed`/`failed`. Passed: record the **last known good** and prune. Failed: **automatic rollback** to the last known good (below) | |

Keys, certificates, NetworkManager, systemd unit files and drop-ins are never touched. The
installed site file is the one thing under `/etc` this script writes, and only that one file.

### The rollback before the commit point

Any failure in steps 3a to 4, and a SIGHUP, SIGINT or SIGTERM, runs **one** restore (never twice, never
after step 4): both checkouts return to the branch or commit they were on (no `--force`, no
`reset --hard`), the previous web release and code-release links are put back, the previous site file
is put back, tested with `nginx -t` and reloaded, and **every unit this run stopped is restarted**
(restarted, not just started, so a unit already running the new code goes back too). No manifest is
written. The units that are active at exit are printed and recorded in the journal. If any part of the
restore fails, or a unit is down afterwards, the exit code is 4.

### The rollback after a failed smoke

The new revision is running and `smoke: failed` is in the manifest (kept as `failed-manifest.json` in
the backup directory). If a last-known-good record exists and is not the very pair that just failed,
the script runs itself again as a rollback deployment of that pair (code releases, checkouts, web
build and site file together, restarting what differs), runs smoke again and prints both results:
`DEPLOYMENT FAILED, ROLLED BACK` (exit 3) when the rolled-back revision passes, `ROLLBACK APPLIED BUT
ITS SMOKE ALSO FAILED` (exit 4) when it does not. A rollback never rolls back again. With no record
(the first deployment ever), `--no-auto-rollback`, or when the record is the failed pair, the new
revision is kept and the exit code is 2, with the manual command printed.

## Options

| Flag | Effect | Recorded in the manifest (`deploy_options`) |
|---|---|---|
| `--dry-run` | print the plan, the site-file difference and the prune list; change nothing | n/a (no manifest) |
| `--allow-dirty` | deploy over uncommitted changes in a checkout | `allow_dirty`; `party.dirty`/`games.dirty` |
| `--allow-branch` | a Party commit that is not on `origin/main` | `allow_branch` |
| `--force-busy` | deploy while a game session is live | `force_busy` |
| `--skip-contract-check` | do not run `tools/contract_check.py` on the pair | `skip_contract_check`; `contract_check.status: skipped` |
| `--skip-smoke` | do not smoke; the last known good is not updated; nothing is pruned | `skip_smoke`; `smoke.status: skipped` |
| `--no-auto-rollback` | keep a revision whose smoke failed (exit 2) | `no_auto_rollback` |
| `--skip-nginx-site` | do not touch the nginx site file | `skip_nginx_site`; `nginx_site.status: skipped` |
| `--keep N` (`AVRANA_DEPLOY_KEEP`) | keep the newest N code releases, web releases and deploy backups (default 5, minimum 2) | not recorded |
| `--no-prune` | prune nothing | not recorded |
| `--status` | print the last known good, the journal and whether a run is live, dead or finished | n/a |
| `--rollback` | deploy the last known good (no SHAs). Not subject to the branch or contract checks | `rollback: manual` |
| `--recover` | after a dead run: converge on the last known good, re-applying every repository and restarting every unit; works with a session live | `rollback: recover` |

`rollback` is `null` for an ordinary deployment and `auto` for the rollback the script ran after a failed smoke.
`nginx_site.status` is `installed`, `unchanged`, `skipped` or `not_managed` (the target commit has no
`avrana-party.nginx`), with the live file's `sha256`.

## What happened / what to do

**By exit code** (the command you typed returns the run's code):

| Exit | What happened | What to do |
|---|---|---|
| 0 | Deployed. Smoke passed (or was skipped by flag: then it is not the last known good) | Phone acceptance; [After](#after) |
| 1 | Refused before anything changed, **or** failed and the restore finished (checkouts, links, site file back; units started). The log names the step | Fix the stated reason and run again. Nothing is half-done. For `nginx -t` read the printed `MISSING PREREQUISITE` lines |
| 2 | Applied, smoke **failed**, and the new revision is still running (no last known good yet, `--no-auto-rollback`, or the record is the failed pair) | Read `smoke.txt` in the backup directory and `/party/api/status`. Fix forward, or `sudo bash .../deploy.sh --rollback` / the explicit SHAs it prints |
| 3 | Applied, smoke failed, **rolled back** to the last known good, whose smoke passed | The deployment failed and the party is safe on the old revision. Read the failed run's `smoke.txt` and `failed-manifest.json` in its backup directory |
| 4 | **A person is needed**: a restore step failed, a unit is down, or the rolled-back revision also fails smoke | `--status`, `journalctl -u <unit> -n 50`, then `--recover` (below). The output lists the units that are not active |
| 129, 130, 143 | The run was signalled (SIGHUP, SIGINT, SIGTERM) **after** step 4, the commit point: nothing was rolled back. (Before it the restore runs and the code is 1 or 4) | `--status`; the manifest says what is running; smoke is the open question |

**By journal phase** (`--status`, file `/var/backups/avrana-party/deploy.journal`). A phase that is not an end,
with no live process, means the run died (SIGKILL, power loss) and nothing restored it:

| Phase | Meaning | What to do |
|---|---|---|
| `started` | Backup taken; nothing changed yet, or only the site file | `--recover` (or just deploy again after `--recover`) |
| `site-installed` | New site file live; no service stopped | `--recover` |
| `stopped-services` | Units are stopped, checkouts not yet switched | `--recover` (starts them) |
| `switched` | Checkouts, releases, web build moved; units not (all) started | `--recover` |
| `restarted` | Units started with the new revision; manifest not written | `--recover` |
| `committed` | Manifest written; smoke result unknown | The new revision is applied. Run the smoke by hand (`cd /opt/avrana-party/current && python3 -m avrana.ops.smoke`) and, if it passes, `python3 -m avrana.ops.manifest smoke /var/lib/avrana-party/deployment.json passed`; or `--rollback` |
| `auto-rollback` | The automatic rollback was running when the run died | `--recover` |
| `smoke-passed` / `smoke-skipped` | A finished run | nothing |
| `smoke-failed` | Smoke failed, revision kept (exit 2) | as exit 2 |
| `auto-rolled-back` | Exit 3 | as exit 3 |
| `rolled-back` | The pre-commit restore finished (exit 1) | as exit 1 |
| `rollback-failed` | Exit 4 | as exit 4 |

### A run that died

```bash
sudo bash /home/cody/avrana-party/ops/deploy.sh --status      # the phase, and the last known good it would return to
sudo bash /home/cody/avrana-party/ops/deploy.sh --recover     # converge on the last known good
```

`--recover` is chosen over an automatic repair at the start of every run on purpose: a half-switched
machine is evidence, and an unrelated command should not silently rewrite it. Until it is run, every
ordinary deploy refuses with the phase it found. `--recover` re-applies everything (it does not trust
"already there"): both checkouts are checked out at the last known good, code releases and the web
build are re-linked, the site file is installed, and **all** units are restarted. Without a
last-known-good record it returns to the before-state the dead run wrote in its journal. It needs both
commits to still exist in the checkouts; if one is gone, deploy explicit SHAs.

### Going back by hand

```bash
sudo bash /home/cody/avrana-party/ops/deploy.sh --rollback                       # the last known good
sudo bash /home/cody/avrana-party/ops/deploy.sh --party <SHA> --games <SHA>      # any earlier pair
```

Because every deployment is a detached checkout of a named commit, forward, backward and rollback
are one operation. After the first run the Party checkout is no longer "on `main`": that is
intended; do not `git pull` in it. `--allow-branch` is only for a supervised test of a commit that
is not on `origin/main`.

## The nginx site file and the web build are one unit

Since AVR-259 the nginx site file and the web build are one deployment unit: the catalog of a
commit offers exactly the games its site file routes. `ops/deploy.sh` now installs both, in one
run, and restores both together on any failure or rollback (a rollback deployment installs the site
file of the older commit). Web build alone: the retired LAN Games tiles disappear and their old
routes still answer. Site file alone: the old Party Home shows tiles that lead to nginx's 502.

`/party/api/status` is the independent check and still stands: it is `degraded` (and so the step 5
smoke fails) while the installed `/etc/nginx/sites-available/avrana-party` differs byte for byte from
the deployed commit's `avrana-party.nginx`, or the live web build is from a different commit than the
deployed Party. A site file the service user cannot read reads `unavailable` and the state is
`unknown`, never `ok`. `nginx_site.sha256` in the status and the manifest is the hash of the live file.

**The Pi today.** It runs Party `c59f1c8` with a site file older than `main`'s. The first deploy with
this script installs the newer one (`nginx site: DIFFERS ...` in the dry run) instead of failing smoke
and waiting for a manual `cp`; it passes only if `nginx -t` accepts it on that machine. If the
`games.avrana.net` certificate is not installed yet, `nginx -t` rejects the site, the old file is put
back, nothing was stopped, and the exit code is 1 with `MISSING PREREQUISITE` naming the file: install
the certificate ([game-origin](game-origin.md)) or run once with `--skip-nginx-site` (status then
stays `degraded` until the site file is installed). The `sites-enabled` link is not managed; the
script warns when `/etc/nginx/sites-enabled/avrana-party` does not resolve to the file it wrote.

The manual sequence (first-time install, or `--skip-nginx-site`) is step 6 of
[party-core-deploy](party-core-deploy.md).

## Releases and backups accumulate; the newest N stay

After a **passed** smoke (never after a failure, a skipped smoke or `--no-prune`) the script keeps the
newest `N` (`--keep`, default 5, minimum 2) of: code releases `/opt/avrana-party/releases/<sha>` and
`/opt/avrana-party-games/releases/<sha>` (by modification time), web releases `.../web/releases/<stamp>-<sha12>`
and deploy backups `/var/backups/avrana-party/deploy-<stamp>` (by name). It never removes the running
release (what `current` points to), the previous one, the one being deployed, the last known good, or
the backup of the current or the last journalled run. Only a plain directory whose name has exactly the
expected shape is a candidate, and its resolved path must be exactly `<directory>/<name>`: links, odd
names, `.new.*` build leftovers and a `releases` directory that is itself a link are skipped and
named in the output. `--dry-run` lists what would be removed. The web build uses the same number
(`AVRANA_WEB_KEEP`, passed on by the script, which prunes web releases itself after smoke instead of at
install time). A standalone `install-party-web.sh` still prunes its own releases, to the same default.

## After

```bash
curl -s https://party.avrana.net/party/api/status | python3 -m json.tool   # from the Party LAN
```

`summary.state` should be `ok`; `party.deployed_sha` and `games.deployed_sha` are the build;
`last_known_good` names the pair the next failure returns to; `nginx_site` is `match`.
`avrana-party-certificate.timer` is optional: until automatic renewal is set up
([party-https](party-https.md)) smoke prints `SKIP unit:avrana-party-certificate.timer not installed`
and status lists it under `summary.notes`. The `certificate` check still fails below 21 days.
Then:

1. Move the Linear issue to **In Review** with the `Human Validation` label when phone acceptance
   remains (the `Ready for Playtest` state in [WORKFLOW](../WORKFLOW.md)).
2. Do the physical check on real phones. Findings become a new issue or close this one.
3. Update [SYSTEM](../SYSTEM.md) from the manifest (`python3 -m avrana.ops.manifest validate`
   prints the SHAs) and add a dated finding only when something noteworthy happened.

## Game covers (the owner's, never committed)

A game can have a cover picture the owner supplies (box art). Covers are not in Git, so they do
not arrive with a commit: they live in one folder on the Pi, `/srv/avrana/covers` (beside the
ROM; `AVRANA_COVERS_DIR` names another), and every web release copies from it.

```bash
sudo install -d -m 0755 /srv/avrana/covers
sudo install -m 0644 ps1-worms.jpg arcade-gauntlet2.jpg ps1-bomberman.jpg /srv/avrana/covers/
sudo bash /home/cody/avrana-party/ops/install-party-web.sh /home/cody/avrana-party
```

- A cover is named for its game: `<game id>.jpg`, `.jpeg`, `.png`, `.webp` or `.avif`. The ids
  are the file names in `contracts/games/` (for example `arcade-gauntlet2`, `ps1-bomberman`,
  `ps1-worms`).
- Only plain picture files pass, at most 1 MB each and 64 in all; a link is never followed, a
  folder inside is not looked in. A file that does not pass is left out and the install says so
  (`cover left out: <name>: <why>`); it never fails the install. A picture is published as what
  it really is, whatever its name says.
- The third command builds a web release from the checkout as it is and the folder as it is:
  static files only, no service restarts, safe during a round. `ops/deploy.sh` does the same
  whenever it builds a web release, so covers already in the folder ride along with every Party
  deploy; a changed cover alone needs only that third command. Then reload the phones.
- Each release keeps the covers it was built with. `install-party-web.sh --rollback`, and the
  deploy putting things back by itself when a step fails, return to the release before as it was
  built, its covers included. Rolling back by deploying an earlier commit builds a new release from
  that commit and the folder as it is now, so the covers stay as they are now. A covers-only
  install is one of the releases kept.
- For another folder, name it on the command: `sudo AVRANA_COVERS_DIR=/some/folder bash …`
  (plain `sudo` does not pass your shell's variables on).
- JPEG, PNG and WebP always work. An AVIF cover is only sure to be drawn if nginx sends its
  type: `grep avif /etc/nginx/mime.types` (not checked on the Pi).
- nginx is not involved: covers are files of the release, under `/party/covers/`.

## Paths and overrides

Defaults match SYSTEM; environment variables override them for a dev/test tree:
`AVRANA_PARTY_CHECKOUT`, `AVRANA_GAMES_CHECKOUT`, `AVRANA_WEB_ROOT`, `AVRANA_DEPLOYMENT_MANIFEST`,
`AVRANA_BACKUP_ROOT`, `AVRANA_PARTY_CORE_URL`, `AVRANA_PARTY_HOST`, `AVRANA_CHECKOUT_USER`,
`AVRANA_PARTY_RELEASES`, `AVRANA_GAMES_RELEASES`, `AVRANA_NGINX_SITE`
(`/etc/nginx/sites-available/avrana-party`), `AVRANA_NGINX_ENABLED`, `AVRANA_NGINX` (the binary),
`AVRANA_LAST_KNOWN_GOOD` (default: `last-known-good.json` beside the manifest), `AVRANA_DEPLOY_LOCK`,
`AVRANA_DEPLOY_KEEP`, `AVRANA_DEPLOY_DETACH=0`. `AVRANA_SYSTEMCTL`, `AVRANA_DEPLOY_UNPRIVILEGED`,
`AVRANA_DEPLOY_SMOKE`, `AVRANA_DEPLOY_PYTHON` and `AVRANA_DEPLOY_TEST_HOOK_DIR` exist only for
`tests/unit/test_deploy_script.py`; do not set them on the appliance. A real run needs root (the
services, the web root and the site file); a run without it refuses before touching anything.
