# CLAUDE.md

> **STALE ON THIS BRANCH — read the docs branch first.** This is a code branch; its repo-level docs
> (`CLAUDE.md`, `CLAUDE-HANDOFF.md`, `docs/`) are older copies. Current truth: branch
> **`docs/party-platform`** (`git show origin/docs/party-platform:CLAUDE.md`, `…:docs/ROADMAP.md`;
> laptop worktree `../avrana-party.wt-platform`). In particular: power is **not** blocking PS1 any
> more (2026-09-24; the limit is CPU), and the party AP is **wlan0 / 10.42.0.1** with eth0
> `10.0.0.142` upstream (no wlan1). Code docs for this branch's own folders stay current
> (`ps1/README.md`, `experiments/*/README.md`).

## Environment

- **This laptop** is the primary dev machine. This local Git repo is where code is normally edited.
- **GitHub `origin`** is the canonical remote and history.
- **SSH `party`** is the Raspberry Pi running Avrana Party. It is the deployment and test target, not the place to develop.
- **SSH `avrana`** is the mini-PC hosting infrastructure (BookStack, Beszel, etc.).
- **Documentation source of truth (since 2026-09-22): this repository.** The BookStack API/MCP integration is unreliable, so record decisions, findings and progress in the repo (`docs/ROADMAP.md`, `docs/findings/`, `docs/adr/`, `CLAUDE-HANDOFF.md`). **Do not try to repair BookStack or its MCP unless the owner explicitly asks**, and never block work on it. BookStack may return as the main wiki later; the repo docs will then be reconciled into it. See `docs/ROADMAP.md`.
- **Current plan:** `docs/ROADMAP.md` (Now / Next / Later). The first native-game target is a **Coup-inspired Avrana bluffing card game**, built as a LAN Games module in the Avrana Party Games fork. **Classic Diplomacy and `diplomacy/diplomacy` are abandoned experiments**; don't continue them.

## Product direction: one party, many games (read before designing anything players touch)

Avrana Party is **one party platform with many games** (*the game may change; the party does not*: the Party outlives every game session). Before designing anything players touch (a game, lobby, login, chat, stat, navigation), read `docs/design/README.md` → `docs/design/PARTY-PLATFORM.md` (the hub) and ADRs `0002`/`0003`. Keep in mind:

- **Device ≠ Profile ≠ Presence ≠ Seat; Admin ≠ Host** (ADR 0003). Names never authorize; games never see device tokens.
- One appliance = one party; guest-first; browser-first; offline-first; TV, app and captive portal all optional.
- **Hard stops:** ROADMAP **N3** (no live-system changes without approval), N5 "Rule for now" (the platform is documents and offline simulations only until the BLUFF real-phone playtest, N2; BLUFF is the working title of the first native card game), and ROADMAP "Explicitly not doing". The current next action is at the top of ROADMAP "NOW".

## Workflow

1. Edit locally, commit to Git, then deploy to and test on `party` (laptop → GitHub → Pi; see "Deploy" below).
2. Inspect remote state (files, services, configs) before changing it.
3. Back up any live configuration before modifying it.
4. Do not casually modify networking, the captive portal, systemd units, nginx, or other live system configuration. Ask first.

## Never commit

Passwords, API keys, SSH private keys, ROMs, emulator cores, runtime data, or any other secrets. See `.gitignore`. When in doubt, leave it out.

## Repo pointers

- `README.md` and `CLAUDE-HANDOFF.md` hold existing project context. `arcade/README.md` covers the streaming prototype.
- BookStack shelf **Avrana Party**: http://10.0.0.218:6875/shelves/avrana-party (currently secondary; see above). Do not confuse it with the **Avrana Homelab** shelf, which documents the separate media server.
- `portal/`, `arcade/`: application code. The LAN Games server source is not in this repo (`/home/cody/LAN-Games` on `party`).
- `avrana-party.nginx`, `avrana-captive.conf`, `install-*.py`: deploy and system config. Treat them as live-system-adjacent.
- `avrana-party.nginx`, `arcade/nginx-site` and the live `/etc/nginx/sites-available/avrana-party` must stay byte-identical (check with `cmp`). `arcade/install-service.py` overwrites the live site from `arcade/nginx-site`.
- Deploy: the checkout on `party` (`/home/cody/avrana-party`) tracks `origin/main`. Commit and push off-Pi, then `git pull --ff-only` on `party`. Don't edit or commit in that checkout, and remember that pulling there changes **live** arcade code (the service needs a restart to pick it up; ask first). Feature branches are tested in the Pi dev checkout `~/avrana-lab/avrana-party-docs` (despite its name, used for every feature branch: `git fetch && git merge --ff-only origin/<branch>`), never developed there. Experiments on the Pi live under `~/avrana-lab/`.
- Games fork (LAN Games + BLUFF): the Pi dev clone is `~/avrana-lab/avrana-party-games` (runs on port 8196); the live service `/home/cody/LAN-Games` is never edited. A verified bare backup is on the laptop (`~/avrana-party-games.git`); once the GitHub repo exists, work moves to a laptop clone with the same laptop → GitHub → Pi flow. Never push `abandoned/classic-diplomacy`.
