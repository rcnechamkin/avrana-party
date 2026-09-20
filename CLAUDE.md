# CLAUDE.md

## Environment

- **This laptop** is the primary dev machine. This local Git repo is where code is normally edited.
- **GitHub `origin`** is the canonical remote and history.
- **SSH `party`** is the Raspberry Pi running Avrana Party. It is the deployment and test target, not the place to develop.
- **SSH `avrana`** is the mini-PC hosting infrastructure (BookStack, Beszel, etc.).
- **BookStack** is the source of truth for architecture, decisions, and runbooks. Check it before making design assumptions, and update it when decisions change.

## Workflow

1. Edit locally, commit to Git, then deploy to and test on `party`.
2. Inspect remote state (files, services, configs) before changing it.
3. Back up any live configuration before modifying it.
4. Do not casually modify networking, the captive portal, systemd units, nginx, or other live system configuration. Ask first.

## Never commit

Passwords, API keys, SSH private keys, ROMs, emulator cores, runtime data, or any other secrets. See `.gitignore`. When in doubt, leave it out.

## Repo pointers

- `README.md` and `CLAUDE-HANDOFF.md` hold existing project context. `arcade/README.md` covers the streaming prototype.
- BookStack shelf **Avrana Party**: http://10.0.0.218:6875/shelves/avrana-party. Do not confuse it with the **Avrana Homelab** shelf, which documents the separate media server.
- `portal/`, `arcade/`: application code. The LAN Games server source is not in this repo (`/home/cody/LAN-Games` on `party`).
- `avrana-party.nginx`, `avrana-captive.conf`, `install-*.py`: deploy and system config. Treat them as live-system-adjacent.
- `avrana-party.nginx`, `arcade/nginx-site` and the live `/etc/nginx/sites-available/avrana-party` must stay byte-identical (check with `cmp`). `arcade/install-service.py` overwrites the live site from `arcade/nginx-site`.
- The checkout on `party` has no git remote, so no deploy method is defined yet. Confirm the method with the user before deploying.
