# CLAUDE.md

Avrana Party: a Raspberry Pi 4 party appliance — phones join its Wi-Fi and play in a normal browser;
designed as **one party platform with many games**. Start at `README.md` → "Start here".

## Machines and network (details: `docs/SYSTEM.md`, `docs/runbooks/network.md`)

- **GitHub `origin`**: canonical source and history. Edit in a local checkout or Claude Code Cloud
  on a branch; push that branch for review. The laptop is optional, not a required runtime path.
- **SSH `party`** (`10.0.0.142`, eth0): the Pi — a deploy/test target; never develop there.
- **SSH `avrana`**: home infrastructure (Beszel telemetry hub; BookStack — stale, don't repair it
  unless the owner asks; the repo is the documentation source of truth).
- Pi network: **eth0 = upstream + management; wlan0 = the "Avrana Party" access point at
  `10.42.0.1/24`** (NetworkManager profile "Avrana Party Internal"). There is no `wlan1` / USB Wi-Fi.
- The Party's browser-trusted hostname is `https://party.avrana.net/` on the
  Party network; local dnsmasq resolves it to `10.42.0.1`. Read
  `docs/runbooks/party-https.md` before changing nginx, DNS or certificates.

## Laptop Party-network testing

When the laptop is connected to both Ethernet and Avrana Party Wi-Fi:

- normal internet/GitHub traffic uses Ethernet
- `10.42.0.0/24` is directly reachable over Wi-Fi
- `party.avrana.net` resolves through the Party DNS to `10.42.0.1`
- `ssh party` is still the management-LAN path

Local Claude Code may run Party-network browser/curl/E2E tests against:
https://party.avrana.net/

Do not treat management-LAN success as Party-WLAN validation.

## Where truth lives

Status and the next action: `docs/ROADMAP.md` · what runs where: `docs/SYSTEM.md` · every test:
`docs/TESTING.md` · design: `docs/design/README.md` · decisions: `docs/adr/` · measured facts:
`docs/findings/` (newest dated file wins). Record new decisions and findings there, not only in chat.
Label claims honestly: LIVE / TESTED / EXPERIMENT / PROPOSED / OPEN; a simulation is not a
measurement, and a proposal is not a decision.

Platform contracts (capability names, Game Contract v0, appliance profile, seat evaluation):
`contracts/README.md` and ADR 0004. The Full Mode web shell (`web/party/`, served at `/party/`
on HTTPS): `docs/design/FULL-MODE.md`.

For architecture and dependency work, read `docs/AVRANA-OPEN-SOURCE-SUBSTRATE.md` (its §0 decision
matrix wins over older sections)
alongside `docs/GAME-PLATFORM-ARCHITECTURE.md`,
`docs/OFFLINE-TRUST-AND-RECOVERY.md`,
`docs/PERSONAL-VIEWPORT-AND-EMULATION.md`, and
`docs/REFERENCE-IMPLEMENTATIONS.md`. The substrate document is current research
on reusable subsystems and candidates, not a finalized or deployed architecture.

## Product boundary

Avrana Party owns cross-game identity/profile, roster/presence, Party Chat,
favorites/history, catalog and navigation. LAN Games is legacy MVP infrastructure
undergoing assimilation, not an independent product boundary. Do not build a second
platform inside it. Read `docs/design/LAN-GAMES-ASSIMILATION.md` before profile,
chat, catalog or shell work. The /party/ adapters reuse the existing wc-* / lg-*
backing keys and donor transports; do not add parallel stores or identity tokens.
Read `docs/design/LAN-GAMES-PROVIDER.md` and ADR 0005 before launch/provider work.
The games fork is now private GitHub `rcnechamkin/avrana-party-games`. Its registry
owns browser-title metadata; use its deterministic exporter and drift check.
Integrated launches use advertised avrana.lan-launch/v1 plus ?avrana=1 and fixed
/party/ return. Canonical library IDs share the existing lists with lazy alias
compatibility. Preserve standalone access; no new global features in its legacy hub.

## Hard rules

- **`main` is production.** Develop on `docs/*`, `experiment/*`, `fix/*` or `chore/*` branches;
  review and test before merging to `main`. Never force-push, rewrite history or deploy experiments.
- **Pi:** inspect before changing; no `sudo` (the owner types it); no changes to NetworkManager,
  nginx, dnsmasq, systemd units, the live services (`avranaparty-games` :8096,
  `avranaparty-arcade` :8097) or the production checkout `/home/cody/avrana-party` without asking.
  Experiments live under `~/avrana-lab/` on dev ports (8190 party front, 8196 BLUFF, 8198 PS1).
- `avrana-party.nginx`, `arcade/nginx-site` and the live site must stay byte-identical (`cmp`).
- Full Mode (ADR 0004):
  - Avrana web pages live under `/party/` on the 443 server only; the port 80 server stays as it is.
  - Never add HSTS or `Service-Worker-Allowed`, and never widen the service worker beyond `/party/`.
  - Capability names come only from `contracts/capabilities.v0.json`.
  - A Game Contract never carries grants (paths, tier, trust, granted permissions).
  - Never decide anything from the user agent.
- **Power measurements:** sample on the Pi and read once at the end — no SSH polling and no parallel
  agent work during one (each SSH session is a CPU burst).
- PS1/emulator runs: bounded and supervised only (`ps1/tools/supervised-run.sh`, or a party-launched
  session you stop yourself); never unattended. Soak, viewer scaling past 5 or stopping the arcade
  need the owner (ROADMAP N4).
- **Never commit or print:** passwords, Wi-Fi keys or home network names, tokens, keys, ROMs, BIOS,
  emulator cores, saves, runtime data. Before every push: inspect the diff, scan for secrets and
  binaries, confirm the branch.
- Classic Diplomacy / `diplomacy/diplomacy` is abandoned (AGPL): never continue it, and never push
  or merge the games fork's `abandoned/classic-diplomacy` branch.
- The games fork (LAN Games + BLUFF) is a **separate repository** (laptop bare backup
  `~/avrana-party-games.git`, Pi dev clone `~/avrana-lab/avrana-party-games`); the live
  `/home/cody/LAN-Games` is never edited.

## Product rules (`docs/design/PARTY-PLATFORM.md`, ADRs 0002/0003)

- Device ≠ Profile ≠ Presence ≠ Seat; Admin ≠ Party Host. Names never authorize; games never see
  device tokens; credentials never appear in URLs or logs.
- One appliance = one party; guest-first, browser-first, offline-first; TV, app and captive portal
  are optional. Accessibility is infrastructure (`docs/design/ACCESSIBILITY.md`).
- Words: "host" means the **Party Host** (a player role). Call the machine "the Pi" or "the
  appliance", and say "Host header" for HTTP.

## Workflow

Read `CLAUDE-CLOUD-HANDOFF.md` before a Cloud task. Clone from GitHub → make a branch → run
offline/unit checks first (`docs/TESTING.md`; `npm ci && npm run test:offline`, in Cloud with
`PW_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium`; the real-nginx test needs `nginx` installed) → push for review. Browser E2E in `tests/` targets
the live appliance and needs the Party Wi-Fi; Cloud cannot run it. Pi-only validation belongs in
`~/avrana-lab/` on dev ports. After review, merge to GitHub `main`, then fast-forward the clean
production checkout `/home/cody/avrana-party` to that exact commit. Restarting services or changing
live configuration is a separate, owner-approved deployment step.
