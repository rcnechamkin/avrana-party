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

| Copy | Where | State (2026-09-24) |
|---|---|---|
| GitHub | `rcnechamkin/avrana-party-games` | **does not exist yet** (owner creates it; push `main` only) |
| laptop backup (bare) | `~/avrana-party-games.git` | `main` @ `2cf4831`; `playtest-readiness` @ `6d795a7` (reconnect fix, lifecycle log lines, the Pi's `ops/lab` helpers; 2026-09-24); also `abandoned/classic-diplomacy` (**never push or use**) and old `agent/*` branches |
| Pi dev clone | `~/avrana-lab/avrana-party-games` | `main` @ `2cf4831` (= laptop); remote `upstream` = BEACNpool LAN Games; also has `playtest-readiness`, checked out as the worktree **`~/avrana-lab/wt/playtest`** (use it for the playtest); old `agent/*` worktrees under `~/avrana-lab/wt/`. Runs BLUFF on port 8196 when started |
| laptop working clone | any scratch clone of the bare backup | edit on a branch; this separate games fork has no GitHub Cloud workflow yet |
| **live** LAN Games | Pi `/home/cody/LAN-Games` | upstream `main` @ `5da1764` (retired upstream); service `avranaparty-games`, port 8096. **Never edited.** |

AGPL/Diplomacy: the abandoned `diplomacy/diplomacy` engine work exists only on the fork's
`abandoned/classic-diplomacy` branch (and `~/avrana-lab/diplomacy-spike` on the Pi). `main` and
`playtest-readiness` do not contain it.

## Branches of this repository

| Branch | Where | What | Merge status |
|---|---|---|---|
| `main` | GitHub + Pi production | **production** | — (only the owner merges into it) |
| `docs/party-platform` | GitHub | source of current docs copied to `main`; also has historical raw measurement evidence and network tools | retained separately; raw evidence and tools not on `main` |
| `experiment/party-sim` | GitHub | `experiments/`: party model, viewport geometry, Personal Viewports PoC | not merged |
| `experiment/party-service` | GitHub + Pi worktree `~/avrana-lab/party-svc` | party service + device identity + dev front door, manifest v0, **service-game launcher (PS1) + seat tickets v1** (branched from `experiment/party-sim` @ `7d4fdfd`, so it lacks the later shared-WebRTC viewport commit) | not merged |
| `experiment/ps1-title-profiles` | GitHub + Pi dev/test checkout | **current PS1 line**: title profiles, token-in-hello, explicit Leave, supervised runs, `--capture`, party mode (seat tickets, return home), `--viewports` (built on `ps1-emulation`) | not merged |
| `ps1-emulation` | GitHub | older PS1 shared-stream base (superseded by `experiment/ps1-title-profiles`) | not merged |
| `fix/arcade-ap-interface` | GitHub (from 2026-09-24) | arcade `/stats` path label after the Wi-Fi change (off `main`) | not merged, not deployed |
| `docs/current-state` | laptop only | an old docs commit **already contained in `main`** | safe to delete (`git branch -d`) |

## Services and ports on the Pi

| Port | Service (systemd) | Code |
|---|---|---|
| 80 | nginx (`/etc/nginx/sites-available/avrana-party`) | `avrana-party.nginx` |
| 8096 | LAN Games (`avranaparty-games`) | `/home/cody/LAN-Games` |
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
