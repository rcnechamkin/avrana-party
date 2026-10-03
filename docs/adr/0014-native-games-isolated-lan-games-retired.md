# ADR 0014 — Native games are isolated platform consumers; LAN Games is retired

Status: **accepted (direction) · proposed (mechanisms) · not implemented** · Date: 2026-10-02
Supersedes the long-term architecture of [ADR 0005](0005-lan-games-provider-launch.md) and the
"LAN Games module as native runtime" assumption in [GAME-INTEGRATION](../design/GAME-INTEGRATION.md)
and [GAME-INSTALLATION](../design/GAME-INSTALLATION.md) (see §Supersession). ADR 0005 and the LAN
Games design documents remain accurate history and current-deployment context until retirement
is performed and verified. Retirement, registry/routing and the Checkers proof are
[AVR-228](https://linear.app/avranakern/issue/AVR-228/retire-lan-games-as-the-avrana-runtime-preserve-it-only-as),
[AVR-222](https://linear.app/avranakern/issue/AVR-222/retire-standalone-lan-games-runtime-and-legacy-wc-token-player),
[AVR-229](https://linear.app/avranakern/issue/AVR-229/make-one-game-manifest-the-canonical-source-of-party-game-metadata),
[AVR-236](https://linear.app/avranakern/issue/AVR-236/build-generic-native-game-registry-routing-and-provision-game-path),
[AVR-227](https://linear.app/avranakern/issue/AVR-227/define-field-test-service-identities-and-inter-service-trust-boundary),
[AVR-237](https://linear.app/avranakern/issue/AVR-237/define-partygame-result-envelope-v1-before-the-second-native-game) and
[AVR-238](https://linear.app/avranakern/issue/AVR-238/prove-checkers-as-the-first-clean-native-game-platform-consumer-after);
Linear owns sequencing. Nothing in this ADR is deployed: the LAN Games fork still runs on the Pi as
[SYSTEM](../SYSTEM.md) records, BLUFF still runs inside it, and Checkers does not exist.
Context: [ADR 0002](0002-party-platform.md), [ADR 0003](0003-ids-and-keys.md), [ADR 0006](0006-party-session-protocol.md),
[ADR 0013](0013-party-and-game-browser-origins.md), [ADR 0011](0011-party-console-model.md),
[GAME-PLATFORM-ARCHITECTURE](../GAME-PLATFORM-ARCHITECTURE.md), [LAN Games notice](../references/LAN-GAMES-NOTICE.md).

## Context

LAN Games (BEACNpool, MIT, retired upstream) was adopted in 2026-09 as a deliberately low-cost
MVP substrate: ~28 working browser party games, a hub, chat and avatars, for the price of a fork.
ADR 0005 and the assimilation/provider designs made it a *provider* behind Avrana's catalog, and
ADR 0006 bridged it to Party sessions so that BLUFF, the first Avrana-native game, could be
played as a Party round. That worked: Party Core, tickets, host-authoritative navigation and the
console model were all proven against it.

It also fixed in place things the platform documents had already called debt: one process and one
event loop for every game and for chat; a browser-mintable `wc-token` that is at once device,
person, seat key and reconnect credential for standalone play; one shared process key, so any
module can read any game's session (ADR 0003, ADR 0006 "Threat assumptions"); game-specific
knowledge (BLUFF's held results, forfeit rules) threaded through `core/session.py` and
`core/net.py`; and bespoke nginx locations and grants per title. The 2026-10-02 review concluded
that continuing to build Avrana-native games as LAN Games modules would make the MVP substrate the
permanent runtime by default.

## Decision

### Retirement

1. **LAN Games was MVP infrastructure and is not the future Avrana runtime.** The following are
   retired from normal Avrana operation (timing in Linear):
   - the standalone LAN Games player flow (the hub at `/`, its lobbies and return chrome) as a
     supported product mode; it may remain a development/compatibility surface until removed;
   - browser-minted `wc-token` player admission;
   - the LAN Games monolith as the runtime/platform for native games;
   - any architecture that treats `lan_games_module` as the normal future execution model.
2. **LAN Games is preserved only as** donor and reference source (the fork and the upstream
   rollback checkout), source material for future *Classics* adaptations of individual titles
   onto the native boundary, and a possible test/reference source for selected TV-required games.
   Attribution ([LAN Games notice](../references/LAN-GAMES-NOTICE.md)) and the donor history in
   [LAN-GAMES-ASSIMILATION](../design/LAN-GAMES-ASSIMILATION.md) are kept.

### The native-game boundary

3. **Each native game is an independent platform consumer** with its own process or runtime
   boundary, its own service/Unix identity where the host supports it, and its own secrets and
   state directory. A game reads no other game's state or keys. Platform-granted permissions and
   resources come from the appliance grant, as ADR 0004 D3 already requires.
4. **Local IPC prefers Unix sockets** between nginx, Party Core and game processes where that is
   practical; loopback TCP remains acceptable where it is not. Nothing a game serves is reachable
   except through the front door.
5. **Routing is generic.** nginx (or whichever front door) routes to games from a runtime-readable
   **game registry**, not from a hand-written location block per title. Adding a game adds a
   registry entry and a grant, not nginx edits.
6. **One provisioning path** creates a game's identity, grants, keys and runtime registration.
   The same path serves BLUFF, Checkers, Spades and later packages.
7. **One canonical per-game manifest** is the source from which catalogue, grant validation and
   runtime registration derive or are mechanically checked. Over time it carries or derives: a
   stable id/slug and version; player counts; Party behaviour (late join, spectators, teams,
   pregame); runtime requirements; presentation requirements; permissions; resources; lifecycle
   bounds; and the supported Party protocol and result-schema versions. Game Contract v0 (ADR 0004
   D3) is the seed of that manifest, not a competitor to it; LAN Games' registry export and the
   compiled browser catalog become derived artefacts or disappear.
8. **No game-specific logic in Party Core.** Party Core speaks `avrana.party-session` (ADR 0006
   and its amendments) and the forthcoming result envelope (AVR-237); it knows roles, roster,
   location and outcomes, never a game's rules or screens.
9. **Party owns durable results.** Games determine their own outcomes and report structured,
   versioned results; Party is the only writer of persistent cross-session results, history, stats,
   person/profile attribution and provenance (ADR 0002 decision 6, ADR 0003 invariant 7).

### Product shape

10. **One active Standard Mode activity.** One appliance, one Party, one active activity at a
    time (ADR 0011). Standard Mode is not architected for simultaneous side games or tables. A
    future *Developer Mode* may deliberately expose multi-activity experimentation to technical
    users; it is outside the consumer architecture and must not complicate Standard Mode.
11. **Validation order.** BLUFF is already the first Avrana-native game in product terms and
    remains the first vertical slice. **Checkers** is the first deliberately simple proof that a
    game can live entirely outside the LAN Games runtime on the boundary above (AVR-238); it is not
    "the first native game". **Spades** follows as the pressure test for teams, private hands,
    reconnect, scoring and richer results.
12. **`.avrgame` archives, the SDK and the provider abstraction stay unfrozen** until Checkers and
    Spades have proven the boundary. LAN Games' `core/session.py` is a donor of patterns, not the
    SDK (ADR 0006 D6 already said so). Exact systemd directives, CLI syntax, container or sandbox
    technology are implementation choices for the Linear issues above, not decisions here.

## Supersession

- **ADR 0005**: its decisions remain the accurate record of the deployed provider boundary
  (`avrana.lan-catalog/v1`, `avrana.lan-launch/v1`, shared `wc-*` keys, one `/chat/ws`). Its
  long-term architecture ("LAN Games owns individual game implementations and temporary
  transport internals") is superseded: individual games move to the native boundary or are not
  carried forward.
- **GAME-INTEGRATION §2** runtime table: `lan_games_module` becomes legacy/retiring; `process` is
  the native runtime type.
- **GAME-INSTALLATION** "Built-in … any runtime, including in-process LAN Games modules": built-in
  games use the same isolated boundary as everyone else; being built in is a trust statement, not
  a licence to share a process.
- **NATIVE-GAMES §3** "LAN Games' `core/session.py` already is this [the SDK]": superseded.
- **ADR 0003 §5 mapping** "Standalone (non-party) play keeps working as today until the fork
  cutover": the cutover happened (2026-09-27); standalone play is now retiring rather than being
  preserved.

## Consequences

- Until retirement lands, **BLUFF still traverses LAN Games infrastructure** (`core/net.py`,
  `hubnet.js`, the fork's server on port 8096). Documents describing that path are current
  deployment context, not contradictions of this ADR.
- Chat, avatars and the shared library keys, which the assimilation design routed through the
  donor, need Party-owned replacements or explicit decisions to drop them before the monolith can
  stop; those are scoped in Linear, not here.
- Per-game processes cost memory and CPU on a Pi 4. The registry and provisioning path must make
  stopping idle games cheap; "runs only while active" (GAME-INSTALLATION) is the expectation for
  games that are not the current activity.
- Tier 2 gains a simulated second game process behind the simulated front door; Tier 3 proves a
  Checkers round end to end on real phones before any SDK is declared.
- Nothing here deletes code. Removing the fork from production is a separate, owner-approved
  deployment with a rollback plan.

## Deliberately open

Service manager details; container or sandbox mechanics; the registry file format and where it
lives; whether Classics adaptations share a small runtime; the exact result envelope (AVR-237);
how chat and avatars are re-homed; the `.avrgame` format; the community/marketplace workflow.
