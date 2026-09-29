# System map: machines, repositories, branches, runtime paths

The **canonical answer to "what lives where"**. Production source revisions were audited on
2026-09-25. Some experiment and games-fork details below are from the 2026-09-24 inventory.
If you change where something lives, update this file in the same commit.

## Machines

| Machine | Role | Reach it | Edit code here? |
|---|---|---|---|
| **Laptop** (Windows) | local checkout and LAN browser tests | — | yes |
| **Claude Code Cloud** | branch development and offline tests in an isolated checkout | GitHub | yes, on branches |
| **GitHub** `rcnechamkin/avrana-party` | canonical history of this repo | `origin` | via push (never force) |
| **Pi `party`** (Raspberry Pi 4, Debian 13, user `cody`) | the appliance: production services + a dev/test area | `ssh party` → `10.0.0.142` (eth0) | **no** (deploy/test target) |
| **Mini-PC `avrana`** (`10.0.0.218`) | home infrastructure: BookStack (stale docs), Beszel telemetry hub | `ssh avrana` | no (not part of this project's code) |

Networking of the Pi: `docs/runbooks/network.md`.

## Repositories and checkouts

### This repository (`avrana-party`)

| Checkout | Machine / path | Branch | Purpose |
|---|---|---|---|
| main checkout | laptop `~/Projects/avrana-party` | varies (was `experiment/ps1-title-profiles`) | editing; has `node_modules` for Playwright |
| worktrees | laptop `~/Projects/avrana-party.wt-*` (`wt-platform`, `wt-sim`, `wt-svc`, `wt-fix`) | one branch each | parallel work without switching branches |
| **production** | Pi `/home/cody/avrana-party` | `main` (tracks `origin/main`) | **live**: nginx site, arcade service code. Deploy = `git pull --ff-only` here. **Never edit or commit here.** Pulling changes live arcade code (a restart applies it; ask first). |
| dev/test | Pi `~/avrana-lab/avrana-party-docs` | a feature branch (`experiment/ps1-title-profiles` since 2026-09-24 night) | test feature branches on the Pi (`git fetch && git merge --ff-only origin/<branch>`); never develop here. Holds one old stash (a rescued handoff edit already in history; safe to drop) |

| dev/test worktree | Pi `~/avrana-lab/party-svc` (worktree of the dev/test checkout) | `experiment/party-service` | runs the dev front door on 8190 (`--ps1 ~/avrana-lab/avrana-party-docs/ps1`); `experiments/party-service/dev-data/` holds runtime logs (git-ignored) |

The laptop also has a git remote `party-dev` → the Pi dev/test checkout (fetch only in practice).

### The games fork: Avrana Party Games (LAN Games + BLUFF) — a separate repository

| Copy | Where | State (2026-09-24; GitHub and production rows 2026-09-28) |
|---|---|---|
| GitHub | `rcnechamkin/avrana-party-games` (private) | canonical; `main` @ `eeedb19` (2026-09-29, games PR #10); work on `fix/*` branches with PRs |
| laptop backup (bare) | `~/avrana-party-games.git` | `main` @ `2cf4831`; `playtest-readiness` @ `6d795a7` (reconnect fix, lifecycle log lines, the Pi's `ops/lab` helpers; 2026-09-24); also `abandoned/classic-diplomacy` (**never push or use**) and old `agent/*` branches |
| Pi dev clone | `~/avrana-lab/avrana-party-games` | `main` @ `2cf4831` (= laptop); remote `upstream` = BEACNpool LAN Games; also has `playtest-readiness`, checked out as the worktree **`~/avrana-lab/wt/playtest`** (use it for the playtest); old `agent/*` worktrees under `~/avrana-lab/wt/`. Runs BLUFF on port 8196 when started |
| laptop working clone | any scratch clone of the bare backup | edit on a branch; this separate games fork has no GitHub Cloud workflow yet |
| **production** games | Pi `/home/cody/avrana-party-games` | fork `main` @ `eeedb19` (detached checkout) since the 2026-09-29 11:37 PDT restart; first deployed at `9696524` on 2026-09-27. Service `avranaparty-games` (port 8096) via the drop-ins `avrana-fork.conf` and `avrana-party-session.conf` (Party sessions on, AVR-51; `docs/findings/2026-09-29-party-core-deploy.md`), using the old venv |
| upstream LAN Games (rollback) | Pi `/home/cody/LAN-Games` | upstream `main` @ `5da1764` (retired upstream); no longer served; removing the drop-in returns to it. **Never edited.** |

AGPL/Diplomacy: the abandoned `diplomacy/diplomacy` engine work exists only on the fork's
`abandoned/classic-diplomacy` branch (and `~/avrana-lab/diplomacy-spike` on the Pi). `main` and
`playtest-readiness` do not contain it.

## Branches of this repository

Reconciled 2026-09-27 (`docs/findings/2026-09-27-m0-git-baseline.md`). Branches
fully contained in `main` were deleted; nothing below is deployed unless it says so. Merged the same
day (PRs #8–#13): the arcade AP fix, the M0 reconcile, the BLUFF-seam finding, the games deploy
runbook, Party Core v0 and the session protocol v0. Production was fast-forwarded to `7581baa` the
same evening (shell and arcade AP fix live); Party Core v0 and the session protocol are in that
checkout but **no Party service runs** (`docs/findings/2026-09-27-production-deploy.md`).
On 2026-09-28 the games fork went to `c6199be` and production was fast-forwarded to `3724b34`, then
to `15f6322` (PR #20, AVR-91). On 2026-09-29 production went to `6bd5af4` with games `eeedb19`: Party Core `avrana-party-core`
(127.0.0.1:8191) runs behind nginx `/party/api/`, and `/party/` serves the release built from `6bd5af4` (`docs/findings/2026-09-29-party-core-deploy.md`). BLUFF is granted and listed in Party Home, and still no
Party service runs (`docs/findings/2026-09-28-bluff-party-home.md`).

| Branch | Where | What | Status |
|---|---|---|---|
| `main` | GitHub + Pi production | **production** source (the Pi checkout may lag it; a fast-forward there is an owner step) | canonical |
| `docs/party-platform` | GitHub | history of the docs now on `main`, plus raw power-measurement evidence that stays out of `main` | park (archive) |
| `experiment/party-service` | GitHub + Pi worktree `~/avrana-lab/party-svc` | party service, device identity, membership, host, presence, lifecycle, manifest v0, service-game launcher (PS1) + seat tickets v1, Party Home reconnect (includes the deleted `fix/party-home-reconnect`) | park: source evidence for Party Core, **not** for a wholesale merge |
| `experiment/party-sim` | GitHub | `experiments/`: party lifecycle model, viewport geometry, Personal Viewports PoC | park (research) |
| `experiment/ps1-title-profiles` | GitHub + Pi dev/test checkout | current PS1 line: title profiles, token-in-hello, Leave, supervised runs, party mode, `--viewports` | park (R&D) |
| `ps1-emulation` | GitHub | older PS1 shared-stream base (superseded by `experiment/ps1-title-profiles`) | park (history) |

## Services and ports on the Pi

| Port | Service (systemd) | Code |
|---|---|---|
| 80 | nginx (`/etc/nginx/sites-available/avrana-party`): captive probes, LAN Games, `/arcade/` | `avrana-party.nginx` |
| 443 | nginx, `party.avrana.net` (Let's Encrypt; `/etc/avrana-party/tls/current`): LAN Games, `/arcade/`; `/party/` Full Mode shell (static, `/var/www/avrana-party/web/current` = release `6bd5af4` since 2026-09-29); `/party/api/` → Party Core 127.0.0.1:8191 | `avrana-party.nginx`, `ops/` |
| 8096 | games: the Avrana Party Games fork (`avranaparty-games` + drop-in `avrana-fork.conf`) | `/home/cody/avrana-party-games` @ `eeedb19` (upstream `/home/cody/LAN-Games` kept for rollback) |
| 127.0.0.1:8097 | arcade (`avranaparty-arcade`): RetroArch + Xvfb + GStreamer | `arcade/` from the production checkout |
| 10.42.0.1:53, 67 | NetworkManager's dnsmasq for the AP | NM + `avrana-captive.conf` |
| 5353 | avahi (`party.local`) | system |
| 5201 | iperf3 | system |
| 45876 | beszel-agent | `telemetry/` |
| 22 | sshd | system |
| 8196 (when started) | BLUFF dev server | games fork dev clone |
| 8198 (when started) | PS1 stream: standalone (`ps1/tools/supervised-run.sh`, binds 10.42.0.1) or started by the front door (binds 127.0.0.1 only) | `ps1/` on the dev/test checkout |
| 8190 (when started) | dev front door + party service; proxies `/ps1/<title>/` to the running PS1 | `experiments/party-service` (Pi worktree `~/avrana-lab/party-svc`) |

## Runtime-only paths (never in Git)

| Path (Pi) | What |
|---|---|
| `/var/log/avrana/pi-throttle.jsonl` | minute power telemetry (the journal itself is volatile: lost at reboot) |
| `~/avrana-lab/power-watch/` | power-test samples; summarize findings in docs, keep raw samples outside Git |
| `~/avrana-lab/playtest/` | playtest logs (runbook) |
| `/srv/…` | ROMs and BIOS (read-only; **never** copied or committed) |
| `/etc/NetworkManager/system-connections/` | Wi-Fi profiles incl. passwords (owner only; never read into chat or Git) |
| `/var/lib/NetworkManager/dnsmasq-wlan0.leases` | DHCP leases (phones' addresses) |
| `experiments/party-service/dev-data/` | dev device-token hashes (git-ignored) |
| `/var/www/avrana-party/web/{releases,current}` | **proposed** Full Mode shell releases, built by `ops/install-party-web.sh` from a clean checkout (static, root-owned; the newest five kept) |
| `.venv/`, `node_modules/`, `__pycache__/`, `test-results/` | tooling caches |

## Compare and sync safely (next time)

```bash
# 1. production checkout = GitHub main?  (clean, same hash)
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
