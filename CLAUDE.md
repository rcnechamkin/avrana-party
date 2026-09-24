# CLAUDE.md

Avrana Party: a Raspberry Pi 4 party appliance — phones join its Wi-Fi and play in a normal browser;
designed as **one party platform with many games**. Start at `README.md` → "Start here".

## Machines and network (details: `docs/SYSTEM.md`, `docs/runbooks/network.md`)

- **Laptop**: the only place code is edited. **GitHub `origin`**: canonical history.
- **SSH `party`** (`10.0.0.142`, eth0): the Pi — a deploy/test target; never develop there.
- **SSH `avrana`**: home infrastructure (Beszel telemetry hub; BookStack — stale, don't repair it
  unless the owner asks; the repo is the documentation source of truth).
- Pi network: **eth0 = upstream + management; wlan0 = the "Avrana Party" access point at
  `10.42.0.1/24`** (NetworkManager profile "Avrana Party Internal"). There is no `wlan1` / USB Wi-Fi.

## Where truth lives

Status and the next action: `docs/ROADMAP.md` · what runs where: `docs/SYSTEM.md` · every test:
`docs/TESTING.md` · design: `docs/design/README.md` · decisions: `docs/adr/` · measured facts:
`docs/findings/` (newest dated file wins). Record new decisions and findings there, not only in chat.
Label claims honestly: LIVE / TESTED / EXPERIMENT / PROPOSED / OPEN; a simulation is not a
measurement, and a proposal is not a decision.

## Hard rules

- **`main` is production.** Never merge into it, force-push, rewrite history or deploy experiments.
  Work on `docs/*`, `experiment/*`, `fix/*` branches; push fast-forward only.
- **Pi:** inspect before changing; no `sudo` (the owner types it); no changes to NetworkManager,
  nginx, dnsmasq, systemd units, the live services (`avranaparty-games` :8096,
  `avranaparty-arcade` :8097) or the production checkout `/home/cody/avrana-party` without asking.
  Experiments live under `~/avrana-lab/` on dev ports (8190 party front, 8196 BLUFF, 8198 PS1).
- `avrana-party.nginx`, `arcade/nginx-site` and the live site must stay byte-identical (`cmp`).
- **Power measurements:** sample on the Pi and read once at the end — no SSH polling and no parallel
  agent work during one (each SSH session is a CPU burst).
- PS1/emulator or stream load only with the owner's go-ahead (ROADMAP N4).
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

Edit on the laptop → commit → push the branch → test in the Pi dev checkout
(`~/avrana-lab/avrana-party-docs`: `git fetch && git merge --ff-only origin/<branch>`) → the owner
merges to `main` → `git pull --ff-only` in `/home/cody/avrana-party` (changes live arcade code; a
restart applies it — ask first).
