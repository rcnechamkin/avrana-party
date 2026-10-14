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
6. The served certificate must cover every name the new site file answers. On the Pi (read 2026-10-12) it
   covers `party.avrana.net` only, so the `games.avrana.net` server block of `main`'s site file would present a
   certificate for the wrong name (phones get a name-mismatch error on the game origin; Party itself is
   unaffected). The deploy checks this before changing anything (`openssl x509 -checkhost` for each
   `server_name` of each `listen 443 ssl` block, as root), prints a `WARNING` naming the host and records it
   (`nginx_site.cert_name_mismatch`), and still deploys; `--require-cert-names` refuses instead, whenever the flag
   is given (also when the live site file already equals the deployed one). Only a listener on exactly port 443
   counts, and a parsing failure never blocks a deploy by default. Install a certificate with both names first:
   [game-origin](game-origin.md).
7. `nginx -t` must already pass on the running configuration: the deploy tests it before replacing the
   site file and refuses (exit 1, nothing changed) when it fails. `--recover` and `--rollback` are the exception:
   a dead run may have left a site file nginx rejects, which is exactly the state they exist for, so they print a
   warning, install the site file of the pair they return to and validate that; only if nginx rejects that one
   too does the restore fail (exit 4, a person is needed).
8. Scope: the unit list is fixed (`avrana-party-core`, `avranaparty-arcade`, `avranaparty-games`). Units that
   a newer revision adds (`avrana-party-core.socket`, `avrana-game@*`, the service-user migration) are
   **not** installed, enabled, stopped or started by this script; their runbooks own them
   ([service-users-migration](service-users-migration.md), [party-core-deploy](party-core-deploy.md),
   [game-origin](game-origin.md)).

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
(`setsid`) with its output in `/var/backups/avrana-party/deploy-<UTC>-<pid>.log` (the pid keeps two runs
that start in the same second apart). What you see is that log followed live (`tail -f`), and the command
returns the run's exit code. **Ctrl-C detaches; it does not abort**: the follower says so and exits 130 while the
deployment carries on, as it does when the connection drops (SIGHUP). If it finishes with a rollback, the log
says so. To see it again:

```bash
sudo tail -f /var/backups/avrana-party/deploy-<UTC>.log     # the log named at the top of the run
sudo bash /home/cody/avrana-party/ops/deploy.sh --status    # phase, last known good, running or dead
```

To abort a run on purpose: `--status` shows the pid, then `sudo kill -TERM <pid>`. That fires the restoring
trap: before the commit point everything is put back (exit 1); after it nothing is rolled back and the code is
143. `AVRANA_DEPLOY_DETACH=0` keeps a run in the foreground (the signal traps still apply, but a dropped terminal
is then the only protection).

The real run:

| Step | What happens | Refuses when |
|---|---|---|
| 1 | lock, inspect both checkouts, fetch Party, check the targets | another deploy runs; a previous run died and was not recovered; a checkout is dirty (`--allow-dirty`); the Party SHA is not on `origin/main` (`--allow-branch`); the Games SHA is absent; the two commits disagree on the Party <-> Games contract (`tools/contract_check.py` run on both exact commits; `--skip-contract-check` for a supervised test; a commit that predates the check is warned about, not refused); a session is live (`--force-busy`) |
| 2 | build (not yet link) the target Party release under `/opt`, choose the tooling release (the target's, or the running one when the target predates `avrana.ops`), record `before.json`, the current web release and a copy of this script under `/var/backups/avrana-party/deploy-<UTC>/`, open the journal, seed the last-known-good record if there is none | neither release carries the tooling: nothing is stopped |
| 3a | **nginx site file**: read `avrana-party.nginx` of the target Party commit from Git; when it differs from `/etc/nginx/sites-available/avrana-party`, back the live file up (`nginx-site-before` in the backup directory), write the new one atomically, `nginx -t`, `systemctl reload nginx`. Nothing is stopped yet | root is missing; the commit's `avrana-party.nginx` and `arcade/nginx-site` differ (they must be byte-identical); `nginx` or the site directory is absent; `nginx -t` rejects the file (typically a certificate file that does not exist yet: the old file is put back, tested and reloaded, the output is printed and the missing prerequisite named); the reload fails |
| 3b | stop only the units whose repository changes (Party: `avrana-party-core`, `avranaparty-arcade`; Games: `avranaparty-games`), check both repositories out **detached at exactly the named commits**, build a root-owned code release of each changed repository (`/opt/avrana-party/releases/<sha>`, `/opt/avrana-party-games/releases/<sha>`, each with a `current` link), build an atomic web release (`ops/install-party-web.sh`, then the installed-package catalog is made to match it or removed, warning only; a running `install-game` can delay this step by at most 30 s, waited once, with the units stopped), start providers then Party Core | a unit does not start or does not stay active: the rollback below |
| 4 | write the [deployment manifest](../design/DEPLOYMENT-MANIFEST.md) (**the commit point**), record the contract-check result, the nginx site file's hash and every flag of the run; grant search (`o+x`, not listing) on the manifest directory so the service user can read it, unless a subdirectory there is open to group or other (the root-owned, root-written public `catalog/` of installed packages excepted) | |
| 5 | smoke (`python3 -m avrana.ops.smoke`) with a settle window: a failing result is retried every 3 s for up to 90 s (`--smoke-settle`, `AVRANA_DEPLOY_SMOKE_SETTLE`; the arcade's RetroArch and the games provider need tens of seconds on a Pi 4 and each check already waits 5 s), then `passed`/`failed` is recorded. Passed: record the **last known good** and prune. Failed: exit 2 with the one command back (`sudo bash .../deploy.sh --rollback`); with `--auto-rollback`, roll back only what the deploy broke (below) | |

A refusal before step 3b (it says `nothing changed`) also removes the backup directory and the staged release this
run created, so it leaves nothing behind; a release that already existed is never removed.

Keys, certificates, NetworkManager, systemd unit files and drop-ins are never touched. The
installed site file is the one thing under `/etc` this script writes, and only that one file.

### The rollback before the commit point

Any failure in steps 3a to 4, and a SIGHUP, SIGINT or SIGTERM, runs **one** restore (never twice, never
after step 4): both checkouts return to the branch or commit they were on (no `--force`, no
`reset --hard`), the previous web release and code-release links are put back (and, when `.avrgame` packages are installed, the
effective game catalog built for the failed web release is regenerated or removed; warning only, see
[install-game](install-game.md); a rollback target that predates the overlay code just loses it until the next forward deploy; the stale file is removed at once and any wait for a running `install-game`, at most 30 s, comes only after the site file and the units are back), the previous site file
is put back, tested with `nginx -t` and reloaded, and **every unit this run stopped is restarted**
(restarted, not just started, so a unit already running the new code goes back too). No manifest is
written. The units that are active at exit are printed and recorded in the journal. If any part of the
restore fails, or a unit is down afterwards, the exit code is 4.

### After a failed smoke

The default is the contract you know: the new revision is running, `smoke: failed` is in the manifest (kept as
`failed-manifest.json` in the backup directory), the exit code is 2, and the message prints the single command
back: `sudo bash /home/cody/avrana-party/ops/deploy.sh --rollback` (the explicit before-state SHAs when no last known good exists yet).

`--auto-rollback` is opt-in, because a smoke result 3 seconds after a restart can also reflect faults the deploy did
not cause. With it, the script smokes the running appliance **before anything is stopped** (the baseline, saved as
`smoke-baseline.json` and listed in the journal) and, after the deploy, rolls back **only if a check that passed in the
baseline now fails**. Checks that already failed before (an expiring certificate, a web build that was stale, a differing
site file) are reported as `PRE-EXISTING, NOT CAUSED BY THIS DEPLOY` and the run exits 2 without moving anything. A
check that the baseline *skipped* and that fails now is reported as `NOT CHECKED BEFORE THE DEPLOY, FAILING AFTER`
(there is nothing to compare with): also exit 2, no automatic rollback. When
there is a regression and a last known good that is not the failed pair, the script runs itself as a nested rollback
deployment of that pair (code releases, checkouts, web build and site file together), runs smoke again and prints both
results: `DEPLOYMENT FAILED, ROLLED BACK` (exit 3) when the rolled-back revision passes, `ROLLBACK APPLIED BUT ITS SMOKE
ALSO FAILED` (exit 4) when it does not. A rollback never rolls back again. `--auto-rollback` turns itself off for a run,
and says so, when there is no baseline to measure against (the first deployment, an unreadable baseline), with
`--skip-smoke`, with `--skip-nginx-site` (that flag makes the status check degrade by design), and in a rollback.
`--no-auto-rollback` is still accepted and does nothing.

## Options

| Flag | Effect | Recorded in the manifest (`deploy_options`) |
|---|---|---|
| `--dry-run` | print the plan, the site-file difference and the prune list; change nothing | n/a (no manifest) |
| `--allow-dirty` | deploy over uncommitted changes in a checkout | `allow_dirty`; `party.dirty`/`games.dirty` |
| `--allow-branch` | a Party commit that is not on `origin/main` | `allow_branch` |
| `--force-busy` | deploy while a game session is live | `force_busy` |
| `--skip-contract-check` | do not run `tools/contract_check.py` on the pair | `skip_contract_check`; `contract_check.status: skipped` |
| `--skip-smoke` | do not smoke; the last known good is not updated; nothing is pruned | `skip_smoke`; `smoke.status: skipped` |
| `--auto-rollback` | opt in: roll back a failed smoke, but only for checks that passed in a baseline taken before anything stopped | `auto_rollback` (only when it was effective) |
| `--no-auto-rollback` | accepted, does nothing (the default) | n/a |
| `--smoke-settle N` (`AVRANA_DEPLOY_SMOKE_SETTLE`) | seconds a failing smoke may still turn passing after the restart (default 90; 0 = one attempt) | not recorded |
| `--require-cert-names` | refuse when the certificate a 443 server block names does not cover its `server_name` | `nginx_site.cert_name_mismatch` lists the mismatches either way |
| `--finish` | close a run that died after the commit point, or a kept revision (journal `committed`, `post-commit-failed` or `smoke-failed`): smoke it, record the result, record the last known good only if it passed. It does not prune; the next passing deploy does | n/a |
| `--force` | with `--recover` only: also act on a journal that is not open (a revision kept on purpose); the default refuses | n/a |
| `--skip-nginx-site` | do not touch the nginx site file. **A host without nginx, or an emergency only**: when the live file differs from the deployed commit's, `/party/api/status` stays `degraded`, so the smoke fails (exit 2, revision kept) unless paired with `--skip-smoke` | `skip_nginx_site`; `nginx_site.status: skipped` |
| `--keep N` (`AVRANA_DEPLOY_KEEP`) | keep the newest N code releases, web releases and deploy backups (default 5, minimum 2) | not recorded |
| `--no-prune` | prune nothing | not recorded |
| `--status` | print the last known good, the journal and whether a run is live, dead or finished | n/a |
| `--rollback` | deploy the last known good (no SHAs). Not subject to the branch or contract checks | `rollback: manual` |
| `--recover` | after a run that DIED (journal open): converge on the last known good, re-applying every repository and restarting every unit. Refuses on a closed journal (a revision kept on purpose: smoke failed or skipped) and points to `--rollback`; on a finished, healthy run it does nothing (exit 0). Keeps the busy check (`--force-busy` to override) | `rollback: recover` |

`rollback` is `null` for an ordinary deployment and `auto` for the rollback the script ran after a failed smoke.
`nginx_site.status` is `installed`, `unchanged`, `skipped` or `not_managed` (the target commit has no
`avrana-party.nginx`), with the live file's `sha256`.

## What happened / what to do

**By exit code** (the command you typed returns the run's code):

| Exit | What happened | What to do |
|---|---|---|
| 0 | Deployed. Smoke passed (or was skipped by flag: then it is not the last known good) | Phone acceptance; [After](#after) |
| 1 | Refused before anything changed, **or** failed and the restore finished (checkouts, links, site file back; units started). The log names the step | Fix the stated reason and run again. Nothing is half-done. For `nginx -t` read the printed `MISSING PREREQUISITE` lines |
| 2 | Applied and kept, but something failed after the switch: smoke **failed** (including failures that already existed before the deploy), or a step after the commit point failed (the output says which; the journal ends `post-commit-failed`) | Read `smoke.txt` in the backup directory and `/party/api/status`. Fix forward, or `sudo bash .../deploy.sh --rollback` / the explicit SHAs it prints |
| 3 | Applied, smoke failed, **rolled back** to the last known good, whose smoke passed | The deployment failed and the party is safe on the old revision. Read the failed run's `smoke.txt` and `failed-manifest.json` in its backup directory |
| 4 | **A person is needed**: a restore step failed, a unit is down, or the rolled-back revision also fails smoke | `--status`, `journalctl -u <unit> -n 50`, fix the named cause, then `--rollback` (it re-applies the last known good completely; `--recover --force` if it refuses). The output lists the units that are not active |
| 129, 130, 143 | The run itself was signalled (SIGHUP, SIGINT, SIGTERM) **after** step 4, the commit point: nothing was rolled back. Before it the restore runs and the code is 1 or 4 | `--status`; the manifest says what is running; smoke is the open question: `--finish` |
| 130 (terminal) | You pressed Ctrl-C on the command you typed: it only *followed* the log and detached; the deployment continues | `--status`, `tail -f` the log named at the start |
| 137 / no exit code | The deployment was SIGKILLed or the machine lost power: no trap ran | the journal is open: `--status`, then `--recover` (before the commit point) or `--finish` (after it) |

**By journal phase** (`--status`, file `/var/backups/avrana-party/deploy.journal`). A phase that is not an end,
with no live process, means the run died (SIGKILL, power loss) and nothing restored it:

| Phase | Meaning | What to do |
|---|---|---|
| `started` | Backup taken; nothing changed yet, or only the site file | `--recover` (or just deploy again after `--recover`) |
| `site-installed` | New site file live; no service stopped | `--recover` |
| `stopped-services` | Units are stopped, checkouts not yet switched | `--recover` (starts them) |
| `switched` | Checkouts, releases, web build moved; units not (all) started | `--recover` |
| `restarted` | Units started with the new revision; manifest not written | `--recover` |
| `committed` | Manifest written; smoke result unknown (the run died, or is still smoking) | The new revision is applied. `sudo bash .../deploy.sh --finish` smokes it, records the result and, only if it passed, the last known good; or `--rollback` |
| `post-commit-failed` | Terminal. The revision is applied and kept, but a step after the switch failed (named in the output and the journal) | Fix the cause, then `--finish` to re-run smoke and record the result; or `--rollback` |
| `auto-rollback` | The automatic rollback was running when the run died | `--recover` |
| `smoke-passed` / `smoke-skipped` | A finished run | nothing |
| `smoke-failed` | Smoke failed, revision kept (exit 2) | fix the cause, then `--finish`; or `--rollback` |
| `auto-rolled-back` | Exit 3 | as exit 3 |
| `rolled-back` | The pre-commit restore finished (exit 1) | as exit 1 |
| `rollback-failed` | Exit 4 | as exit 4 |

### A run that died (or a run you must close)

```bash
sudo bash /home/cody/avrana-party/ops/deploy.sh --status      # the phase, and the last known good it would return to
sudo bash /home/cody/avrana-party/ops/deploy.sh --recover     # converge on the last known good
```

`--recover` only acts when the journal is open, i.e. the run really died before the commit point; on a closed
journal it refuses (`--force` overrides) because it would move a revision that was kept on purpose, and on a healthy
machine it is a no-op. After the commit point use `--finish` (smoke the applied revision and close the journal) or
`--rollback`. `--recover` is chosen over an automatic repair at the start of every run on purpose: a half-switched
machine is evidence, and an unrelated command should not silently rewrite it. Until it is run, every
ordinary deploy refuses with the phase it found. `--recover` re-applies everything (it does not trust
"already there"): both checkouts are checked out at the last known good, code releases and the web
build are re-linked, the site file is installed, and **all** units are restarted. Without a
last-known-good record it returns to the before-state the dead run wrote in its journal. It needs both
commits to still exist in the checkouts; if one is gone, deploy explicit SHAs.

### Which command next

One table, keyed on the journal phase `--status` shows and the exit code you saw. When the two disagree, trust the phase.

| Journal phase | Exit code seen | Run next |
|---|---|---|
| none, `smoke-passed` | 0 | nothing |
| `smoke-skipped` | 0 | nothing (it is not the last known good; deploy again without `--skip-smoke` to make it one) |
| `started`, `site-installed`, `stopped-services`, `switched`, `restarted`, `auto-rollback` and no live process | none, 137, or the connection was lost | `--recover` |
| `rolled-back` | 1 | nothing: everything was put back; fix the stated reason and deploy again |
| `committed`, no live process | none, 129, 130 (the run, not the terminal), 137, 143 | `--finish` (or `--rollback`) |
| `post-commit-failed` | 2 | fix the named step, then `--finish` (or `--rollback`) |
| `smoke-failed` | 2 | fix the cause, then `--finish`; or `--rollback` |
| `auto-rolled-back` | 3 | nothing: the last known good is running and its smoke passed |
| `rollback-failed` | 4 | fix what the output names, then `--rollback` (`--recover --force` if it refuses) |

### A deploy made while a check already fails for an unrelated reason

Example: the served certificate is `expiring` (or the web build was already stale). The deploy does not cause it
and cannot cure it, so smoke fails after the deploy too.

- Without `--auto-rollback` (the default) the run ends with exit 2, `smoke-failed`, the new revision running, and the
  command back printed.
- With `--auto-rollback` the baseline shows the check failing before, so the output says `PRE-EXISTING, NOT CAUSED BY
  THIS DEPLOY` and the exit code is 2; nothing is rolled back. (A check the baseline skipped says `NOT CHECKED BEFORE
  THE DEPLOY, FAILING AFTER` instead.)
- Such a deploy is **never the last known good** and **prunes nothing**: both need a passed smoke, and the failing
  check keeps it from passing.

```bash
sudo bash /home/cody/avrana-party/ops/deploy.sh --status      # confirm: phase smoke-failed, last known good unchanged
# fix the cause (renew the certificate, rebuild the web release, ...), then:
sudo bash /home/cody/avrana-party/ops/deploy.sh --finish      # smoke again; if it passes: manifest says passed, last known good recorded
sudo bash /home/cody/avrana-party/ops/deploy.sh --party <PARTY_SHA> --games <GAMES_SHA>   # the next passing deploy also prunes
sudo bash /home/cody/avrana-party/ops/deploy.sh --rollback    # or: decide to go back instead
```

### After a rollback: which smoke `--status` shows

A rollback (`--rollback`, or the automatic one) is a complete deployment of the last known good pair, so it has its own
smoke. `--status` and the manifest show **that** result, for the pair that is running: after a passing rollback the
journal ends `smoke-passed` (manual) or `auto-rolled-back` (automatic, exit 3) and `smoke: passed` belongs to the old
pair. The failed attempt is not lost: `last_attempt` in the manifest and in `/party/api/status` names the pair that failed,
its outcome (`rolled-back`) and its backup directory, whose `smoke.txt` and `failed-manifest.json` hold its result.
"Good" means every smoke check passed for that pair at that moment; it does not mean a phone was tried
([After](#after)).

### The first supervised run on the appliance

**No version of this script has run on the appliance.** Everything above is proved by the unit suite on Linux
runners and by reading, not by a deployment. So the first run is supervised by the owner:

1. `sudo bash /home/cody/avrana-party/ops/deploy.sh --party <SHA> --games <SHA> --dry-run`. Read the plan, the
   site-file difference summary (`live N lines, deployed M; +A -R`), the certificate-name `WARNING` and the prune list.
2. A normal run **without** `--auto-rollback` (the default): `sudo bash .../deploy.sh --party <SHA> --games <SHA>`.
3. Afterwards `sudo bash /home/cody/avrana-party/ops/deploy.sh --status`, then phone acceptance.

Add `--auto-rollback` only after one run has behaved as described.

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
and waiting for a manual `cp`. Both server blocks use `/etc/avrana-party/tls/current/fullchain.pem`, so
`nginx -t` passes on a Pi that serves HTTPS. The real prerequisite (read from the appliance 2026-10-12) is
that the served certificate's subjectAltName is only `DNS:party.avrana.net`: after the install the
`games.avrana.net` block serves a certificate for the wrong name. The deploy prints the `WARNING` and records
the name; Party stays deployable. Get a certificate with both names ([game-origin](game-origin.md)) before
anyone opens the game origin, or add `--require-cert-names` to refuse until then. If `nginx -t` rejects the new
file for any other reason the old file is put back, nothing was stopped and the exit code is 1; if `nginx -t`
already fails on the running configuration, the deploy refuses before changing anything. `--skip-nginx-site`
leaves the file alone and leaves status `degraded` until it is installed. The `sites-enabled` link is not managed; the
script warns when `/etc/nginx/sites-enabled/avrana-party` does not resolve to the file it wrote.

The manual sequence (first-time install, or `--skip-nginx-site`) is step 6 of
[party-core-deploy](party-core-deploy.md).

## Releases and backups accumulate; the newest N stay

After a **passed** smoke (never after a failure, a post-commit failure, a skipped smoke or `--no-prune`) the script keeps the
newest `N` (`--keep`, default 5, minimum 2) of: code releases `/opt/avrana-party/releases/<sha>` and
`/opt/avrana-party-games/releases/<sha>` (by modification time), web releases `.../web/releases/<stamp>-<sha12>`
and deploy backups `/var/backups/avrana-party/deploy-<stamp>` (by name). It never removes the running
release (what `current` points to), the previous one, the one being deployed, the last known good, or
the backup of the current or the last journalled run. Only a plain directory whose name has exactly the
expected shape is a candidate, and its resolved path must be exactly `<directory>/<name>`: links, odd
names, `.new.*` build leftovers and a `releases` directory that is itself a link are skipped and
named in the output. The same pass removes build leftovers (`.new.*` in the code-release directories, `.build.*` in the web
releases, `deploy.journal.tmp.*`) once an hour old, and run logs `deploy-*.log` beyond the newest N. `--dry-run` lists what would be removed. The web build uses the same number
(`AVRANA_WEB_KEEP`, passed on by the script, which prunes web releases itself after smoke instead of at
install time). A standalone `install-party-web.sh` still prunes its own releases, to the same default.

## After

```bash
curl -s https://party.avrana.net/party/api/status | python3 -m json.tool   # from the Party LAN
```

`summary.state` should be `ok`; `party.deployed_sha` and `games.deployed_sha` are the build;
`last_known_good` names the pair the next failure returns to; `nginx_site` is `match`; `last_attempt` says how the
last run ended (`ok`, or `smoke-failed-kept`, `rolled-back`, ... with a `summary.notes` entry: after a rollback the
manifest names the pair that is running, not the one that failed).
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
(`/etc/nginx/sites-available/avrana-party`), `AVRANA_NGINX_ENABLED`,
`AVRANA_LAST_KNOWN_GOOD` (default: `last-known-good.json` beside the manifest), `AVRANA_DEPLOY_LOCK`,
`AVRANA_DEPLOY_KEEP`, `AVRANA_DEPLOY_SMOKE_SETTLE`, `AVRANA_DEPLOY_DETACH=0`, `AVRANA_DEPLOY_PYTHON` (the
interpreter for the contract checker). `AVRANA_SYSTEMCTL`, `AVRANA_NGINX`, `AVRANA_OPENSSL`, `AVRANA_DEPLOY_SMOKE`,
`AVRANA_DEPLOY_UNPRIVILEGED`, `AVRANA_DEPLOY_TEST_HOOK_DIR`, `AVRANA_DEPLOY_FAIL_STEP`, `AVRANA_DEPLOY_UNIT_GRACE`
and `AVRANA_DEPLOY_SMOKE_PAUSE` (the production waits of 1 s per restarted unit and 2 s before the first smoke) exist only for
`tests/unit/test_deploy_script.py`: they are honoured only with `AVRANA_DEPLOY_TESTING=1` on a scratch root (none of the
production paths in use), and anywhere else their presence is a refusal naming the variable. The script's own
re-executions use hidden `--internal-*` arguments, not environment variables. `--internal-nested` and
`--internal-rollback-kind` refuse to be typed by hand; `--internal-detached` only means "do not detach again" and is
harmless when typed. A real run needs root (the
services, the web root and the site file); a run without it refuses before touching anything.
