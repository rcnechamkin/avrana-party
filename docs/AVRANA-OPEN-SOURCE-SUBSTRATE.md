# Avrana Party Open-Source Substrate Reference

> **Status: current project research.** This document identifies proposed reusable
> subsystems and implementation/reference candidates. It informs architecture work;
> it does not finalize provider choices or describe deployed components.

## Purpose

This document captures the current open-source research direction for **Avrana Party** and is written primarily for LLM ingestion.

The goal is to avoid reimplementing solved infrastructure while preserving Avrana Party's unique architecture and product behavior.

The central rule is:

> **Avrana Core should orchestrate replaceable subsystems through narrow, stable contracts.**

Open-source components may provide runtime, streaming, controller, update, networking, packaging, and security capabilities. Avrana should not become tightly coupled to any single implementation.

---

# 0. Decision matrix (verification pass, 2026-09-26)

**Read this before the per-project sections below.** Five research tracks checked this document
against upstream code, licence files and release metadata on 2026-09-26: the repository audit,
runtime/streaming/input, party engine, network/trust and browser. Where a section below disagrees
with this matrix, **this matrix wins**.

Labels and scope:
- The classifications are **PROPOSED**. The boundaries they refer to are ADR 0004 (proposed).
- **Nothing here proves Pi 4 compatibility.** Rows marked HARDWARE-SPIKE-REQUIRED name the spike
  that would decide them.
- The evidence and sources are in `docs/findings/2026-09-26-architecture-sprint.md`.
- No dependency was added to Avrana by this pass.

Rule: **Avrana owns the contracts and the orchestration; implementations stay replaceable.**
The contracts that exist now:
- the capability vocabulary;
- Game Contract v0;
- the appliance profile;
- RuntimeProvider, InputProvider and PresentationProvider.

### Runtime, streaming and input

| Project | Class | Gives Avrana | Boundary | Licence (read) | Main risk | Avrana keeps |
|---|---|---|---|---|---|---|
| RetroArch / libretro | **ADOPT / WRAP** (live) | emulator runtime; a stdin command channel later | child process behind `RuntimeProvider` (`RetroArchRuntime`) | GPL-3.0 (separate process) | its UDP command port listens on all interfaces without authentication: **keep it off** | lifecycle, config, content identity |
| MAME 2010, FBNeo cores | ADOPT (private use only) | arcade emulation | libretro `.so`, installed by the owner, never committed | **non-commercial** licence texts | commercial distribution is restricted | never bundling cores |
| PCSX ReARMed | ADOPT (experiment) | PS1 emulation; memory maps (viewport state without computer vision) | libretro `.so` | GPL-2.0 | per-title compatibility | title profiles |
| GStreamer `webrtcbin` + Pi `v4l2h264enc` | **ADOPT** (live) | one shared H.264 encode fanned out per phone | in-process (`arcade/stream.py`), `PresentationProvider` | LGPL | 1 encoder context proven; N contexts unknown | encoder budget, seat admission |
| uinput (python-evdev) / XTest | **ADOPT** (live / experiment) | virtual pads | `InputProvider` (isolation global / private) | kernel ABI; python-evdev BSD-3-Clause | uinput pads leak into any udev RetroArch (seen) | seat → slot, staleness policy |
| gst-wayland-display | **HARDWARE-SPIKE-REQUIRED (S1)** → ADAPT | a headless GPU display instead of Xvfb's software GL (~1.2 cores today) | a GStreamer element as frame source | MIT | Smithay GLES on the Pi's v3d is unproven | when to use the GPU |
| Selkies 2.0 + pixelflux 2.1 | **HARDWARE-SPIKE-REQUIRED (S3)** → WRAP or REFERENCE | the only external stack with one encode shared by all viewers **and** a Pi 4 V4L2 M2M encoder | a separate process behind `PresentationProvider` | MPL-2.0 (the published wheels are GPL because they bundle x264) | desktop-product surface; a new dependency | seats, tickets, viewport policy |
| Wolf / Games on Whales | **REFERENCE** (DEFER, S5) | the lobby / producer-switch pattern | none | MIT | **each client gets its own encode**; images are amd64 only; no V4L2 encoder in its default list | fan-out, seats |
| Gamescope | **REJECT** (Pi 4) | — | — | **BSD-2-Clause** (not MIT) | Vulkan extensions the Pi lacks; a Pi 5 bug report shows it failing | — |
| Moonlight-Web (two projects: `linckosz/moonlight-web`, `MrCreativ3001/moonlight-web-stream`) | REFERENCE | transport engineering ideas | none | **GPL-3.0 (both)** | needs a GameStream host and an encode per client | browser transport |
| InputPlumber | DEFER | physical pads → seats, later | a root D-Bus daemon | GPL-3.0-or-later | **routing input over the network is not implemented** (`network.rs` is empty) | seat ↔ pad policy |
| PartyPad | REFERENCE | DSU motion server; RetroArch autoconfig pattern | none | MIT | early alpha, single author | everything else |
| inputtino | DEFER | vendor-exact pads, rumble | library | MIT | `/dev/uhid` access | slot mapping |
| Sunshine | DEFER | a Moonlight host | Moonlight protocol | GPL-3.0 | no Pi hardware encode in a release | — |
| webrtcsink | REJECT for the shared stream; DEFER for dedicated per-seat streams (S2) | congestion control per viewer | — | MPL-2.0 | one encode per consumer | encoder budget |

### Party engine and native games

| Project | Class | Gives Avrana | Licence | Why |
|---|---|---|---|---|
| **Avrana party model + service** (branches `experiment/party-sim`, `experiment/party-service`) | **OWN** | party, device, profile, presence, seat, host succession, seating across games | Avrana | **no upstream framework models a party**; these rules already match or beat every reference |
| Colyseus | **WRAP**, optional and per game (spike 3); **REJECT** as the party layer | a realtime room runtime for native action games | MIT | ~88–91 MB RSS versus ~23 MB for the Python front (x86, not measured on the Pi); puts `sessionId` and `reconnectionToken` in URLs (conflicts with "no credentials in URLs") |
| boardgame.io | REFERENCE | filter-then-diff private state, log redaction, per-move staleness | MIT | copy the patterns into a Python game SDK |
| React Native Couch Kit, Buzz TV Party Game | REFERENCE | the host / transport / display split | MIT | client-minted secrets; raw action echo |
| Hotspot Arcade | REFERENCE | phone-recovery watchdog, captive-browser handoff | MIT | MAC-address identity (rejected) |
| Nakama | REJECT | — | Apache-2.0 | needs Postgres or CockroachDB; account-centric |
| AirConsole, Jackbox | REFERENCE (product behaviour) | — | proprietary / none | — |

### Network, trust, packages and updates

| Project | Class | Gives Avrana | Licence | Note |
|---|---|---|---|---|
| **openNDS** | **REJECT** as a runtime (was "strong candidate"); REFERENCE | RFC 8908/8910 know-how | GPL-2.0 | it forces a splash page and so **brings back the captive popup the owner removed**; v11 refuses a wireless gateway interface; it fights NetworkManager's dnsmasq. Keep the current dnsmasq + nginx design. Spike 4 becomes a captive regression test |
| lego | **ADOPT** (live) | ACME DNS-01, and later DNS-PERSIST-01 or CSR courier mode | MIT | the v4 → v5 CLI break affects `ops/renew-party-certificate.sh`; **don't mint a zone-wide Cloudflare token for the Pi**: delegate `_acme-challenge` by CNAME to a validation-only zone, or wait for DNS-PERSIST-01. Decide before ~2026-11-25 |
| TUF (python-tuf 7.x; go-tuf v2) | **ADOPT** (spike 7) | signed metadata, rollback/freeze protection, delegation | Apache-2.0 OR MIT | the Pi has no RTC, so expiry needs a time policy for courier delays; rust-tuf is REJECTED (beta) |
| OCI image spec 1.1 | ADAPT (DEFER) | per-architecture artifacts, referrers for signatures and SBOMs | Apache-2.0 | a tarred OCI Image Layout; no registry on the Pi |
| ORAS | WRAP on the build / courier side only | produce and export OCI layouts | Apache-2.0 | not on the Pi |
| Rugix | **HARDWARE-SPIKE-REQUIRED** (spike 5, spare SD card) | A/B updates with rollback (Pi 4 tryboot) | MIT OR Apache-2.0 | falls back to ephemeral state if the data partition fails to mount |
| Mender / RAUC | REFERENCE / fallback | A/B update clients | Apache-2.0 / **LGPL-2.1** | Mender needs U-Boot; RAUC has no tryboot backend |
| CertMagic | REFERENCE | ACME renewal info (ARI), locking | Apache-2.0 | only inside a future Go agent |
| LocalSend protocol | REFERENCE; later ADAPT as a receive-only inbox | Companion courier transport | **the protocol repo has no LICENSE file**; the app is Apache-2.0 | trust-on-first-use TLS, an open port |
| CasaOS / ZimaOS store | REFERENCE (UX); REJECT (trust model) | "add a source" without a marketplace | Apache-2.0; ZimaOS has no licence | unsigned; Compose apps get host power |
| Home Assistant add-on model | REFERENCE (pattern) | coarse permission keys + a rating computed by the appliance → Game Contract `runtime.permissions` | code Apache-2.0; docs CC BY-NC-SA | the shape is copied, not the keys |
| Wasmtime | DEFER; HARDWARE-SPIKE-REQUIRED | a capability-scoped sandbox for small extensions (not games) | Apache-2.0 WITH LLVM-exception | aarch64 is Tier 2 upstream; the Pi kernel's 39-bit address space may need tuning |

### Browser

| Source | Class | Use |
|---|---|---|
| MDN Browser Compatibility Data | REFERENCE (prior knowledge only) | expectations; **runtime probes decide** (`web/party/lib/capabilities.js`). Examples: Wake Lock is iOS 16.4 in a tab, 18.4 in Home Screen apps; there is no element fullscreen, orientation lock or vibration on iPhone |

**Corrections to the sections below:**
- §3.2 Gamescope's licence is BSD-2-Clause.
- §3.3 "Moonlight-Web" is two GPL-3.0 projects.
- §3.4 InputPlumber has no network input routing.
- §3.5 PartyPad is alpha and WebSocket-based locally.
- §5.2 openNDS is rejected as a runtime.
- §12 RAUC is LGPL-2.1.
- §13 see the lego note above.
- §19 Wasmtime aarch64 is Tier 2.
- Personal Viewport (§15) is implemented as a presentation `method` with a `viewport` kind
  (`crop`, `dedicated_stream`, `browser_renderer`, `private_panel`) in Game Contract v0
  (`contracts/README.md`).

---

# 1. Current Product Philosophy

Avrana Party is not merely a small gaming appliance. It is intended to become a local-first party gaming platform.

Key principles:

1. **Phones-first participation**
   - Browser participation must remain first-class.
   - The Avrana companion app may enhance capability but must not be required for ordinary participation.

2. **Capability-driven behavior**
   - Avoid a single global `FULL_MODE` / `LIMITED_MODE` switch.
   - Determine capability per:
     - device
     - seat
     - game
     - runtime
     - current network/security state

3. **Graceful degradation**
   - One poorly supported client must not downgrade the entire party.
   - Different players may use different execution paths simultaneously.

4. **Offline-first operation**
   - Internet access is optional during gameplay.
   - Core party creation, joining, controller input, game execution, and local administration should work without WAN connectivity.

5. **Owner freedom, guest simplicity**
   - Guests should receive a highly standardized, low-friction experience.
   - Advanced owners may enable developer functionality, sideload packages, add repositories, inspect logs, or alter runtime behavior.

6. **Replaceable internals**
   - Avrana owns contracts and orchestration.
   - Individual lower-level components should be replaceable without redesigning the product.

---

# 2. Core Avrana Architecture

Current conceptual subsystems:

## Avrana Core
Owns:
- hardware abstraction
- appliance networking
- system lifecycle
- updates
- recovery
- package lifecycle
- local services

## Party Engine
Owns:
- parties
- sessions
- player identities
- seat assignment
- roles
- join/leave/reconnect behavior
- game lifecycle

## Capability Engine
Determines:
- what each client can do
- which APIs/features are actually available
- whether secure browser capabilities are usable
- which execution strategies are available per seat

## Runtime Engine
Launches and manages:
- emulators
- native games
- browser-native games
- streamed games
- hybrid games
- per-seat runtime strategies

## Package System
Owns:
- game packages
- runtime packages
- compatibility data
- controller profiles
- third-party repositories
- signatures
- dependencies
- package permissions

## Avrana Companion
Optional enhanced client that may provide:
- native rendering
- local game modules
- diagnostics
- provisioning
- update transport
- certificate transport
- offline courier behavior
- enhanced controller APIs

---

# 3. Open-Source Components Worth Leveraging

## 3.1 Games on Whales / Wolf

Repository:
- `games-on-whales/wolf`

Primary relevance:
- Runtime Engine

Useful capabilities:
- on-demand isolated gaming sessions
- containerized applications
- virtual displays
- per-client resolution and framerate
- controller support
- low-latency streaming
- configurable encoding
- multi-session operation
- rendering/encoding separation

Potential Avrana role:

```text
Capability Engine
    ↓
Runtime Strategy
    ↓
Wolf session
    ↓
Gamescope / emulator / game
```

Design implication:
- Avrana should investigate using Wolf as a runtime substrate instead of implementing its own long-term session launcher and streaming lifecycle.

License:
- MIT

Integration posture:
- Strong candidate for direct experimentation and possible production integration.

---

## 3.2 Gamescope

Repository:
- `ValveSoftware/gamescope`

Primary relevance:
- Runtime Engine
- display isolation

Useful capabilities:
- nested compositor
- virtual display resolution
- isolated game display environments
- embedded gaming focus
- minimized unnecessary display copies

Potential role:

```text
Wolf
  ↓
Gamescope
  ↓
Game / Emulator
```

Avrana benefit:
- Games do not need direct awareness of the appliance's actual display topology.
- Useful for HDMI, headless, virtual-display, and streamed execution modes.

License:
- permissive/MIT-style components

Integration posture:
- Strong candidate.

---

## 3.3 Moonlight-Web

Repository:
- `linckosz/moonlight-web`

Primary relevance:
- browser streaming
- Personal Viewport research
- Wolf interoperability

Useful capabilities:
- browser-native Moonlight-compatible streaming
- GameStream media
- controller input
- WebRTC
- Wolf integration

Why it matters:
- Demonstrates that a browser can act as an individual low-latency client to a Wolf-backed session.

Potential application:
- Personal Viewport
- individual browser seat streaming
- future browser-native game session access

License:
- GPLv3

Integration caution:
- Do not assume direct code incorporation into a commercial proprietary component.
- Consider:
  - separate-process integration
  - protocol study
  - architectural reference
  - clean-room implementation of required concepts

---

## 3.4 InputPlumber

Repository:
- `ShadowBlip/InputPlumber`

Primary relevance:
- controller abstraction
- virtual gamepads
- seat-to-controller mapping

Useful capabilities:
- combine physical input devices
- create virtual controllers
- remap input
- profiles
- D-Bus control
- network-capable input routing

Potential Avrana abstraction:

```text
Seat 1 → virtual controller 1
Seat 2 → virtual controller 2
Seat 3 → virtual controller 3
Seat 4 → virtual controller 4
```

This is preferable to teaching every Avrana service raw `uinput` behavior.

License:
- GPLv3

Integration caution:
- Prefer daemon/API boundary over copying internal code into proprietary components.

---

## 3.5 PartyPad

Repository:
- `benmross/partypad`

Primary relevance:
- browser phone controllers
- phone-to-uinput architecture
- player slot assignment

Useful capabilities:
- browser phone controller
- DSU/UDP controller support
- `uinput` / `evdev`
- automatic player slot assignment
- WebRTC transport
- temporary Linux AP support

Avrana use:
- Reference implementation for:

```text
Browser Controller
    ↓
Network Transport
    ↓
Seat Mapping
    ↓
Virtual Controller
```

License:
- MIT

Integration posture:
- Excellent reference and potential code reuse candidate.

---

# 4. Party State and Native Game Frameworks

## 4.1 Colyseus

Repository:
- `colyseus/colyseus`

Primary relevance:
- Party Engine
- Avrana-native games

Useful capabilities:
- authoritative server state
- rooms
- state synchronization
- matchmaking primitives
- connection lifecycle
- automatic reconnection
- reconnection tokens
- client reattachment
- delta/binary state updates

Potential model:

```text
One Avrana native game session
        =
One Colyseus room
```

Benefits:
- avoids rebuilding session state synchronization separately for every native Avrana game
- useful for:
  - reconnects
  - iOS browser suspension
  - temporary Wi-Fi drops
  - late joins
  - public/private player state

License:
- MIT

Integration posture:
- Strong candidate for an Avrana-native game SDK experiment.

---

## 4.2 React Native Couch Kit

Repository:
- `faluciano/react-native-couch-kit`

Related example:
- `faluciano/buzz-tv-party-game`

Primary relevance:
- architectural reference

Useful pattern:

```text
Host
Client
Display
Shared game logic
```

This strongly resembles Avrana's independently derived model:

```text
Host
Client
Presentation
```

Potential lesson:
- Keep authoritative game state separate from client rendering and presentation.

Integration posture:
- Reference architecture rather than likely core dependency.

---

# 5. Captive Portal and Local Join Experience

## 5.1 Hotspot Arcade

Repository:
- `tarikbc/hotspot-arcade`

Primary relevance:
- offline local gaming
- captive portal behavior
- client bundle delivery
- phone joining

Useful concepts:
- own AP
- completely local operation
- captive landing page
- WebSocket referee
- content packs
- wildcard DNS
- catch-all HTTP
- compressed client bundles
- bundle-change detection
- persistent caching

Important lesson:
- captive portal mini-browsers are often too restricted for the real game client
- perform a handoff into the device's normal browser when necessary

This directly overlaps with current Avrana iOS captive-portal behavior.

Integration posture:
- High-value reference implementation.

---

## 5.2 openNDS

Repository:
- `openNDS/openNDS`

Primary relevance:
- captive portal engine

Useful capabilities:
- captive portal detection
- modern captive portal identification mechanisms
- RFC 8910 / RFC 8908 support
- small-footprint gateway behavior

Potential role:
- Replace large portions of Avrana's homemade captive-portal plumbing once prototype learning is complete.

Recommended division:

```text
openNDS
    owns:
        captive-network mechanics

Avrana
    owns:
        join experience
        party UI
        player flow
```

Integration posture:
- Strong candidate for prototype testing.

---

# 6. Companion Courier and Offline Transport

## 6.1 LocalSend Protocol

Project:
- LocalSend protocol

Primary relevance:
- Avrana Companion
- offline courier
- device discovery
- LAN transfer

Important design assumptions worth adopting:
- multicast may fail
- discovery requires fallback paths
- clients may not both be able to host services
- no external server should be required for local transfer
- TLS identity can help authenticate peers

Recommended Avrana discovery ladder:

```text
1. mDNS
2. local UDP announcement
3. known Party address
4. QR/bootstrap token
5. manual connection
```

Potential courier payloads:
- certificates
- update metadata
- game packages
- compatibility definitions
- controller profiles
- firmware deltas
- emulator core updates
- diagnostics bundles

Key principle:

> The Companion should transport data, not automatically possess authority to install or trust it.

---

# 7. Package Trust and Secure Offline Updates

## 7.1 The Update Framework (TUF)

Project:
- TUF

Primary relevance:
- Package System
- offline courier security
- repository trust

Useful protections:
- signed metadata
- rollback resistance
- stale metadata detection
- delegated publishers
- target hashes
- repository compromise resilience
- snapshot/timestamp metadata

Recommended model:

```text
Internet
   ↓
Avrana Companion downloads package + signed metadata
   ↓
Offline transfer to Party
   ↓
Party independently verifies package
   ↓
Install only if trust policy passes
```

The Companion should remain deliberately untrusted.

The same verification path should work regardless of transport:

```text
Companion
USB drive
Laptop
LAN transfer
future removable storage
```

Transport is irrelevant.
Verification occurs on the Party.

---

# 8. Package Storage and Distribution

## 8.1 OCI Image Specification

Project:
- Open Container Initiative image specification

Primary relevance:
- Avrana package format
- architecture variants
- content-addressable storage

Useful capabilities:
- arbitrary artifact manifests
- content-addressable blobs
- metadata
- cryptographic digests
- platform variants
- architecture-specific payloads

Potential implication:

A future `.avpkg` may not need to be a custom archive format.

An Avrana package could conceptually be an OCI artifact containing:

```text
manifest
host runtime
browser client
native client module
assets
compatibility metadata
controller profile
```

Architecture variants:

```text
arm64
x86_64
future retail hardware
```

One package identity can reference multiple hardware-specific implementations.

---

## 8.2 ORAS

Project:
- ORAS

Primary relevance:
- OCI artifact transport

Useful capabilities:
- registry-to-registry transfer
- local filesystem storage
- OCI layouts
- air-gapped workflows
- arbitrary OCI artifacts

Potential Avrana use:
- source repositories
- offline artifact export/import
- Companion courier
- development workflows

Integration posture:
- Strong architectural candidate.

---

# 9. Repository and Source Model

## 9.1 CasaOS / ZimaOS App Store

Project:
- CasaOS App Store and related ecosystem

Primary relevance:
- repository metadata
- third-party sources
- app/package manifests

Useful ideas:
- platform-specific metadata layered on standard runtime configuration
- third-party stores
- static-hosted repository content
- no mandatory centralized marketplace

Avrana direction:

Prefer:

```text
Add Source
```

over:

```text
Avrana App Store
```

A source could contain:

```text
repository metadata
package descriptors
signatures
download locations
publisher identity
```

A community source could potentially be hosted on:
- GitHub
- static web hosting
- personal infrastructure

Core philosophy:
- avoid marketplace overhead
- allow advanced users to add community repositories
- keep trust level explicit

---

# 10. Permission Model

## 10.1 Home Assistant Add-on/Supervisor Model

Project:
- Home Assistant Supervisor / add-on ecosystem

Primary relevance:
- Package System
- permission declaration

Useful lesson:
Extensions explicitly request capabilities rather than inheriting the host.

Potential Avrana permissions:

```text
controllers
bluetooth
internet
microphone
camera
party_roster
personal_viewport
host_rendering
persistent_storage
emulator_runtime
local_network
usb
hdmi
```

Desired flow:

```text
Package requests permission
        ↓
Avrana policy evaluates
        ↓
Runtime grants only approved access
```

Third-party software must not receive implicit host-wide authority.

---

# 11. Trust Levels

Potential package trust classes:

## Avrana Verified
- signed
- tested by Avrana
- approved for supported hardware/runtime combinations

## Community Signed
- cryptographically attributable publisher
- not necessarily tested or endorsed by Avrana

## Untrusted / Sideloaded
- owner deliberately installs
- heavily sandboxed
- explicit warning
- still prevented from arbitrary host access where technically possible

Guiding principle:

> Advanced users may choose risky software, but Avrana should maintain technical containment rather than relying only on warning dialogs.

---

# 12. Appliance Update and Recovery Stack

## 12.1 Rugix

Project:
- Rugix

Primary relevance:
- Avrana Core
- operating system updates
- recovery

Useful capabilities:
- A/B updates
- automatic rollback
- delta updates
- cryptographic verification
- compatibility checks
- application/system separation
- state handling
- read-only root filesystem strategies

License:
- MIT / Apache-2 style permissive licensing

Why it matters:
- Specifically aligned with commercial Linux appliance design.

Current recommendation:
- First candidate for Avrana Core system-update research.

---

## 12.2 Mender

Project:
- Mender

Primary relevance:
- alternative A/B update system

Useful behavior:
- dual root filesystem design
- failed-update rollback
- resilience to interrupted updates

Status:
- viable alternative if Rugix proves unsuitable.

---

## 12.3 RAUC

Project:
- RAUC

Primary relevance:
- atomic embedded Linux update bundles
- recovery partition strategies

Useful capabilities:
- signed bundles
- atomic updates
- embedded-device focus

Status:
- viable alternative.

---

# 13. Certificate Courier Infrastructure

## 13.1 lego

Project:
- `go-acme/lego`

Primary relevance:
- HTTPS certificate acquisition
- Companion certificate courier

Useful capabilities:
- ACME v2
- DNS challenge
- custom challenge solvers
- certificate issuance from an existing CSR

Recommended flow:

```text
Party:
    generate private key
    generate CSR

Companion:
    transport CSR to internet-connected Avrana infrastructure

Avrana infrastructure:
    complete ACME/DNS challenge
    obtain signed certificate

Companion:
    transport certificate back

Party:
    install certificate
```

Security property:
- the Party's TLS private key never leaves the Party.

---

## 13.2 CertMagic

Project:
- Caddy CertMagic

Primary relevance:
- alternate ACME/certificate automation

Useful capabilities:
- DNS challenge
- automated certificate lifecycle
- does not require the local Party to be publicly reachable when DNS validation is used

Status:
- useful alternate or backend component.

---

# 14. Capability Detection

## 14.1 MDN Browser Compatibility Data

Project:
- `mdn/browser-compat-data`

Primary relevance:
- Capability Engine

Useful data:
- WebRTC support
- WebCodecs
- Gamepad API
- WebGL
- WebGPU
- fullscreen
- Wake Lock
- motion APIs
- browser/version compatibility

Important rule:

Static compatibility data must not be treated as authoritative runtime capability.

Recommended process:

```text
1. Identify browser/device
2. Consult known compatibility metadata
3. Perform real capability probes
4. Record observed capability
5. Select runtime strategy
```

Example:

Do not conclude:

```text
Safari version X supports feature Y
```

Instead conclude:

```text
This specific device successfully completed:
- WebRTC media
- DataChannel
- fullscreen
- Gamepad API
- required permissions
```

The observed result should drive seat capability.

---

# 15. Personal Viewport

Personal Viewport must not be defined as "crop split-screen video."

Definition:

> A Personal Viewport is an independently addressable visual output associated with a seat.

Possible implementations:

```text
split-screen crop
dedicated streamed renderer
browser-native renderer
native app renderer
private card/hand view
scoreboard
spectator view
secondary tactical UI
```

The Capability Engine and game manifest decide which method is available.

---

# 16. Multi-Strategy Games

An Avrana game may expose multiple execution strategies.

Example:

```text
Among-Us-style Avrana-native game

Host:
    authoritative Party process

Possible client presentations:
    browser renderer
    Avrana app native renderer
    streamed Personal Viewport
    shared HDMI/TV renderer
```

All are implementations of the same game session.

The Runtime Engine selects the best strategy per seat.

This means two players in the same party may legitimately use different presentation technologies.

---

# 17. Game Contract / Manifest

Every game should declare a capability contract.

Potential fields:

```yaml
players:
  min: 2
  max: 8

presentation:
  shared_tv: true
  personal_viewport: optional
  browser_native: true
  app_native: true
  streamed: true

requirements:
  https: preferred
  controllers: true
  microphone: false
  camera: false

late_join:
  supported: true

spectating:
  supported: true

runtime:
  emulator: false
  host_rendered: optional

fallbacks:
  - native_app
  - browser
  - personal_stream
  - controller_only
```

Exact schema is not yet defined.

Important principle:
- game requirements must be machine-readable
- Avrana should not rely on hardcoded per-game special cases

---

# 18. Roles and Identity

Do not equate Party Host with Player 1.

Potential roles:

```text
Owner
Party Host
Player
Spectator
Administrator
Developer
```

One person may possess multiple roles.

Identity, seat, device, and controller should remain conceptually separate.

Example:

```text
Person: Cody
Role: Party Host + Player
Seat: 2
Device: iPhone
Controller: virtual-controller-2
Presentation: Personal Viewport
```

This avoids future coupling problems.

---

# 19. Optional Future Extension Runtime

## 19.1 Wasmtime

Project:
- Bytecode Alliance Wasmtime

Primary relevance:
- future low-risk extension system

Potential use cases:
- score processors
- trivia providers
- tournament rules
- procedural content
- lobby plugins
- controller translators
- lightweight automation

Potential benefit:
- WebAssembly modules can be given narrowly scoped capabilities
- safer than giving small extensions full Linux container access

Not recommended for immediate MVP work.

Long-term architecture possibility:

```text
Games / emulators
    → containers/processes

Small extensions
    → WASM
```

---

# 20. What Avrana Should NOT Reinvent

Avoid inventing custom implementations for:

- video codec pipelines when existing stacks satisfy requirements
- virtual gamepad primitives
- A/B operating system updates
- ACME
- package signing fundamentals
- package artifact storage
- basic multiplayer reconnection
- captive portal detection
- generic local-device discovery
- browser compatibility databases
- generic container/session isolation

These are infrastructure problems.

Use mature implementations where feasible.

---

# 21. What Avrana SHOULD Own

Avrana's differentiating engineering should remain concentrated in:

## Capability Engine

Question:

> What can this exact Party, game, network, runtime, and set of player devices accomplish right now?

---

## Seat Scheduler

Question:

> What execution path should each individual seat receive?

Example:

```text
Player 1 → native Avrana app
Player 2 → browser renderer
Player 3 → Personal Viewport stream
Player 4 → controller-only
```

without degrading the entire party.

---

## Game Contract

Question:

> What does this game require, support, prefer, and gracefully fall back to?

---

## Runtime Strategy

Question:

> Where should this player's game logic and pixels execute?

Possible answers:

```text
Party host
browser
native phone app
container
emulator
streamed virtual display
HDMI/shared TV
hybrid
```

---

## Party Lifecycle

Avrana must make the following feel ordinary:

```text
join
leave
reconnect
switch device
become host
spectate
join late
change game
change controller
lose WAN
recover WAN
```

Underlying runtime mechanics should remain invisible to guests.

---

## Offline Resilience

Core behavior must remain useful if the Internet disappears.

Avrana should know whether it has sufficient local material to maintain full functionality.

Possible future user-facing concept:

```text
Full Offline Reserve: 26 days
```

This could summarize:
- certificate validity
- cached runtime dependencies
- compatibility metadata
- recovery content
- package availability
- required app synchronization

Exact implementation is undecided.

---

# 22. Recommended Prototype / Spike Order

## Spike 1: Wolf + Gamescope
Goal:
- determine ARM/Pi compatibility
- inspect session model
- test virtual display behavior
- compare with current Avrana streaming prototype

Success question:

> Can Avrana treat Wolf as a replaceable session/runtime substrate?

---

## Spike 2: PartyPad + InputPlumber
Goal:
- compare with current custom `uinput` work
- prototype stable seat-to-virtual-controller mapping

Success question:

> Can Avrana stop owning low-level virtual input plumbing?

---

## Spike 3: Colyseus
Goal:
- build one intentionally trivial two-player Avrana-native game
- test:
  - reconnect
  - late join
  - private player state
  - host authority
  - browser suspension

Success question:

> Is Colyseus suitable as the session substrate for native Avrana games?

---

## Spike 4: openNDS
Goal:
- compare against current dnsmasq/nginx captive portal
- test:
  - iOS
  - Android
  - Windows
  - browser handoff
  - normal-browser launch behavior

Success question:

> Can openNDS own captive mechanics while Avrana owns UX?

---

## Spike 5: Rugix
Goal:
- create throwaway A/B image
- intentionally break an update
- verify automatic rollback
- test state persistence

Success question:

> Can Rugix own system-update safety?

---

## Spike 6: LocalSend-Inspired Courier
Goal:
- prototype Companion ↔ Party discovery
- deliberately break multicast
- test fallback methods
- transport arbitrary signed payloads

Success question:

> Can a phone reliably act as an offline courier under hostile LAN conditions?

---

## Spike 7: OCI/ORAS + TUF
Goal:
- package one fake Avrana game
- assign architecture metadata
- sign repository metadata
- download externally
- courier offline
- verify locally
- install

Success question:

> Can Avrana package distribution remain transport-independent and cryptographically verified?

---

## Spike 8: lego Certificate Courier
Goal:
- Party generates key + CSR
- CSR leaves Party
- internet-connected service obtains certificate
- certificate returns
- Party installs it
- private key never leaves device

Success question:

> Can Full Mode HTTPS be renewed through a Companion courier without exposing the Party's private key?

---

# 23. Licensing Guidance

Do not treat all open-source projects equally.

Before commercial integration, classify dependencies.

## Permissive candidates
Usually easier to integrate directly:
- MIT
- BSD
- Apache-2.0

Examples currently of interest:
- Wolf
- PartyPad
- Colyseus
- Rugix
- many OCI/ORAS components

## Copyleft candidates
Require deliberate architecture/legal review:
- GPLv3
- AGPL
- similar copyleft licenses

Examples currently requiring caution:
- Moonlight-Web
- InputPlumber

Possible strategies:
- run as independent processes
- communicate through stable APIs
- use as architectural reference
- avoid source incorporation into proprietary components
- replace later with clean implementations if needed

Licensing conclusions must be revalidated before commercial release.

---

# 24. Central Architectural Rule

Avrana Party must not become a monolith made from one-off integrations.

Preferred structure:

```text
Avrana Core
    |
    +-- Runtime Provider Interface
    |
    +-- Input Provider Interface
    |
    +-- Captive Portal Provider Interface
    |
    +-- Update Provider Interface
    |
    +-- Package Provider Interface
    |
    +-- Streaming Provider Interface
```

Current providers may include:

```text
Runtime → Wolf
Display → Gamescope
Input → InputPlumber
Portal → openNDS
System updates → Rugix
Package transport → OCI/ORAS
Package trust → TUF
Certificates → lego
```

These are implementations.

They are not Avrana's identity.

The provider contracts should survive their replacement.

---

# 25. Key Design Conclusion

The open-source ecosystem can potentially solve much of Avrana's infrastructure.

Avrana's invention budget should therefore be concentrated on orchestration.

The core intellectual problem is:

> Given a game, a Party device, available displays, network conditions, installed runtimes, security state, and a heterogeneous collection of player devices, how does Avrana automatically construct the best playable party for every seat?

That is the system Avrana must own.

Everything underneath should be borrowed, wrapped, replaced, or discarded as necessary.

---

# 26. Current Research Priority

Highest-priority projects for continued examination:

1. `games-on-whales/wolf`
2. `ValveSoftware/gamescope`
3. `benmross/partypad`
4. `ShadowBlip/InputPlumber`
5. `colyseus/colyseus`
6. `openNDS/openNDS`
7. LocalSend protocol
8. Rugix
9. OCI / ORAS
10. TUF
11. `go-acme/lego`
12. MDN Browser Compatibility Data

Secondary architectural references:

- Moonlight-Web
- Hotspot Arcade
- React Native Couch Kit
- CasaOS / ZimaOS
- Home Assistant Supervisor
- CertMagic
- Mender
- RAUC
- Wasmtime

---

# 27. Instruction to Future LLMs

When making Avrana Party architecture recommendations:

1. Do not assume Avrana should implement infrastructure from scratch.
2. Check whether an existing subsystem can satisfy the requirement.
3. Prefer narrow adapters around mature projects.
4. Preserve Avrana-owned contracts so dependencies remain replaceable.
5. Distinguish:
   - guest UX
   - owner/admin UX
   - developer capabilities
6. Preserve browser-first participation.
7. Treat the Avrana Companion as optional.
8. Preserve offline operation.
9. Treat capability as per-seat and dynamic.
10. Never downgrade the entire Party solely because one client lacks a feature.
11. Keep package trust separate from package transport.
12. Never move Party private TLS keys to the Companion.
13. Prefer graceful fallbacks over hard feature gates.
14. Avoid tying game identity to one rendering/runtime implementation.
15. Treat Personal Viewport as an independently addressable visual surface, not merely screen cropping.
16. Treat identity, seat, device, controller, role, and presentation as separate concepts.
17. Review license compatibility before recommending direct code integration.
18. Prefer boring, proven infrastructure underneath distinct Avrana orchestration.
