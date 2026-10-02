# Avrana Party

A portable local multiplayer appliance. A Raspberry Pi 4 runs the games; phones join its
“Avrana Party” Wi-Fi and play in a normal browser. Core play needs no internet, cloud accounts
or app installs. **The game may change; the party does not.**

## Start here

| You want to know… | Canonical source |
|---|---|
| Current source/code/tests | GitHub `main` in Party and [Games](https://github.com/rcnechamkin/avrana-party-games) |
| Live priorities, next task, blockers, acceptance and ownership | [Linear](https://linear.app/avranakern) |
| Architecture and product contracts | [ADRs](docs/adr/) and [design docs](docs/design/README.md) |
| Deployed topology and verified revisions | [SYSTEM](docs/SYSTEM.md), supported by dated [findings](docs/findings/) |
| Strategic direction and milestones | [ROADMAP](docs/ROADMAP.md) |
| Test commands and evidence tiers | [TESTING](docs/TESTING.md) |
| Agent and deployment rules | [CLAUDE.md](CLAUDE.md), [Cloud guide](CLAUDE-CLOUD-HANDOFF.md) |
| Network, HTTPS and adding games | [Network](docs/runbooks/network.md), [HTTPS](docs/runbooks/party-https.md), [add a game](docs/runbooks/add-a-game.md) |

Findings, old PR bodies and historical handoffs record what was true at their date; they do not
assign current work. Linear owns live sequencing.

## Current source and verified production

Current main includes [Party PR #34](https://github.com/rcnechamkin/avrana-party/pull/34) and
[Games PR #13](https://github.com/rcnechamkin/avrana-party-games/pull/13), implementing
[ADR 0011](docs/adr/0011-party-console-model.md). A browser with an Avrana profile gains or resumes
presence automatically on the canonical Party/game surfaces. Normal play has no Join or Leave
button. The host moves one authoritative Party location through home, Party-owned full-screen
setup, game and held results. Play or Watch and host-only Start come from ADR 0010.

**Source is ahead of verified production.** The latest repository deployment finding records
Party **`956b968`** and Games **`c6d7b52`** on 2026-09-29. It verifies Party Core, authoritative
navigation (AVR-128), Party-managed arcade lifecycle (AVR-134) and BLUFF pregame (AVR-129) on the
server. Deployment and real-phone verification of ADR 0011 remain with **AVR-212**. Merged PRs and
automated browsers do not establish production or phone acceptance; see [SYSTEM](docs/SYSTEM.md).

| Surface | State |
|---|---|
| Party Home `/party/` | Implemented and deployed with profile, catalog, shared Party Chat, favorites/history and Party Core; current source adds the console model above |
| Native browser games | Private Games fork supplies the maintained LAN Games titles; BLUFF is the first native Avrana testbed, with server-authoritative rules, filtered private hands and Party sessions |
| Gauntlet II `/arcade/` | Shared WebRTC stream, two controller slots; emulator/encode run for the Party session. AVR-130 reconnect reservations merged in PR #35 during this reconciliation; deployment/phone acceptance remains unverified by published findings |
| PS1 / Personal Viewports | Research on experiment branches; metadata is not an installed production runtime |

BLUFF discovery/direct launch has dated iPhone evidence; the full group playtest and newer Party
flows still need their own phone evidence. Earlier Gauntlet two-iPhone play likewise does not
prove the current console flow.

## URLs on the Party Wi-Fi

- `https://party.avrana.net/party/`: Party Home; `/party/diag/`: diagnostics.
- `https://party.avrana.net/`: maintained legacy Games hub; `/arcade/`: Gauntlet II.
- `http://10.42.0.1/` (also `http://party.local/`): legacy/recovery entry, a separate origin.
- `http://10.42.0.1/hotspot-detect.html`: Apple probe deliberately returns `Success` without a popup.

Use the canonical HTTPS origin for Party identity. The AP is internal `wlan0` at `10.42.0.1`;
`eth0` carries upstream/management traffic. TV and captive portal are optional.

## Repository contents

| Path | Purpose |
|---|---|
| `avrana/`, `contracts/` | Party Core, session protocol, providers, capability evaluation, Game Contracts and appliance grants |
| `web/party/`, `web/src/` | Static Full Mode shell and generated UI sources/assets |
| `arcade/` | Gauntlet II stream and runtime integration |
| `deploy/`, `ops/` | Deployment templates and owner-run release/recovery tools |
| `avrana-party.nginx`, `avrana-captive.conf` | Reviewed nginx and captive DNS configuration |
| `tests/` | Offline unit/modules/browser suites, cross-repo harness and separate live-appliance tests |
| `telemetry/`, `docs/` | Telemetry tooling; architecture, runbooks, strategy and dated findings |

## Development and verification

Work on an issue-scoped branch from current main, then open a PR. Deployment and service restarts
are separate owner-approved actions; never edit production checkouts.

`npm ci` installs tooling. `npm run test:offline` runs Python unit, Node module and localhost
browser checks; Linux CI also supplies nginx/logrotate gates. `npm run check:ui` and
`python3 -m avrana.contracts.catalog --check` check generated assets. See [TESTING](docs/TESTING.md)
for platform setup, historical results and cross-repo commands.

`npm test`, soak and fault target the live appliance on Party Wi-Fi and are not offline checks.
Real phones, offline operation, Wi-Fi capacity, streaming hardware, latency and power require
separate bounded hardware/human evidence. Historical portal and arcade records remain in Git
history, dated findings and [the historical Claude log](CLAUDE-HANDOFF.md).
