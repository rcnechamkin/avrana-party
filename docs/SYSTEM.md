# System map: machines, repositories, branches, runtime paths

The **canonical answer to deployed state and topology**. Production rows reconciled 2026-10-12
against the read-only capture in [the 2026-10-12 baseline](findings/2026-10-12-deployed-baseline.md)
(the status endpoint's deployment manifest, plus non-root shell reads); no new Pi audit, deployment or
restart was performed. The latest production evidence is that capture: Party `c59f1c8`, Games `a448972`,
deployed 2026-10-06 and read 2026-10-12. Rows it did not touch (the machines, the dev/test checkouts, the
branch inventory) keep their earlier dates. Older local/experiment inventories below are explicitly dated
snapshots, not claims of current branch checkout state.
If you change where something lives, update this file with deployment evidence.

**Accepted direction is not deployed state (note added 2026-10-02).** ADRs
[0012](adr/0012-limited-mode-party-survives-https-loss.md),
[0013](adr/0013-party-and-game-browser-origins.md) and
[0014](adr/0014-native-games-isolated-lan-games-retired.md) accept Limited Mode, a separate game
origin, isolated native-game processes and the retirement of LAN Games as an Avrana runtime. None
of that is deployed. This file intentionally continues to describe the runtime that is actually
on the Pi — one HTTPS origin, HTTPS-only `/party/`, the LAN Games fork on port 8096 — until each
migration is performed and verified with dated evidence.

## Source versus verified production

Three different things, never to be merged in the reader's head: what is **deployed** (running on the Pi),
what is on **main** (merged source, not necessarily deployed), and what is **unmerged** (open pull requests
and branches).

| Repository | Deployed (Pi, manifest read 2026-10-12) | `origin/main` (2026-10-12) | Unmerged |
|---|---|---|---|
| Party | `c59f1c8` (checkout and `/party/` web release build `c59f1c819de1`; clean, no mismatch). Deployed 2026-10-06T21:10:48Z by `ops/deploy.sh`, smoke passed | `14a0278` plus the merges of #86 and this document's PR #113; 157 commits ahead of `c59f1c8` at `14a0278`. PRs #85, #86 and #108 to #111 merged on 2026-10-12, after the [baseline](findings/2026-10-12-deployed-baseline.md) was written | Draft PRs #106, #107 and #112 and the branch `fix/avr-33-session-recovery`. PR #114 (deploy hardening: `ops/deploy.sh` installs the nginx site, journals, recovers and rolls back) merged after the others on 2026-10-12; that script has never run on the Pi |
| Games | `a448972` (clean, no mismatch) | `282c620` (Games #61 merged 2026-10-12) | none |

**Main is ahead of production, and unmerged work is ahead of main.** Main's extra commits include native
games (`provision-game`, `prepare-native-games`, native Checkers), the game origin runbook and nginx block,
the service-user migration tooling, the experimental `.avrgame` package installer and the Party/Games contract
work. **None of that is running on the Pi**: the installed nginx site equals the deployed checkout's file, the
services still run as `cody`, and no native game, game origin or package is installed. A merged pull request is
not a release. The ADR 0011 console model **is** in the deployed revision (`ff32bb4`, the merge of Party PR #34,
is an ancestor of `c59f1c8`); its real-phone proof belongs to AVR-212 and is still missing. Unmerged work has no
phone or Pi evidence; the baseline lists each branch and says what it changes.

Earlier production milestones are in the progression list below. The deployment finding of
[2026-09-29](findings/2026-09-29-avr129-deploy.md) verified Party `956b968` and Games `c6d7b52` server-side:
Party Core running (AVR-51), authoritative navigation (AVR-128), Gauntlet II lifecycle (AVR-134), BLUFF Play or
Watch with host-only Start (AVR-129 / ADR 0010). Those checks do not establish physical phone acceptance, and
no deployment finding records the later deployments (see the progression list).
GitHub main supplies code/tests; ADRs and design docs supply contracts; Linear supplies live work
sequencing. Do not silently substitute a newer main SHA for a deployed revision.

## Machines

| Machine | Role | Reach it | Edit code here? |
|---|---|---|---|
| **Laptop** (Windows) | local checkout and LAN browser tests | — | yes |
| **Claude Code Cloud** | branch development and offline tests in an isolated checkout | GitHub | yes, on branches |
| **GitHub** `rcnechamkin/avrana-party` | canonical history of this repo | `origin` | via push (never force) |
| **Pi `party`** (Raspberry Pi 4, Debian 13, user `cody`) | the appliance: production services + a dev/test area | `ssh party` → `10.0.0.142` (eth0) | **no** (deploy/test target) |
| **Mini-PC `avrana`** (`10.0.0.218`) | home infrastructure: BookStack (stale docs), Beszel telemetry hub | `ssh avrana` | no (not part of this project's code) |

Networking of the Pi: `docs/runbooks/network.md`. Observed 2026-10-12: the access point is on channel 36
(5180 MHz, 20 MHz), not the 149 recorded on 2026-09-24
([baseline](findings/2026-10-12-deployed-baseline.md)). What a clean target would need to become this
appliance is enumerated in `deploy/appliance-inventory.json` and
[the rebuild runbook](runbooks/rebuild.md) (AVR-32): a proposed procedure that has not been run
on any device, with the facts this file does not record listed there as unknown.

## Repositories and checkouts

### This repository (`avrana-party`)

| Checkout | Machine / path | Branch | Purpose |
|---|---|---|---|
| main checkout | laptop `~/Projects/avrana-party` | issue-scoped branch | editing; has `node_modules` for Playwright |
| worktrees | laptop `~/Projects/avrana-party.wt-*` (`wt-platform`, `wt-sim`, `wt-svc`, `wt-fix`) | one branch each | parallel work without switching branches |
| **production** | Pi `/home/cody/avrana-party` | at `c59f1c8` (manifest `checkout_sha`, clean, 2026-10-12) | **live**: nginx site, arcade service code. An owner-approved deployment selects an exact reviewed commit and fast-forwards here; source synchronization alone is not a release. **Never edit or commit here.** Pulling changes live arcade code (a restart applies it; ask first). |
| dev/test | Pi `~/avrana-lab/avrana-party-docs` | feature branch (2026-09-24 inventory: `experiment/ps1-title-profiles`) | test feature branches on the Pi (`git fetch && git merge --ff-only origin/<branch>`); never develop here. 2026-09-24 inventory recorded an old rescued-handoff stash; not re-audited |
| dev/test worktree | Pi `~/avrana-lab/party-svc` (worktree of the dev/test checkout) | `experiment/party-service` | runs the dev front door on 8190 (`--ps1 ~/avrana-lab/avrana-party-docs/ps1`); `experiments/party-service/dev-data/` holds runtime logs (git-ignored) |

The laptop also has a git remote `party-dev` → the Pi dev/test checkout (fetch only in practice).

### The games fork: Avrana Party Games (LAN Games + BLUFF) — a separate repository

| Copy | Where | State (local copies: 2026-09-24 inventory; source/production: see revision table above) |
|---|---|---|
| GitHub | `rcnechamkin/avrana-party-games` (private) | canonical source; `main` @ `282c620` (2026-10-12; was `0b4e9d2` on 2026-10-01); work on issue-scoped branches with PRs |
| laptop backup (bare) | `~/avrana-party-games.git` | `main` @ `2cf4831`; `playtest-readiness` @ `6d795a7` (reconnect fix, lifecycle log lines, the Pi's `ops/lab` helpers; 2026-09-24); also `abandoned/classic-diplomacy` (**never push or use**) and old `agent/*` branches |
| Pi dev clone | `~/avrana-lab/avrana-party-games` | `main` @ `2cf4831` (= laptop); remote `upstream` = BEACNpool LAN Games; also has `playtest-readiness`, checked out as the worktree **`~/avrana-lab/wt/playtest`** (historical playtest worktree; current scope comes from Linear); old `agent/*` worktrees under `~/avrana-lab/wt/`. Runs BLUFF on port 8196 when started |
| laptop working clone | any scratch clone of the bare backup | edit on a branch; the separate games fork has independent GitHub CI |
| **production** games | Pi `/home/cody/avrana-party-games` | at `a448972` (manifest `checkout_sha`, clean, 2026-10-12); earlier `c6d7b52` (since the 2026-09-29 16:33 PDT restart, AVR-129; before: `03df5ae`) and `0b4e9d2` (read 2026-10-02); first deployed at `9696524` on 2026-09-27. Service `avranaparty-games` (port 8096) via the drop-ins `avrana-fork.conf` and `avrana-party-session.conf` (Party sessions on, AVR-51; `docs/findings/2026-09-29-party-core-deploy.md`), using the old venv (the drop-ins and venv were not re-read on 2026-10-12) |
| upstream LAN Games (rollback) | Pi `/home/cody/LAN-Games` | upstream `main` @ `5da1764` (retired upstream); no longer served; removing the drop-in returns to it. **Never edited.** |

AGPL/Diplomacy: the abandoned `diplomacy/diplomacy` engine work exists only on the fork's
`abandoned/classic-diplomacy` branch (and `~/avrana-lab/diplomacy-spike` on the Pi). `main` and
`playtest-readiness` do not contain it.

## Branch roles and historical inventories

The [retention inventory](branches.json) records the later GitHub branch audit. The rows below
retain their dated historical context; neither inventory assigns work or establishes deployment.

Production progression is historical evidence, not an instruction to synchronize to main:

- 2026-09-27: `7581baa`, shell and arcade AP fix; Party Core was present as source but inactive
  ([finding](findings/2026-09-27-production-deploy.md)).
- 2026-09-28: Party `15f6322`, BLUFF listed in Party Home; Games `c6199be`.
- 2026-09-29: Party Core deployed and restart/rollback checked at `6bd5af4` / `b345b6d`,
  Games `eeedb19` ([finding](findings/2026-09-29-party-core-deploy.md)).
- Later that day: Party `0e97c2e`, Games `03df5ae` for AVR-128/134
  ([finding](findings/2026-09-29-avr128-134-deploy.md)), then Party `956b968`, Games `c6d7b52`
  for AVR-129 ([finding](findings/2026-09-29-avr129-deploy.md)).
- 2026-09-29 evening to 2026-10-02: the checkout stood at Party `a32b7b4` (merge of PR #29, 20:00 PDT) and
  Games `0b4e9d2` when the AVR-130 finding read the Pi; **no finding records the deployment that put them
  there**. That finding ([2026-10-02-avr130-deploy](findings/2026-10-02-avr130-deploy.md)) stages the next
  deployment and records no after-state.
- 2026-10-06: Party `c59f1c8`, Games `a448972`, deployed 2026-10-06T21:10:48Z by `ops/deploy.sh`, smoke passed
  at 21:10:51Z, restarting `avrana-party-core`, `avranaparty-arcade` and `avranaparty-games`. Evidence: the
  deployment manifest as reported by `/party/api/status` on 2026-10-12
  ([baseline](findings/2026-10-12-deployed-baseline.md)). **No dated deployment finding exists** for the
  deployments between 2026-09-29 and 2026-10-06, nor for this one.
- 2026-10-09 22:59 PDT: an unrecorded reboot, observed after the fact (baseline); all units were active
  afterwards with Ethernet present. Not an offline-boot proof.

Party Core `avrana-party-core` runs at 127.0.0.1:8191 behind nginx `/party/api/`.
BLUFF is granted and listed in Party Home. Experiment rows below retain the 2026-09-27 branch
inventory; the source revision table above governs current main observations.

| Branch | Where | What | Status |
|---|---|---|---|
| `main` | GitHub + Pi production | current source/code/tests; the Pi holds a separately deployed revision | canonical |
| `docs/party-platform` | GitHub | history of the docs now on `main`, plus raw power-measurement evidence that stays out of `main` | park (archive) |
| `experiment/party-service` | GitHub + Pi worktree `~/avrana-lab/party-svc` | party service, device identity, membership, host, presence, lifecycle, manifest v0, service-game launcher (PS1) + seat tickets v1, Party Home reconnect (includes the deleted `fix/party-home-reconnect`) | park: source evidence for Party Core, **not** for a wholesale merge |
| `experiment/party-sim` | GitHub | `experiments/`: party lifecycle model, viewport geometry, Personal Viewports PoC | park (research) |
| `experiment/ps1-title-profiles` | GitHub + Pi dev/test checkout | current PS1 line: title profiles, token-in-hello, Leave, supervised runs, party mode, `--viewports` | park (R&D) |
| `ps1-emulation` | GitHub | older PS1 shared-stream base (superseded by `experiment/ps1-title-profiles`) | park (history) |

## Services and ports on the Pi

| Port | Service (systemd) | Code |
|---|---|---|
| 80 | nginx (`/etc/nginx/sites-available/avrana-party`): captive probes, LAN Games, `/arcade/` | `avrana-party.nginx` |
| 443 | nginx, `party.avrana.net` (Let's Encrypt; `/etc/avrana-party/tls/current`): LAN Games, `/arcade/`; `/party/` Full Mode shell (static, `/var/www/avrana-party/web/current` = build `c59f1c819de1` per the 2026-10-12 manifest; earlier `956b968` (2026-09-29 16:32 PDT), `0e97c2e`, `6bd5af4`); `/party/api/` → Party Core 127.0.0.1:8191 | `avrana-party.nginx`, `ops/` |
| 8096 | games: the Avrana Party Games fork (`avranaparty-games` + drop-in `avrana-fork.conf`) | `/home/cody/avrana-party-games` @ `a448972` (upstream `/home/cody/LAN-Games` kept for rollback) |
| 127.0.0.1:8191 | Party Core (`avrana-party-core`): membership, host and session authority behind HTTPS `/party/api/` | `avrana/party/`, production `c59f1c8` |
| 127.0.0.1:8097 | arcade (`avranaparty-arcade`): RetroArch + Xvfb + GStreamer | `arcade/` from the production checkout |
| 127.0.0.1:8098 | arcade control (**LIVE** since 2026-09-29, AVR-134): the Party's signed launch/end start and stop RetroArch + the encode (ADR 0009); drop-in `/etc/systemd/system/avranaparty-arcade.service.d/avrana-party-session.conf`; never proxied. The arcade idles (no RetroArch) until the Party Host starts Gauntlet II | `arcade/stream.py`, `avrana/party/managed.py` |
| 10.42.0.1:53, 67 | NetworkManager's dnsmasq for the AP | NM + `avrana-captive.conf` |
| wlan0 (radio) | Party AP "Avrana Party", 5 GHz **channel 36**, 20 MHz, read on the Pi 2026-10-07 (the owner changed it from 149 on 2026-10-06 after a measured comparison; policy and evidence are in the network runbook) | NM profile "Avrana Party Internal"; `docs/runbooks/network.md` (Channel policy) |
| 5353 | avahi (`party.local`) | system |
| 5201 | iperf3 | system |
| 45876 | beszel-agent | `telemetry/` |
| 22 | sshd | system |
| 8196 (when started) | BLUFF dev server | games fork dev clone |
| 8198 (when started) | PS1 stream: standalone (`ps1/tools/supervised-run.sh`, binds 10.42.0.1) or started by the front door (binds 127.0.0.1 only) | `ps1/` on the dev/test checkout |
| 8190 (when started) | dev front door + party service; proxies `/ps1/<title>/` to the running PS1 | `experiments/party-service` (Pi worktree `~/avrana-lab/party-svc`) |

### Who the services run as (observed 2026-10-03; user re-confirmed 2026-10-12)

On 2026-10-12 `systemctl show avrana-party-core` still reported `User=cody`, `Restart=on-failure`
([baseline](findings/2026-10-12-deployed-baseline.md)): the ADR 0016 migration has not been applied. The
rest of this section is the 2026-10-03 reading.

`avrana-party-core`, `avranaparty-games` and `avranaparty-arcade` all run as **`cody`**, the
owner's SSH account, which is in `sudo` and owns both source checkouts. The session keys in
`/etc/avrana-party/game-keys/` are `0600 cody` in a `0700 cody` directory (`bluff.key`,
`arcade-gauntlet2.key`; there is no `expo.key` on the Pi). Only Party Core's unit has systemd
hardening. The games server listens on `0.0.0.0:8096`: the loopback default merged in Games PR
#18 is not deployed.

Consequences, so nothing here is read as isolation: every service can read every game's key and
every other service's state, can rewrite the code the others run, and can reach every loopback
port. A `0600` key and a loopback-only route protect against phones and the network, not against
another local service. The intended boundary is
[ADR 0016](adr/0016-service-identities-and-local-trust-boundary.md) (accepted, not implemented).
`python3 -m avrana.ops.boundary` reports each of its rules on a host, read-only; on this date the
Pi met 6 of the 25 phase-1 rules (`tests/fixtures/boundary/pi-2026-10-03.json`).

## Runtime-only paths (never in Git)

| Path (Pi) | What |
|---|---|
| `/var/log/avrana/pi-throttle.jsonl` | minute power telemetry. The systemd journal is **volatile**: effective `Storage=volatile` (the Raspberry Pi OS drop-in `40-rpi-volatile-storage.conf`; Avrana's `avrana.conf` bounds sizes and leaves `Storage=` alone), one boot in `journalctl --list-boots`, 11.4M, observed 2026-10-12 ([baseline](findings/2026-10-12-deployed-baseline.md)); lost at reboot. A deliberate reboot proof is not run |
| `~/avrana-lab/power-watch/` | power-test samples; summarize findings in docs, keep raw samples outside Git |
| `~/avrana-lab/playtest/` | playtest logs (runbook) |
| `/srv/…` | ROMs and BIOS (read-only; **never** copied or committed) |
| `/etc/NetworkManager/system-connections/` | Wi-Fi profiles incl. passwords (owner only; never read into chat or Git) |
| `/var/lib/NetworkManager/dnsmasq-wlan0.leases` | DHCP leases (phones' addresses) |
| `experiments/party-service/dev-data/` | dev device-token hashes (git-ignored) |
| `/var/www/avrana-party/web/{releases,current}` | **live** Full Mode shell releases, built by `ops/install-party-web.sh` from a clean checkout (static, root-owned; the newest five kept) |
| `.venv/`, `node_modules/`, `__pycache__/`, `test-results/` | tooling caches |

## Compare and sync safely (owner-approved deployment only)

```bash
# 1. Compare production with GitHub main; a lag is legitimate, not permission to deploy
ssh party 'cd ~/avrana-party && git fetch -q && git status -sb && git rev-parse HEAD origin/main'
# 2. live config = repo?
ssh party 'cmp /etc/nginx/sites-available/avrana-party ~/avrana-party/avrana-party.nginx && cmp /etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf ~/avrana-party/avrana-captive.conf && echo same'
# 3. games fork: Pi dev clone vs laptop backup (hash only; nothing is copied)
ssh party 'git -C ~/avrana-lab/avrana-party-games rev-parse main'; git -C ~/avrana-party-games.git rev-parse main
# 4. any Pi-only edits?  (must be empty)
ssh party 'git -C ~/avrana-party status --porcelain; git -C ~/avrana-lab/avrana-party-games status --porcelain'
```

Direction of travel is always **development branch → GitHub → Pi**: edit and commit locally or in
Claude Code Cloud, push, review, then fast-forward production or a separate dev/test checkout
on the Pi. If a Pi checkout ever has legitimate uncommitted work, copy it to a development
checkout (e.g. `git diff > patch`, `scp`), commit it
there on a branch, and reset nothing on the Pi until the owner agrees. Never sync credentials,
ROMs, logs, telemetry, databases, caches or `/etc` into Git.
