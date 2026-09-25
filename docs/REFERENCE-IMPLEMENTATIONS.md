# Avrana Party — Reference Implementations and Borrowable Engineering Patterns

> **Status: research notes.** These references are prompts for later investigation;
> verify each project's current license and implementation before reusing code or assets.

## Purpose

This document records open-source or source-available projects that are useful as engineering references for Avrana Party.

These projects are **not automatically game candidates**.

The primary reason they are included is that they contain implementation work, architecture, protocol design, packaging ideas, session behavior, or browser/mobile patterns Avrana Party can study instead of inventing everything from scratch.

Always re-check current licenses before copying code or assets.

---

# Summary Matrix

| Project | Primary Avrana Value | Avoid / Caveat |
|---|---|---|
| OpenGlad | simulation/runtime separation, authoritative networking, seats, snapshots, browser/WASM | do not inherit UI/art or require its language/engine |
| GameNest | local party appliance model, game catalog, common room shell, private per-player views | game registration is more manual/monolithic than desired |
| OpenCombat | reconnect grace, validation, fixed ticks, metrics, logs, same-origin local serving | avoid making Colyseus mandatory |
| WebWars | legacy engine → browser/WASM, WebSocket gateway, lazy assets | not yet a complete mobile/touch reference |
| Suroi | delta replication, dirty-state tracking, shared schemas, mobile-aware networking | much more complex than most Avrana games need |
| OpenFront | deterministic simulation, intent model, worker separation | do not universalize lockstep |
| Mindustry | dedicated server, LAN philosophy, version/mod compatibility, content ecosystem | native-first assumptions |
| Mk48.io | shared types across server/WASM client, compiled browser runtime | do not require Rust/WASM globally |
| GenerateRacer | unified input abstraction, lightweight static deployment | manual WebRTC signaling is not acceptable UX |
| Agar.io clone | simple authoritative browser-game architecture | old implementation details |
| tuxes3 Bomberman | touch controls, rooms, browser multiplayer, room cleanup | backend architecture is not a platform model |
| MultiPlayer Bomberman | small transport/game-manager separation | limited platform relevance |
| Artillery | compact host-authoritative turn model, touch-first browser play | no license; PeerJS/host-phone authority are poor Avrana defaults |

---

# 1. OpenGlad

## Why It Matters

OpenGlad is one of the strongest references for Avrana's core runtime model.

It demonstrates a game architecture where simulation, transport, rendering, and platform-specific concerns are meaningfully separated.

It also has a browser/WASM path and server-authoritative multiplayer.

## Borrow

### Simulation independent from presentation

Strong reference for keeping:

- game world/simulation
- rendering
- audio
- platform code
- transport

separate.

This is important because Avrana wants games to render through multiple execution paths.

### Local play still respects client/server boundaries

Useful design principle:

Do not create a completely separate code path for “local” gameplay.

Keep local players going through the same conceptual intent → authority → state flow.

Benefits:

- easier testing
- bots can reuse client interfaces
- replay tools are easier
- headless simulation is easier
- multiplayer bugs are less likely to diverge from single-player behavior

### Stable seats

Useful reference for distinguishing player/seat identity from raw connection state.

Avrana should preserve seats across reconnects.

### Snapshots + deltas + state verification

Borrow conceptually:

- full state snapshots
- incremental updates
- protocol revisioning
- optional state hashes/desync detection

### Persistent lobby-to-game lifecycle

The same underlying session can survive:

```text
lobby
→ game
→ results
→ lobby
```

Avrana should behave similarly.

### Ephemeral events separate from durable state

Useful for:

- audio triggers
- haptics
- screen shake
- particle effects
- temporary animations

These should not be modeled as durable game-state fields.

### WASM browser packaging

Reference for a heavier downloadable game tier:

```text
HTML shell
JS glue
WASM engine
packaged data
```

## Avoid

- Do not turn Avrana into an OpenGlad fork.
- Do not force C++ or OpenGlad's engine structure on every game.
- Do not reuse GPL-covered code casually in a commercial core without deliberate licensing analysis.
- Do not inherit its current visuals/UI as product direction.

## Avrana Impact

High.

Use OpenGlad primarily as a runtime/networking architecture reference.

---

# 2. GameNest

## Why It Matters

GameNest is close to the Avrana Party appliance concept:

- one local server
- phones on the same Wi-Fi
- room/join flow
- multiple unrelated games
- browser clients
- local-first operation

It is strategically valuable even if its individual games are not Avrana-quality.

## Borrow

### Shared shell for unrelated games

This validates the concept that Avrana can own:

- player identity
- rooms
- ready state
- reconnect
- catalog
- launch

while games provide their own rules/rendering.

### Common game-module contract

Use as inspiration for a more formal Avrana SDK/package contract.

Avrana should improve on it by making packages self-describing rather than requiring central source edits to register games.

### Private per-player views

Especially important.

The authority can hold complete canonical state while producing seat-specific views.

Use for:

- cards
- hidden roles
- fog of war
- secret objectives
- private inventory

### Bots and common room behavior

Useful reference for allowing bots to fit into the same room/session structure as humans.

## Avoid

- Manual game registration in central server files.
- Monolithic assumptions that make third-party packages difficult.
- Treating its exact API as the Avrana API.
- Reusing game names/assets without checking trademark/copyright implications.

## Avrana Impact

Very high for package/catalog/session philosophy.

---

# 3. OpenCombat

## Why It Matters

OpenCombat is useful less for the game itself and more for its practical multiplayer hygiene.

It handles many production problems that prototypes tend to ignore.

## Borrow

### Fixed simulation cadence

Run game simulation on a controlled tick.

Use actual elapsed time carefully.

Clamp huge time jumps after process stalls.

This prevents one scheduling stall from creating giant physics jumps.

### Client input validation

Validate:

- numeric ranges
- finite values
- legal actions
- rate limits
- malformed payloads

Never trust browser/client data simply because all players are on the same local network.

### Reconnect grace

Do not immediately delete player state when a socket disappears.

Reserve the seat for a configurable period.

Allow the reconnecting client to reclaim it.

### Structured metrics/logging

Avrana game servers should expose standardized health information.

Possible common metrics:

- tick duration
- tick overruns
- connected seats
- reconnect count
- errors
- memory
- CPU
- session age
- dropped/invalid messages

### Local dependency vendoring

Games intended for offline Avrana use should not depend on runtime CDNs or Internet-hosted assets.

Everything required should be local to the package or Avrana platform.

## Avoid

- Requiring Colyseus for every game.
- Importing framework complexity into simple games.
- Assuming its current gameplay/UI is representative of Avrana quality.

## Avrana Impact

Very high for resilience and operational standards.

---

# 4. WebWars

## Why It Matters

WebWars is useful because it demonstrates how a traditional native/legacy game engine can be pushed into the browser through WebAssembly and connected to existing multiplayer infrastructure.

It is especially relevant to downloadable browser games and emulator/legacy bridging.

## Borrow

### Heavy engine → browser/WASM path

Useful proof that Avrana can support more than simple JavaScript games.

### Progressive/lazy content

Do not bundle every optional asset into the initial game package.

Split:

- core engine
- required assets
- optional themes/maps/content

This directly informs Avrana's package/content-pack model.

### Browser WebSocket ↔ legacy protocol gateway

Very important.

A legacy server that expects TCP does not need to be rewritten immediately.

Avrana can potentially run:

```text
browser WebSocket
→ local Avrana gateway
→ legacy TCP/native protocol
```

This expands the set of reusable open-source games/servers.

### Keep the outer session alive

Launching the game should not destroy the Avrana Shell's room identity/session if avoidable.

Mount game runtime inside a persistent shell/session boundary.

## Avoid

- Treating WebWars' current mobile UX as production-ready.
- Assuming every legacy engine will port cleanly to WASM.
- Assuming browser networking can directly replace every native socket behavior.

## Avrana Impact

Very high for legacy integration and progressive delivery.

---

# 5. Suroi

## Why It Matters

Suroi is a mature enough browser multiplayer project to demonstrate serious state-replication discipline.

## Borrow

### Dirty-field / delta replication

Avoid retransmitting full player/world objects when one field changes.

Track changed state and send compact deltas.

This is not mandatory for tiny games, but the platform should make it possible.

### Shared client/server schemas

Keep one canonical definition of protocol/state types where practical.

Avoid independently maintained server and client structures.

### Mobile-aware input semantics

Send movement/action intent rather than emulating keyboard events.

## Avoid

- Copying its complexity into simple party games.
- Treating large battle-royale networking requirements as the minimum Avrana baseline.

## Avrana Impact

High as a networking optimization reference.

---

# 6. OpenFront

## Why It Matters

OpenFront is useful for deterministic simulation and intent-based networking.

## Borrow

### Intent model

Clients express:

> what the player wants to do

The authority/simulation decides:

> what actually happens

This is a strong general Avrana principle.

### Worker isolation

Running simulation separately from UI/rendering in browser workers can preserve responsiveness.

Useful for more demanding browser-native games.

### Deterministic simulation

For selected strategic/tick-based games, deterministic lockstep can reduce bandwidth and simplify state distribution.

## Avoid

- Making deterministic lockstep the default for all realtime games.
- Assuming mobile browsers will remain perfectly deterministic under suspension/throttling.
- Copying AGPL-covered code into proprietary components without deliberate licensing analysis.

## Avrana Impact

Medium-high.

Use concepts selectively.

---

# 7. Mindustry

## Why It Matters

Mindustry is a strong reference for multiplayer ecosystem management.

It demonstrates:

- dedicated server operation
- LAN-friendly multiplayer
- mod/plugin ecosystem concepts
- client/server compatibility checking
- version awareness

## Borrow

### Compatibility handshake

Before launching:

- game version
- protocol version
- content version
- required mod/content set

should be checked explicitly.

Do not let mismatched clients fail mysteriously later.

### Server-delivered/required content philosophy

The session authority should be able to dictate:

> This session requires these exact versions/assets.

Phones then acquire missing material from Avrana Party.

### Dedicated server administration

Useful model for Avrana headless game servers.

## Avoid

- Native-app-only assumptions.
- Requiring a Mindustry-like mod ecosystem for v1.
- Exposing server-administration complexity to normal users.

## Avrana Impact

High for compatibility/versioning/content management.

---

# 8. Mk48.io

## Why It Matters

Mk48 demonstrates a compiled browser client and shared code/types across server and client.

## Borrow

### Shared definitions

A useful model for keeping protocol/state definitions consistent.

### WASM as normal browser runtime

Supports Avrana's position that WASM should be first-class rather than exotic.

## Avoid

- Requiring Rust for Avrana games.
- Treating every game as a high-performance WASM workload.

## Avrana Impact

Medium.

Useful proof and implementation reference.

---

# 9. GenerateRacer

## Why It Matters

GenerateRacer is lightweight and demonstrates a clean cross-input browser model.

## Borrow

### Unified input abstraction

Map:

- touch
- keyboard
- gamepad

into one game-facing intent interface.

### Static lightweight deployment

Useful model for tiny games that should not need a large build/deployment stack.

## Avoid

### Manual WebRTC signaling

Any flow requiring users to copy/paste connection blobs is unacceptable for Avrana.

Avrana Party already has a central local device and should own discovery/signaling.

### P2P-first architecture as default

For most Avrana games, a local authoritative server over WebSockets is simpler and more reliable.

## Avrana Impact

Medium.

Very useful for input and minimal deployment, not for multiplayer orchestration.

---

# 10. Agar.io Clone

## Why It Matters

The Agar.io clone is useful because it is simple.

It demonstrates:

```text
browser sends input
server owns game
server sends state
canvas renders
```

That is enough for many Avrana games.

## Borrow

- simple authoritative Node-style server
- simple browser renderer
- clear protocol/client separation
- self-hostable local multiplayer

## Avoid

- importing old implementation details as platform architecture
- overfitting Avrana to Socket.IO specifically

## Avrana Impact

Medium.

Useful reminder not to overengineer small games.

---

# 11. tuxes3 Bomberman

## Why It Matters

Useful compact reference for:

- browser multiplayer
- touch controls
- WebSockets
- rooms
- inactive-room cleanup

## Borrow

### Room garbage collection

Abandoned sessions must die automatically.

Conceptual lifecycle:

```text
room empty
→ grace period
→ terminate game process
→ flush logs
→ release resources
→ invalidate stale seat/session tokens
```

## Avoid

- using its backend structure as the Avrana platform architecture
- assuming its custom/permissive license is sufficient for commercial reuse without re-checking exact terms

## Avrana Impact

Medium.

Best lesson is lifecycle cleanup.

---

# 12. MultiPlayer Bomberman

## Why It Matters

Small enough to understand quickly.

Useful as an anatomy diagram for separating transport from a game-management layer.

## Borrow

- lightweight server/game-manager separation
- simple room/player handling

## Avoid

- treating it as a complete production architecture
- using it as the basis for the Avrana SDK

## Avrana Impact

Low-medium.

Useful educational reference.

---

# 13. Artillery

## Why It Matters

The project is useful as a conceptual reference for a Worms-like browser game with touch controls and host-authoritative turn handling.

## Borrow Conceptually

### Compact authoritative turn model

Clients send actions.

One authority determines valid turn state.

Compact state updates are distributed.

This maps well to:

- artillery games
- card games
- board games
- simple party games

### Touch-first interaction

Useful reference for phone-native web controls.

## Avoid

### No license

The repository currently lacks a clear software license.

Do not copy code or assets unless permission/license status changes.

### Host-phone authority

Avrana already has a central local appliance.

Do not make one player's phone the authoritative host unless there is a compelling reason.

### Public PeerJS dependency

Do not depend on an Internet-hosted broker for a local-first appliance.

## Avrana Impact

Medium conceptually, low for direct code reuse.

---

# Cross-Project Patterns Avrana Should Standardize

The repositories collectively support the following architecture.

## Package/catalog

Borrow from:

- GameNest
- Mindustry
- WebWars

## Runtime boundaries

Borrow from:

- OpenGlad
- OpenCombat

## Seat/session lifecycle

Borrow from:

- OpenGlad
- GameNest
- OpenCombat

## Authoritative realtime state

Borrow from:

- OpenGlad
- OpenCombat
- Agar clone

## Efficient replication

Borrow from:

- Suroi
- OpenGlad

## Intent/action separation

Borrow from:

- OpenFront
- Suroi

## WASM/browser execution

Borrow from:

- OpenGlad
- WebWars
- Mk48.io

## Progressive content

Borrow from:

- WebWars
- Mindustry

## Touch/controller abstraction

Borrow from:

- GenerateRacer
- OpenCombat

## Private player state

Borrow from:

- GameNest

## Metrics/reconnect/resilience

Borrow from:

- OpenCombat

## Legacy protocol adapters

Borrow from:

- WebWars

## Turn-based authority

Borrow from:

- Artillery
- Bomberman references

## Room cleanup

Borrow from:

- Bomberman
- GameNest-style room lifecycle

---

# Licensing Notes

Current high-level license understanding from the research session:

- OpenGlad — GPLv2
- GameNest — Apache 2.0
- OpenCombat — MIT code; assets may have separate permissive licenses
- WebWars / Hedgewars lineage — GPL-family constraints apply
- Suroi — GPLv3
- OpenFront — AGPLv3
- Mindustry — GPLv3
- Mk48.io — AGPLv3
- GenerateRacer — MIT
- Agar.io clone — MIT
- MultiPlayer Bomberman — MIT
- tuxes3 Bomberman — custom permissive-style license; re-check before reuse
- Artillery — no clear license; treat as reference-only

Do not rely on this section as final legal verification.

Before direct reuse:

1. inspect current repository license
2. inspect dependency licenses
3. inspect asset licenses separately
4. determine whether linking/derivative-work obligations apply
5. document attribution/source obligations
6. seek legal review before commercial distribution where appropriate

---

# Source URLs

These URLs are included for agent navigation and future verification.

- https://github.com/openglad/openglad
- https://github.com/absswds/GameNest
- https://github.com/FreePeak/opencombat
- https://github.com/apmlabs/webwars
- https://github.com/HasangerGames/suroi
- https://github.com/openfrontio/OpenFrontIO
- https://github.com/Anuken/Mindustry
- https://github.com/SoftbearStudios/mk48
- https://github.com/commjoen/generatedracer
- https://github.com/owenashurst/agar.io-clone
- https://github.com/tuxes3/bomberman
- https://github.com/Bshisia/MultiPlayer-Bomberman
- https://github.com/lettfeti/artillery

---

# Current Recommendation

Do not fork one project and attempt to turn it into Avrana Party.

Instead, use these repositories as implementation references while defining a small Avrana-specific platform contract.

The platform should combine:

- OpenGlad-style runtime separation
- GameNest-style multi-game shell
- OpenCombat-style resilience
- WebWars-style browser/legacy packaging
- Suroi-style replication
- OpenFront-style intents
- Mindustry-style version/content management
- GenerateRacer-style input abstraction

The goal is to borrow solved engineering work without inheriting unnecessary product constraints.
