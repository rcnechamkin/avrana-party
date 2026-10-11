# Avrana Party — Game Platform Architecture

> **Status: design direction, not deployed implementation.** Read `design/PARTY-PLATFORM.md` and ADRs 0006–0011
> for current contracts, `SYSTEM.md` for deployed state, `ROADMAP.md` for strategy, and Linear
> for live sequencing. Broader concepts below are research, not an implemented SDK.
>
> **Reconciled 2026-10-02** with ADRs [0012](adr/0012-limited-mode-party-survives-https-loss.md),
> [0013](adr/0013-party-and-game-browser-origins.md) and
> [0014](adr/0014-native-games-isolated-lan-games-retired.md). The "Accepted direction" section
> states what those ADRs decided; none of it is deployed. Everything else remains conceptual, and
> examples (package trees, manifests, schedulers) are illustrations, not built functionality.

## Purpose

This document defines the current architectural direction for Avrana Party as a game platform.

It is written primarily for LLMs and future engineering agents. Treat it as project context, not marketing copy. Preserve the distinctions between **current decisions**, **strong architectural preferences**, and **open implementation questions**.

---

## Accepted direction (2026-10-02)

This is the forward-looking overview. The ADRs are the decisions; [SYSTEM](SYSTEM.md) is what is
deployed; Linear owns sequencing.

| Area | Accepted direction | Status |
|---|---|---|
| Surface | **Browser-first.** Wi-Fi plus a normal browser is the product; app, TV and captive portal are optional | deployed principle |
| Trust in transport | **Full Mode / Limited Mode.** Trusted HTTPS is preferred; its loss degrades capabilities individually and visibly and never disables the Party (ADR 0012) | Full Mode deployed; Limited Mode not implemented |
| Browser trust | **Party origin vs game origin.** The trusted Party origin owns device identity, the Party API, membership/presence, host/platform controls and profile/system surfaces; the game origin holds session tickets only (ADR 0013) | not implemented; one origin today |
| Activity model | **One active Standard Mode activity.** One appliance, one Party, one activity at a time. A future Developer Mode may relax this for technical users, outside the consumer architecture (ADR 0011 amendment, ADR 0014) | deployed for Party sessions |
| Game runtime | **Isolated native-game processes**: per-game process, service identity, secrets and state; local IPC, Unix sockets preferred (ADR 0014) | not implemented |
| Lifecycle | **Game Supervisor / registry** as the target: runtime-readable registry, start/stop, health, limits | target; not built |
| Metadata | **One canonical game manifest**; catalogue and runtime metadata are derived or mechanically validated, no competing layer (ADR 0014, AVR-229) | target; Game Contract v0 is the seed |
| Operations | **Generic routing and one provisioning path** for identity, grants, keys and registration; no per-title nginx blocks (AVR-236) | target; not built |
| Durable data | **Party owns durable profiles, results and history.** Device identity is not human identity; a browser-stored name/avatar is not durable identity; persistent facts need an optional server-side Profile | target; no Profile store or result store exists |
| Results | **Games submit versioned result data**; Party validates, attributes and is the only writer. Schema is AVR-237, not yet designed | target |
| Tickets | Symmetric HMAC, single-use, fresh ticket on reconnect; public-key signatures only for package/update provenance (ADR 0003/0006 amendments) | single-use admission merged in Party source (AVR-52, PR #42); verified production predates it |
| LAN Games | **Legacy/Donor only.** MVP infrastructure; not a future runtime; standalone play and `wc-token` admission retire; code kept as donor/reference and Classics source material (ADR 0014) | still deployed until retirement lands |
| Validation sequence | **BLUFF → Checkers → Spades.** BLUFF is the first Avrana-native vertical slice; Checkers is the first clean proof outside the LAN Games runtime; Spades pressure-tests teams, private hands, reconnect, scoring and richer results | BLUFF exists; Checkers and Spades do not |

**Future and deliberately unfrozen:** the final `.avrgame` archive format, the SDK surface, the
provider abstraction, sandbox and container mechanics, package signing workflow, and any
owner/companion app. They are designed after Checkers and Spades have proven the boundary.

---

## Core Product Model

Avrana Party is a local-first party gaming appliance.

Its long-term purpose is to let a group of people join a local Avrana Party device with phones and immediately play multiplayer games with minimal setup.

The platform may support multiple execution styles:

1. **Browser-native games**
   - HTML/JavaScript/WebAssembly runs on each phone.
   - Avrana Party provides game packages, room/session coordination, authority, and shared state.

2. **Native-app execution**
   - *Open conflict (2026-10-10, AVR-335): owner direction in AVR-37 rules out delivering native mobile executables through `.avrgame`, which this item does not reflect. Unresolved pending a reviewed decision; see [Portable game-client delivery](design/PORTABLE-GAME-CLIENT-DELIVERY.md) section 11.*
   - The Avrana mobile app may run game or emulator workloads locally on the phone.
   - Avrana Party remains coordinator, package source, session authority, or fallback renderer.

3. **Central execution / streaming**
   - Avrana Party runs the game or emulator.
   - Players receive video or a personal viewport and send input back.

4. **TV Mode**
   - Avrana Party renders one shared display over HDMI.
   - Phones primarily act as controllers and/or private secondary displays.

These execution paths are complementary. The platform should choose the cheapest viable execution path based on device capabilities, security state, game requirements, player count, and available hardware.

---

## Primary Architectural Principle

**Avrana Party should not think in binary “modes” internally. It should think in capabilities.**

Consumer-facing language such as “Full Mode,” “Limited Mode,” or “Recovery Mode” may still be useful, but internal scheduling should be based on actual capabilities.

Examples:

- Avrana public HTTPS certificate valid?
- Browser running in a secure context?
- Native Avrana app present?
- Browser supports WebAssembly?
- Browser supports WebGPU?
- Gamepad API available?
- Persistent storage available?
- Phone has sufficient CPU/GPU for local execution?
- Avrana device has sufficient CPU/GPU/encoder capacity for fallback streaming?
- Player is in browser, native app, TV mode, or controller-only mode?
- Game has a local-execution implementation?
- Game has a central-render fallback?
- Game supports reconnect?
- Game supports spectators?
- Game requires private per-player state?

The scheduler should combine these facts per player seat.

---

## Durable Platform Components

The durable asset is the platform, not any individual game.

The current conceptual platform components are:

### 1. Avrana Shell

The trusted user-facing application layer.

Responsibilities may include:

- party creation and joining
- player identity
- room/lobby presentation
- game catalog
- package installation and update state
- launch coordination
- reconnect UX
- system status
- recovery UX
- capability reporting
- advanced telemetry for expert users

The shell should not contain game-specific logic beyond launch metadata and capability negotiation.

---

### 2. Game Package Manager

(Future. No package manager exists; the format below is an illustration and is not frozen.)

Manages installable game packages.

A game package should eventually contain enough metadata for Avrana Party to discover and run it without editing the platform itself.

Proposed conceptual structure:

```text
game.avrana
├── manifest.json
├── client/
│   ├── index.html
│   ├── game.js
│   └── optional game.wasm
├── server/
│   └── server entrypoint
├── content/
│   ├── required packs
│   └── optional packs
└── licenses/
```

The exact archive/container format is not yet settled, and is deliberately left unfrozen until the
native-game boundary is proven (ADR 0014).

The important requirement is that packages are self-describing: one canonical manifest per game,
from which catalogue and runtime metadata derive.

---

### 3. Game Supervisor

(Target. Not built: today systemd runs a fixed set of services and the LAN Games fork hosts every
browser game in one process. ADR 0014 accepts per-game processes and a registry as the direction;
supervisor mechanics are not frozen.)

Responsible for running game-server or adapter processes, driven by a runtime-readable game
registry that the front door also routes from.

Responsibilities should eventually include:

- start/stop game runtime
- process isolation
- CPU and memory limits
- crash detection
- health checks
- session lifecycle
- logging
- cleanup of abandoned rooms
- network permissions
- filesystem permissions
- exposing standardized metrics
- preventing one failed game from destabilizing the appliance

Game processes should be treated as potentially untrusted, even if v1 only ships curated games.

---

### 4. Session and Seat Manager

Important identity model:

**device != network connection != player != seat**

Do not collapse these concepts.

A phone may reconnect and reclaim the same seat.

A phone could eventually represent multiple seats.

Device identity is not human identity either: a durable person is an optional server-side
Profile, separate from the live Party identity above (ADR 0003 amendment 2026-10-02).

A spectator is not a player.

A game host is not necessarily Player 1.

A controller may attach to a phone or to Avrana directly.

The seat/session layer should survive temporary connection loss.

---

### 5. Capability Scheduler

Determines the best execution path for each seat.

Example:

```text
Party:
- Seat 1: Avrana App, capable phone
- Seat 2: Avrana App, capable phone
- Seat 3: Avrana App, capable phone
- Seat 4: HTTP browser, no secure context

Game:
- native phone execution supported
- browser execution requires secure context
- central streaming fallback supported

Result:
- Seats 1–3 execute locally
- Seat 4 receives Avrana-rendered fallback
```

The weakest client should not automatically downgrade the entire party.

---

## Game Package Manifest: Minimum Direction

The initial schema should remain small, but some fields should exist from the start because they are expensive to retrofit later.

Conceptual fields:

```yaml
id:
version:

package_schema_version:
sdk_version:
protocol_version:

players:
  min:
  max:

runtime:
  - javascript
  - wasm
  - native-app
  - streamed
  - legacy-adapter

client:
  entrypoint:

server:
  entrypoint:
  authority_model:

capabilities:
  touch:
  gamepad:
  reconnect:
  spectators:
  private_player_state:
  personal_viewport:

requirements:
  secure_context:
  service_worker:
  persistent_storage:
  webgpu:
  webcodecs:
  camera:
  microphone:

content:
  required_packs:
  optional_packs:

permissions:
  network:
  filesystem:
  platform_apis:

integrity:
  hashes:
  signature:

license:
  code:
  assets:
```

This is a conceptual model, not a frozen schema. Whatever it becomes, there is **one** canonical
manifest per game (growing from Game Contract v0, ADR 0004 D3), able over time to carry or derive
id/slug/version, player counts, Party behaviour, runtime and presentation requirements,
permissions, resources, lifecycle bounds and supported protocol/result-schema versions. The
`legacy-adapter` runtime above is where LAN Games donor titles would sit, if any are carried at
all; it is not a path for new games.

---

## Supported Networking Models

Avrana Party should not require every game to invent its own networking architecture.

Three supported models are currently preferred.

### A. Realtime Authoritative State Replication

Default for action games, racers, arena games, co-op games, and most realtime multiplayer.

Pattern:

```text
client sends intent/input
        ↓
Avrana game authority validates and simulates
        ↓
authority sends snapshots/deltas/events
        ↓
clients render
```

Preferred default.

---

### B. Turn-Based Authoritative State

For card games, board games, artillery, social games, asynchronous actions, hidden-role games, etc.

The authority owns canonical state.

Clients send moves/actions.

The server validates and produces the next state.

---

### C. Deterministic Lockstep

Optional for games that benefit from it.

Clients run equivalent simulation and exchange synchronized actions/inputs.

Appropriate for selected strategy/simulation titles and synchronized emulation.

Do not make this the universal model because mobile browser suspension, timer throttling, hardware differences, and emulator differences can complicate determinism.

---

## State Replication

Preferred realtime approach:

- full keyframes/snapshots when needed
- deltas between known revisions
- dirty-field tracking where worthwhile
- optional state hashes for desync detection
- explicit protocol versions

If a client falls too far behind, prefer sending a fresh authoritative snapshot over heroic repair of a long delta chain.

---

## Input Philosophy

Games should consume **intent**, not physical-device events.

Examples:

Preferred:

```text
move_x = 0.63
move_y = -0.42
fire = true
```

Avoid building game logic around:

```text
KEY_W
KEY_SPACE
```

The Avrana input layer may normalize:

- touch
- keyboard
- browser Gamepad API
- Bluetooth/native controller
- future custom Avrana controller
- accessibility inputs

Games should generally not care which physical device generated the intent.

---

## Private Per-Player State

The server must support different views of one canonical game state.

Examples:

- hidden cards
- hidden roles
- secret objectives
- private inventories
- fog of war
- asymmetric player screens

Do not send all hidden information to every client and rely on UI code to conceal it.

Conceptual API:

```text
viewState(gameState, seatId)
```

---

## Game Lifecycle

Earlier conceptual lifecycle (historical; ADRs 0010/0011 supersede manual join/lobby flow).
Current member flow is automatic profile presence → home → Party setup → game → held results;
only the host moves it. The sequence below is not a current UI contract:

```text
Join Party
   ↓
Claim Seat
   ↓
Lobby
   ↓
Launch Game
   ↓
Gameplay
   ↓
Results
   ↓
Return to Lobby
```

The underlying player/session identity should persist through the entire flow.

Avoid destroying and recreating player identity between every game.

Standard Mode runs this flow for **one activity at a time**; it is not designed around
simultaneous side games or tables. Results leave the game as versioned result data and become
durable only in the Party's record.

---

## Reconnect Philosophy

Reconnect is core functionality, not polish.

Mobile clients may:

- change apps
- lock the screen
- roam Wi-Fi
- temporarily lose connectivity
- reload
- have the browser suspend execution

Preferred behavior:

```text
connection lost
   ↓
seat remains reserved
   ↓
game applies configured behavior
   - pause
   - continue
   - bot takeover
   - idle player
   ↓
client reconnects with a fresh single-use ticket
   ↓
authority sends fresh state
   ↓
resume
```

Reconnect policy may vary by game.

---

## Ephemeral Events vs Durable State

Separate authoritative state from presentation events.

Durable state examples:

- health
- positions
- inventory
- score
- active projectile

Ephemeral presentation event examples:

- sound
- haptic
- screen shake
- temporary animation trigger
- visual effect

This separation allows rendering and art direction to change without rewriting simulation logic.

---

## WASM as a First-Class Runtime

WebAssembly should be treated as a first-class browser game runtime.

Potential uses:

- ports of native engines
- emulator cores
- physics-heavy games
- games implemented in Rust/C/C++/other compiled languages

Typical browser package:

```text
HTML bootstrap
JavaScript glue
WASM engine
required assets
optional content packs
```

Do not require every game to use WASM.

JavaScript/TypeScript remains appropriate for many party games.

---

## Progressive Content Delivery

Avoid forcing the entire game universe into the first download.

Preferred model:

```text
core engine
+ required starter content
+ optional content packs
```

Examples of optional packs:

- maps
- campaigns
- high-resolution assets
- music
- skins
- additional characters
- language packs

The Avrana device remains the canonical package source.

Phone caches are disposable acceleration layers, not the authoritative library.

---

## Security Boundary

The trusted Avrana Shell and game code do not share a trust boundary. This is now accepted
direction for **all** game code, not only third-party code (ADR 0013): the Party origin and the
game origin are separate browser trust domains, and each native game is a separate process on the
appliance (ADR 0014). It is not deployed; today games share the Party origin and one process.

Avoid placing arbitrary game code in the same browser origin and API privilege context as the management shell.

Accepted direction and longer-term preference:

- trusted shell origin
- isolated game origin or equivalent sandbox
- short-lived scoped session tokens
- minimal game API permissions
- game process isolation on the Avrana device
- no Internet access for games by default
- explicit manifest permissions

The exact sandbox mechanism for untrusted community games is open and unfrozen. A package
signature, when it exists, establishes provenance and never substitutes for this isolation.

---

## Hardware Abstraction

Game code should not depend directly on Raspberry Pi hardware.

The current Pi is a prototype platform, not a permanent API.

Games should declare requirements or query abstract capabilities.

Examples:

- required runtime
- minimum memory
- GPU feature requirement
- hardware encoder requirement
- recommended maximum player count
- native-app requirement
- secure browser requirement

This allows future Pi, x86, ARM, custom SoC, or retail hardware transitions.

---

## Performance Budgets

Exact numeric budgets are not finalized, but telemetry should exist early enough to establish them.

Measure:

- Avrana shell idle RAM
- per-game server RAM
- game CPU usage
- simulation tick duration
- input-to-authority latency
- authority-to-render latency
- reconnect duration
- package cold-launch time
- browser package size
- streaming encoder load
- per-seat streaming cost
- device thermal state

Do not wait until retail hardware selection to begin measuring these.

---

## Expert vs Consumer Experience

Default user experience should remain simple.

Normal user:

```text
Join
Choose game
Play
```

Advanced functionality should be optional and discoverable.

Expert/Advanced mode may expose:

- execution strategy
- browser/app capability
- package versions
- game-server health
- device CPU/RAM/thermal state
- network latency
- emulator configuration
- imported content
- protocol/debug information

Advanced functionality must never become necessary for ordinary operation.

---

## Current High-Priority Proofs

Before broadening scope, prove:

0. (2026-10-02) the native-game boundary itself, in order: BLUFF as the existing vertical slice,
   Checkers as the first game outside the LAN Games runtime, then Spades as the pressure test
1. trusted local HTTPS on a real local Avrana network (done for Full Mode), and a usable Limited
   Mode when it is unavailable
2. browser package download/cache/relaunch
3. a minimal self-describing Avrana game package
4. four-player realtime multiplayer
5. seat persistence through disconnect/reconnect
6. one mixed-capability party where different seats use different execution paths
7. a game process crash that does not destabilize the appliance
8. telemetry sufficient to compare local execution vs central fallback

---

## Architectural Invariants

Treat these as strong current principles:

- Offline is a normal operating state.
- Failure should degrade capabilities instead of collapsing the appliance. Losing trusted HTTPS
  is such a failure: it yields Limited Mode, not an unusable Party.
- The Party shell and game clients are separate browser trust domains.
- One appliance, one Party, one active Standard Mode activity.
- Party owns durable profiles, results and history; games report versioned results.
- LAN Games is legacy/donor material, not a runtime to build on.
- Capability detection is more important than binary mode labels.
- The central box should not perform work a capable client can perform more cheaply.
- The weakest client should not automatically downgrade the whole party.
- Game packages should be replaceable; the platform is the durable asset.
- Reconnect is foundational.
- Security restoration should be automatic where safe.
- Product-changing updates should require consent.
- Expert functionality should exist without contaminating the default consumer experience.
