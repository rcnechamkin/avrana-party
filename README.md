# Avrana Party

A portable, self-contained local multiplayer appliance. A Raspberry Pi 4 runs the games; phones
join its Wi-Fi ("Avrana Party") and play in a normal browser — no internet, accounts or app
installs. It is designed as **one party platform with many games**: *the game may change; the party
does not* (identity, host, seats and history carry from game to game — design stage).

Not to be confused with the Avrana Homelab media server (the machine `avrana`).

## Start here

| You want to know… | Canonical source |
|---|---|
| status, what's next, what not to do | `docs/ROADMAP.md` ("NOW" → "Next action") |
| which machine, repo, branch and checkout does what; runtime-only paths; how to sync | `docs/SYSTEM.md` |
| the network (eth0 upstream, internal-Wi-Fi AP, offline mode, checks) | `docs/runbooks/network.md` |
| Party HTTPS, DNS-01 certificates, validation and rollback | `docs/runbooks/party-https.md` |
| how to run every test suite | `docs/TESTING.md` |
| how to add a game | `docs/runbooks/add-a-game.md` |
| the platform design (party, identity, games, viewports, onboarding, accessibility) | `docs/design/README.md` → `PARTY-PLATFORM.md` |
| decisions | `docs/adr/` (0002 party platform, 0003 identifiers and credentials) |
| measured facts | `docs/findings/` (newest dated file wins) |
| rules for coding agents | `CLAUDE.md` |
| starting in Claude Code Cloud | `CLAUDE-CLOUD-HANDOFF.md` |
| arcade prototype history | `arcade/README.md`; `CLAUDE-HANDOFF.md` (historical log with current banners) |

## What exists today (2026-09-24)

Labels: **LIVE** = running on the appliance · **TESTED** = automated tests, not live ·
**EXPERIMENT** = on an experiment branch · **PROPOSED** = design only.

| Thing | Status | Where |
|---|---|---|
| LAN Games hub (~28 browser games) | **LIVE** (port 8096 behind nginx `/`) | `/home/cody/LAN-Games` on the Pi (upstream retired; not in this repo) |
| Gauntlet II arcade stream (1 encode → WebRTC, 2 players) | **LIVE** prototype | `arcade/` |
| Captive probe: Apple gets "Success" (no popup) | **LIVE** | `avrana-party.nginx`, `avrana-captive.conf` |
| Party AP on the Pi's internal Wi-Fi, eth0 upstream | **LIVE** since 2026-09-24 (boot determinism pending: an owner fix in the runbook) | `docs/runbooks/network.md` |
| BLUFF (first native game) in the Avrana Party Games fork | **LIVE** since 2026-09-27 (games fork `9696524` serves port 8096); no real-phone playtest yet | separate repo, see `docs/SYSTEM.md` |
| PS1 on one shared stream; title profiles | **EXPERIMENT**, power-gated | branches `ps1-emulation`, `experiment/ps1-title-profiles` |
| Party lifecycle model; Personal Viewports PoC (incl. shared WebRTC source) | **EXPERIMENT** | branch `experiment/party-sim` (`experiments/`) |
| Party service + device identity + dev front door; manifest v0 | **EXPERIMENT** | branch `experiment/party-service` |
| Browser-trusted HTTPS at `https://party.avrana.net` (Full Mode origin) | **LIVE** since 2026-09-25 (renewal not automated yet) | `docs/runbooks/party-https.md`, `ops/` |
| Full Mode web shell at `/party/`: capability-aware game cards, offline copy, diagnostics; arcade keep-awake + quiet reconnect | **LIVE** at release `7581baa` since 2026-09-27 (server-side and HTTP checks; phone checklist pending) | `web/party/`, `docs/design/FULL-MODE.md` |
| Platform contracts: capability vocabulary, Game Contract v0, appliance profile, per-seat Capability Engine v0; provider boundaries (arcade runs through them) | **TESTED**, not deployed | `contracts/`, `avrana/`, ADR 0004 |
| Party platform, onboarding, accessibility expectations | **PROPOSED** | `docs/design/` |

Power: with the USB Wi-Fi adapter removed and the new PSU, **zero under-voltage** through idle, SSH,
all-core CPU bursts and AP transmit load to one (sleeping) phone — several active phones, PS1 and
long sessions are untested (`docs/findings/2026-09-24-no-usb-power-baseline.md`); with the adapter,
the same PSU dipped 9 times in ~91 min.

## URLs (on the Avrana Party Wi-Fi)

- `https://party.avrana.net/`: browser-trusted Full Mode origin (local Party
  DNS; phone join and HTTPS passed on `fix/party-https`, laptop Wi-Fi check pending)
- `https://party.avrana.net/party/` and `/party/diag/`: the Full Mode shell and diagnostics
  (**after** the owner deploys it: `docs/runbooks/party-https.md`, "Full Mode web shell")
- `http://10.42.0.1/` (also `http://party.local/`): LAN Games hub
- `http://10.42.0.1/arcade/`: Gauntlet II stream
- `http://10.42.0.1/hotspot-detect.html`: Apple connectivity probe (deliberately `Success`)
- `http://10.0.0.218:8093`: Beszel telemetry hub (home LAN, on `avrana`)

## Repo contents (`main`; experiment branches add `experiments/` and `ps1/`)

| Path | Purpose |
|---|---|
| `avrana-party.nginx` | live nginx site (probe, `/arcade/`, LAN Games proxy); must equal `arcade/nginx-site` and the live file |
| `avrana-captive.conf` | captive DNS rules (live: `/etc/NetworkManager/dnsmasq-shared.d/`) |
| `install-portal.py`, `install-captive-dns.py` | installers kept for provenance and recovery; do not rerun blindly |
| `arcade/` | Gauntlet II streaming prototype, service and install files |
| `avrana/` | stdlib Python platform package: `contracts` (validators, catalog build, seat evaluation), `providers` (runtime/input/presentation boundaries + adapters), `web` (shell build, local dev server) |
| `contracts/` | capability vocabulary, Game Contracts, appliance profile, shared test vectors (`contracts/README.md`) |
| `web/party/` | the Full Mode web shell (static; served by nginx at `/party/` on HTTPS) |
| `ops/` | HTTPS certificate scripts and `install-party-web.sh` (Pi only, owner-run) |
| `telemetry/` | Beszel agent + Pi `vcgencmd` sampler installers, systemd units, baseline runbook |
| `tests/` | Playwright E2E against the live appliance (run from a laptop on the party Wi-Fi); `tests/unit` and `tests/offline` are Tier 1–2 offline suites (`npm run test:offline`, CI) |
| `portal/index.html` | old captive landing page; not served since 2026-09-18 |
| `docs/` | roadmap, system map, runbooks, design, ADRs, findings |

## Production end-to-end tests (Playwright)

`tests/` targets the live appliance at `http://party.avrana` (→ `10.42.0.1` via the laptop's hosts
file), so **run them from a machine joined to the Avrana Party Wi-Fi**. `npm test` (fast),
`npm run soak` / `npm run fault` (heavy; power-gated). Details and every other suite:
`docs/TESTING.md`; harness design: `docs/adr/0001-load-soak-fault-harness.md`.

## Open / not yet verified

- Real phones **truly offline** (every phone test so far had internet behind the Pi) — `tools/avrana-offline`
  and the phone checklist in `docs/runbooks/network.md`.
- BLUFF on real phones (ROADMAP N2) — `docs/runbooks/bluff-playtest.md`.
- Input-to-photon latency; soak with more than two phones; the AP's client ceiling.
- Android / Windows / Firefox captive flows (their probes get a 404 today).

# History

## Portal install and history (2026-09-18/19)

Run locally on the Pi:

```sh
sudo python3 /home/cody/avrana-party/install-portal.py
```

The installer saves originals in a timestamped `backups/` directory, installs
the portal HTML and nginx site, runs `nginx -t`, reloads nginx, and restores the
originals on failure.

The mobile landing page is entirely local: embedded CSS, no JavaScript, fonts or
external dependencies. Its ordinary same-window Play link goes to
`http://party.local/`; it does not try to launch Safari automatically. The exact
nginx probe location adds `no-store`, disables ETag and ignores
If-Modified-Since so repeat probes get the page body. See
https://nginx.org/en/docs/http/ngx_http_core_module.html#if_modified_since and
https://nginx.org/en/docs/http/ngx_http_headers_module.html#add_header.

Captive DNS: `avrana-captive.conf` intercepts **both** `captive.apple.com` and
`captive.g.aaplimg.com`, with `local=` rules that stop upstream AAAA/HTTPS
answers for those names. A packet capture on 2026-09-18 showed the iPhone querying
`captive.g.aaplimg.com` directly and receiving Apple's real Success page through
upstream internet, which is why both names are required. Do not remove either.
See https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html.

| Date | Change | Backup |
|---|---|---|
| 2026-09-18/19 | Landing page and probe caching headers installed | `backups/20260919T032818520554Z` |
| 2026-09-18/19 | Captive DNS alias fix installed (`install-captive-dns.py`) | `backups/20260919T033200228715Z` |

## Portal acceptance checks

> **Superseded (design changed 2026-09-18):** `/hotspot-detect.html` now deliberately returns
> Apple's `Success` page so iPhones join silently with no captive popup, and `portal/index.html` is
> no longer served (see `CLAUDE-HANDOFF.md`, "DESIGN CHANGED", and `avrana-party.nginx`). The
> checks below describe the old landing-page design; the current onboarding plan and its test
> list are in `docs/design/ONBOARDING.md`.

1. Request `http://10.42.0.1/hotspot-detect.html` with `Host: captive.apple.com`.
   Expect 200, `Content-Type: text/html`, `Cache-Control: no-store`, the Avrana
   page, and no Apple Success response. Repeat with a future `If-Modified-Since`;
   expect 200 with the page body, not 304.
2. Join Avrana Party on the iPhone. If it remembers the old connection and no
   popup appears, forget that Wi-Fi network and rejoin.
3. Confirm the landing page appears, tap Let's play, and play a game. Test name
   entry, room joining and reconnecting after screen lock.
4. If the captive assistant cannot play reliably, use the displayed Safari
   fallback while remaining connected to Avrana Party.
5. Verify with two phones, then four. An HTTP/WebSocket check alone does not
   establish that games work inside the iPhone captive assistant.
6. Schedule a full offline test with management access available. Do not disable
   `wlan0` during a remote session. *(Since 2026-09-24 the management link is `eth0`.)*
