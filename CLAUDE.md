# CLAUDE.md

## Environment

- **This laptop** is the primary dev machine. This local Git repo is where code is normally edited.
- **GitHub `origin`** is the canonical remote and history.
- **SSH `party`** is the Raspberry Pi running Avrana Party. It is the deployment and test target, not the place to develop.
- **SSH `avrana`** is the mini-PC hosting infrastructure (BookStack, Beszel, etc.).
- **Documentation source of truth (since 2026-09-22): this repository.** The BookStack API/MCP integration is unreliable, so record decisions, findings and progress in the repo (`docs/ROADMAP.md`, `docs/findings/`, `docs/adr/`, `CLAUDE-HANDOFF.md`). **Do not try to repair BookStack or its MCP unless the owner explicitly asks**, and never block work on it. BookStack may return as the main wiki later; the repo docs will then be reconciled into it. See `docs/ROADMAP.md`.
- **Current plan:** `docs/ROADMAP.md` (Now / Next / Later). The first native-game target is a **Coup-inspired Avrana bluffing card game**, built as a LAN Games module in the Avrana Party Games fork. **Classic Diplomacy and `diplomacy/diplomacy` are abandoned experiments**; don't continue them.

## Product direction: one party, many games (read before designing anything players touch)

Avrana Party is a **portable local multiplayer platform whose games plug into a shared party system**: *the game may change; the party does not* — the Party is a long-lived object that outlives every game session. Avrana owns identity, session, social, progression, navigation and player management; games consume them. Before designing a game, lobby, login, chat, stat or navigation feature, start at **`docs/design/PARTY-PLATFORM.md`** (the hub; it links the focused design docs) and the ADRs `0002-party-platform` and `0003-ids-and-keys`; phasing is ROADMAP **N5**. The rules agents most often need:

- **Guest-first, browser-first, offline-first; no app and no captive portal required; TV optional.**
- **One appliance = one party.** The host is disposable (grace, then succession); late joiners spectate unless the game opts in; physical seating is not a platform concept.
- **Device ≠ Profile ≠ Presence ≠ Seat ≠ Role ≠ Persona** (ids and credentials: ADR 0003). Games get a game key and a persona, never a device token. Names never authorize anything.
- **Admin ≠ Host.** The admin is PIN-protected and appliance-wide; the host is a temporary party role with no system powers.
- **Navigation is party-synchronized**, and a game must not reinvent profiles, chat, reconnect, teams, spectators or session lifecycle.
- **The phone is not just a controller**: native games should use each player's private screen (`docs/design/NATIVE-GAMES.md`).
- **Never claim what can't be observed:** every stat carries provenance; emulated games produce no results unless a per-game adapter exists, and participation is never a win.
- **Not a gameplay framework and not a store:** platform services around games through a small contract (`docs/design/GAME-INTEGRATION.md`); open installation (`docs/design/GAME-INSTALLATION.md`).
- Until the BLUFF real-phone playtest (N2) is done, the platform is **documents and offline simulations only** (`experiments/party-model/`, `experiments/viewports/` on branch `experiment/party-sim`).

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
- Deploy: the checkout on `party` (`/home/cody/avrana-party`) tracks `origin/main`. Commit and push off-Pi, then `git pull --ff-only` on `party`. Don't edit or commit in that checkout. Feature branches are tested in the Pi dev checkout `~/avrana-lab/avrana-party-docs` (`git fetch && git merge --ff-only origin/<branch>`), never developed there. Experiments on the Pi live under `~/avrana-lab/`.
