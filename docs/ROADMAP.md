# Avrana Party — strategic roadmap

Reconciled 2026-10-01 against GitHub main and dated repository findings; strategic sequencing
reconciled 2026-10-02 with ADRs 0012–0014. This document describes
product direction and milestone outcomes. **Linear owns live priorities, sequencing, blockers,
acceptance criteria, ownership and the next agent task.** Start with the current Linear issue;
do not infer an assignment or deployment approval from this roadmap.

| Question | Source of truth |
|---|---|
| What source/code/tests exist? | GitHub `main` in each repository |
| What is deployed and running? | [SYSTEM](SYSTEM.md) and dated [findings](findings/) |
| What are the architecture/product contracts? | [ADRs](adr/) and [design docs](design/README.md) |
| What should we work on next? | [Linear](https://linear.app/avranakern) |
| Where is the product going? | This roadmap |

Merged source may be ahead of production. Findings, old PR bodies and archived handoffs are
dated evidence; their former instructions do not override a current Linear issue. BookStack is
an older documentation mirror; do not repair it unless the owner asks.

## Product direction

**The game may change. The party does not.** One appliance hosts one Party across many games.
Avrana owns cross-game identity/profile, presence, host authority, navigation, catalog and social
surfaces; games own rules, rendering and private state. Browser-first, guest-first, offline-first;
TV, captive portal and an app are optional. Physical seating is not a platform concept.

V1.0 is for the owner: prove that an entire party night works and is fun. A later demonstrator or
crowdfunded appliance must not distort that goal. The three useful demonstrations remain native
no-TV social games, native action games designed around phones, and emulated multiplayer with
[Personal Viewports](design/PERSONAL-VIEWPORTS.md). BLUFF is the first Avrana-native game and testbed.
Standard Mode is one appliance, one Party, one active activity at a time.

## Foundation milestone: implemented, with distinct release evidence

The former N5/F1–F8 build-order list mixed experiments, contracts and production work. It is
retired as a queue. Its useful outcomes now map to these boundaries:

| Foundation | Current baseline | Remaining boundary |
|---|---|---|
| IDs and keys (former F1) | ADR 0003 invariants; Party Core device credentials and session participant tickets | Rich persistent profiles, trust and pairing remain design work |
| Single origin (F2) | Browser-trusted `https://party.avrana.net`, `/party/`, games and arcade through nginx; published Games fork cutover | HTTP stays a recovery/legacy origin; PS1 runtime promotion is still experimental. Target changed 2026-10-02: one trusted *Party* origin plus a separate game origin (ADR 0013), and a Limited Mode without trusted HTTPS (ADR 0012) |
| Device identity (F3) | Server-issued, hash-only Party cookie; games receive session credentials instead | Shared browser profile keys are compatibility storage, not cloud accounts or a completed profile database |
| Party authority (F4/F6) | Party Core v0, host grace/succession, versioned actions and one session | Reboot persistence, kicks and broader admin/moderation remain future contracts |
| Presence and sessions (F5) | Party membership, ticket admission, stable BLUFF participant identity/reconnect | AVR-130 arcade reservations merged during this reconciliation (PR #35); deployment/phone proof is pending; a universal seat/grace layer is not complete |
| Metadata and capabilities (F7) | ADR 0004 Game Contract v0, appliance grants, deterministic Games catalog and per-seat capability evaluation | Experimental PS1 metadata is not an installed runtime |
| Lifecycle/provenance (F8) | Signed session launch/end/completion reports and outcomes | The broader stat/event sink, achievements and cross-game scoring remain design direction |

Party Home is implemented at `/party/`. AVR-128 supplies authoritative navigation; AVR-134
makes Gauntlet II's emulator/encode run only for a Party session; ADR 0010 / AVR-129 supplies
Play or Watch with host-only Start. These are recorded as deployed, server-side verified on
2026-09-29: Party **`956b968`**, Games **`c6d7b52`**. Server checks are not phone acceptance. Party PR #35 subsequently merged AVR-130 arcade
controller reservations; published findings do not verify their deployment or physical acceptance.

Current source additionally contains [Party PR #34](https://github.com/rcnechamkin/avrana-party/pull/34)
and [Games PR #13](https://github.com/rcnechamkin/avrana-party-games/pull/13), implementing
[ADR 0011](adr/0011-party-console-model.md): automatic presence with an Avrana profile, no normal
Join or Leave button, one authoritative `home/setup/game/results` location, Party-owned
full-screen setup, held results and host-owned navigation. Production deployment and Tier 3
phone verification belong to AVR-212; no newer release evidence is recorded here.

## Platform-boundary milestone (accepted 2026-10-02)

The 2026-10-02 decisions ([ADR 0012](adr/0012-limited-mode-party-survives-https-loss.md),
[ADR 0013](adr/0013-party-and-game-browser-origins.md),
[ADR 0014](adr/0014-native-games-isolated-lan-games-retired.md) and the dated amendments to ADRs
0002, 0003, 0006 and 0011) set the strategic order below. It is an order of outcomes, each
depending on the ones before it; issue state, scope and acceptance live in Linear and are not
duplicated here. None of it is deployed.

1. **Decision-record reconciliation** — ADRs and design documents agree with the decisions.
2. **Single-use tickets** — close the v0 replay gap; reconnect fetches a fresh ticket. Merged in
   Party source on 2026-10-02 (PR #42); deployment evidence is separate.
3. **Party/game origin boundary** — game clients leave the trusted Party origin.
4. **Service/process isolation** — per-game process, service identity, secrets and state.
5. **Canonical manifest** — one per-game source for catalogue and runtime metadata.
6. **Generic registry, routing and provisioning** — no per-title front-door configuration.
7. **Result protocol** — versioned results from games; Party owns the durable record.
8. **Retire the LAN Games operational dependency** — standalone flow, `wc-token` admission and
   the monolith as runtime; the code stays as donor/reference.
9. **Checkers platform proof** — the first deliberately simple game outside the LAN Games runtime.
10. **Spades pressure test** — teams, private hands, reconnect, scoring, richer results.
11. **Only then freeze and build SDK, package and provider abstractions.**
12. **Community, package signing and productization** — later.

Limited Mode (ADR 0012) is accepted direction alongside this sequence rather than a step in it;
its place in the order is a Linear decision. The party-night milestone below continues in
parallel: this sequence must not regress a real evening's play.

## Party-night milestone

The outcome is a coherent evening: open the Party address, set a local name/avatar, follow the
host through setup, play or watch, finish a round, and move together to the next one. Sleeping,
reloading or reopening a phone should recover the authoritative location and the game's own
identity safely. Validate this with actual iPhone Safari and Android Chrome, including truly
offline play. See [TESTING](TESTING.md) and the [BLUFF playtest](runbooks/bluff-playtest.md).

BLUFF already has server-authoritative rules, filtered private views, bots, timers, autopilot,
reconnect and Party session integration. Its Coup-inspired baseline uses original working names
and assets. A real group should inform mechanics, theme, readable prompts, event history and
player-count balance. Differential masking and protocol tests remain essential: another
player's hidden state must never reach a player's browser. Do not generalize gameplay primitives
until a second game needs them.

Gauntlet II remains the shared-stream arcade path, with four controller slots in source (AVR-311,
2026-10-07). Earlier two-iPhone play proves that dated prototype, not four phones, ADR 0011 phone
behavior or a long multi-phone soak. Preserve the runtime while measuring reconnect, audio
recovery, latency, power and phone usability.

## Emulation and Personal Viewports research

PS1 title profiles, the experimental Party service and the lifecycle/viewport simulations are
research evidence on `experiment/ps1-title-profiles`, `experiment/party-service` and
`experiment/party-sim`. They are not alternative production contracts or instructions to merge
those branches wholesale.

The 2026-09-24 Bomberman slice proved bounded shared-stream play and independent controller
slots, but found latency stalls and resource contention with the arcade. Preserve the measurements
in [the latency finding](findings/2026-09-24-ps1-latency.md) and
[the slice finding](findings/2026-09-24-ps1-bomberman-party-slice.md). Hardware display/capture and
streaming-provider alternatives remain research candidates in the
[substrate decision matrix](research/AVRANA-OPEN-SOURCE-SUBSTRATE.md).

Personal Viewports should prove readability and preference against a full shared frame, then
measure latency and stability with real phones. Auto-detection and per-title result adapters
come only after a manual proof. Emulated participation is observable; a win is not observable
without a trustworthy result adapter. Hot-seat games cannot assume per-person turn attribution.

All emulator runs stay bounded and supervised. Sustained soak, viewer scaling beyond five and
stopping the production arcade require owner approval; experiment history is not approval.

## Longer-term product direction

- Profiles and local history: guest-to-profile promotion, recent players, device trust/revocation,
  optional profile PINs, pairing, export/import and admin-only merge without transferring access.
- Social play: build on the existing shared Party Chat transport; consider queue/voting,
  playlists, team chat and whispers only where a party night demonstrates the need. The host
  remains the final authority; votes are advisory and belong to presences, not sockets.
- Progression (Party-owned record; needs the optional server-side Profile before anything
  persistent is stored about a person): participation with provenance, authoritative native-game results, party recaps,
  then teams, achievements and cosmetics where evidence supports them. Never equate launch
  history with completed play.
- New native games: content-light no-TV reveals and action games using each phone as a private
  dynamic surface, each an isolated platform consumer (ADR 0014). Extract a private-player-panel
  contract only when two games need it.
- Open installation: appliance-owned grants and trust tiers; sandbox untrusted community code.
  Packaging (`.avrgame`), package signing, public/demo admission and richer administration remain
  separate future work, after the platform-boundary milestone.
- Optional TV/public surfaces and companion conveniences: never show players' private hands,
  require a TV for the whole platform, or make an app the baseline.

## Appliance readiness milestone

Measure boot-to-joinable time, power-loss recovery, battery runtime, cooling, phone battery drain,
the AP's actual awake-client ceiling, noisy-venue usability and offline recovery. QR/NFC/e-ink
onboarding is a convenience around a normal browser. Certificate renewal and release rollback
must be maintainable; current topology and operational evidence live in SYSTEM and runbooks.

Removing the USB Wi-Fi adapter resolved under-voltage for the workloads measured on 2026-09-24.
That does not prove cold boots, long sessions, several active phones, PS1 or a battery pack.
Use the [network runbook](runbooks/network.md) and dated power findings for the test conditions.

## Standing boundaries and historical context

Develop on issue-scoped branches; review and test before merge. Deployment, live configuration
and restarts are separate owner-approved steps ([AGENTS](../AGENTS.md)). No direct production
editing. Keep credentials, ROMs/BIOS/cores, runtime data and raw telemetry out of Git.

There is no universal gameplay engine, cloud-account requirement, proprietary game store,
multi-party appliance, simultaneous-activity Standard Mode or distributed-phone-display
commitment. Preserve captive probes. Standalone LAN Games compatibility is preserved only while
the fork is still the deployed runtime; it is not a product mode and retires with it (ADR 0014).
The retired LAN Games upstream is maintained through the private Games fork as donor/reference
code; its original checkout remains a rollback copy.

Classic map-based Diplomacy was abandoned on 2026-09-23 after a misunderstanding of the target.
Its [engine finding](findings/2026-09-22-diplomacy-engine-on-pi.md) and local
`abandoned/classic-diplomacy` branch are historical only; never continue, push or integrate it.
Earlier N1–N5/F1–F8 marching orders remain in Git history and dated findings, not this live roadmap.
