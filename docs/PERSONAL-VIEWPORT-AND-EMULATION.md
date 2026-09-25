# Avrana Party — Personal Viewport, User-Imported Games, and Emulation

> **Status: design direction.** The PS1 and viewport work remains on experiment branches.
> Read `ROADMAP.md` and `design/PERSONAL-VIEWPORTS.md` for current status.

## Purpose

This document defines the current architecture and design direction for:

- user-imported legally obtained game content
- emulator-based gameplay
- browser-side emulation
- native-app emulation
- Avrana-hosted emulation/streaming
- distributed synchronized emulation
- Personal Viewport

It is intended primarily for LLMs and future engineering agents.

Do not assume that emulation is the core commercial product. It is an advanced capability that should coexist with a simple consumer experience.

---

## Product Philosophy

Avrana Party must remain accessible to nontechnical users.

Normal experience:

```text
Join
Choose game
Play
```

Advanced users should be allowed deeper control without forcing complexity on everyone else.

Possible Advanced Library features:

- import user-owned game dumps
- manage emulator cores
- homebrew
- compatible community packages
- advanced controller mapping
- emulator settings
- performance telemetry
- Personal Viewport profiles
- manual compatibility overrides

The presence of these features must not make ordinary operation more complicated.

---

## Legal/Product Boundary

Preferred commercial posture:

- Avrana Party should not ship copyrighted commercial ROMs/ISOs without proper licensing.
- The system may provide emulator runtimes where legally and license-wise appropriate.
- Users may be allowed to import their own game content where they have the legal right to do so.
- Package/license handling must distinguish emulator code from user-supplied game data.
- Do not phrase the platform as a piracy tool.

Exact legal policy requires later legal review.

---

## Core Execution Principle

**Execution belongs wherever it is cheapest and most capable.**

For an imported game, multiple execution paths may exist.

### Path A — Browser-Local Emulation

```text
Avrana stores:
- game data
- emulator runtime

Phone downloads both
      ↓
browser executes emulator locally
```

Avrana Party primarily handles:

- package delivery
- seat/session coordination
- synchronized input
- save-data coordination
- compatibility metadata

Good candidate for older systems where browser/WASM emulation is mature.

---

### Path B — Native Avrana App Emulation

```text
Avrana Party
      ↓ local transfer
Avrana App
      ↓
native emulator runtime
      ↓
phone executes game locally
```

Potential advantages:

- greater native performance
- more direct controller integration
- fewer browser secure-context constraints
- better storage control
- potentially more capable emulator runtimes
- better background/reconnect behavior

This path is especially important for more demanding systems.

---

### Path C — Avrana-Hosted Emulation + Per-Seat Streaming

```text
Avrana Party runs emulator
      ↓
extracts player viewport
      ↓
encodes player-specific stream
      ↓
phone receives video + sends input
```

Advantages:

- client does little compute
- supports weaker/browser-only clients

Disadvantages:

- expensive central CPU/GPU/encoder usage
- per-seat encoding cost
- latency sensitivity
- lower scalability

Use as fallback when local execution is unavailable.

---

### Path D — TV Mode

```text
Avrana Party runs emulator
      ↓ HDMI
TV/shared display

Phones:
- controllers
- optional private secondary information
```

This is likely the simplest path for many traditional couch-multiplayer games.

---

## Mixed Execution Parties

Different players may use different execution paths in the same session.

Example:

```text
Seat 1: native app local emulation
Seat 2: native app local emulation
Seat 3: browser local emulation
Seat 4: Avrana-rendered fallback stream
```

The session should still represent one logical multiplayer game.

The weakest client should not force every player onto the fallback path.

---

## Synchronized Local Emulation

For selected systems/games, every capable phone may run a synchronized copy of the same console game.

Conceptual model:

```text
Phone A runs whole game
Phone B runs whole game
Phone C runs whole game
Phone D runs whole game

Avrana coordinates:
- identical game hash
- emulator/core version
- deterministic settings
- seat mapping
- synchronized inputs
- session start/state
```

This can radically reduce Avrana Party processing load.

The Avrana device becomes coordinator rather than renderer.

---

## Determinism Constraints

Synchronized emulation can fail if instances diverge.

Potential causes:

- emulator version mismatch
- game hash mismatch
- architecture/JIT differences
- graphics backend differences
- timing differences
- optional patches/cheats
- nondeterministic emulator behavior
- inconsistent settings

Therefore Avrana should never simply assume that “same ROM” means compatible.

Potential compatibility metadata:

```yaml
game_hash:
emulator_core:
core_version:
required_settings:
supported_architectures:
known_good_devices:
known_bad_devices:
netplay_mode:
```

Compatibility must eventually be tested empirically per system/game.

---

## N64 Direction

N64 is a strong candidate for local phone-side execution.

Reasons:

- modern phones greatly exceed N64 hardware capability
- mature emulator technology exists
- browser/WASM may be feasible for many titles
- native mobile execution should be even more capable

N64 should be considered a priority proof target for Personal Viewport and distributed execution.

Mario Kart 64 is a particularly useful conceptual reference because it combines:

- full-screen menus
- shared character/course selection
- split-screen gameplay
- full-screen/shared results
- multiple player layouts

Do not assume compatibility until tested on actual target devices.

---

## GameCube/Wii Direction

GameCube/Wii are more demanding.

Native mobile execution is more realistic than browser execution.

Potential concerns:

- CPU/GPU demand
- JIT requirements
- device thermal limits
- architecture differences
- emulator determinism
- per-game compatibility
- controller complexity
- motion-control expectations for some Wii titles

The platform should support these systems opportunistically rather than promise universal compatibility.

---

## Personal Viewport: Core Goal

Traditional split-screen games render all players into one framebuffer.

Avrana Personal Viewport should allow each player to see only their own section during gameplay while still showing full-screen shared interfaces when appropriate.

Desired behavior:

```text
Main menu
→ everyone sees full frame

Character select
→ everyone sees full frame

Race/gameplay begins
→ each player sees only personal viewport

Results screen
→ everyone sees full frame
```

A naive permanent crop is unacceptable.

---

## Personal Viewport Is a State Problem, Not Only an Image-Cropping Problem

Avoid:

```text
4 players = always divide frame into four
```

This would break:

- title screens
- character select
- map/course select
- shared menus
- cutscenes
- results screens
- pause screens

Personal Viewport needs to determine whether the current game state is:

- shared full-screen
- personal split-screen
- other special layout

---

## Detection Hierarchy

Preferred detection order:

### 1. Known Game Profile

Best option.

A per-game profile knows relevant game states and layouts.

Potential information sources:

- emulator memory addresses
- known state flags
- player-count values
- framebuffer layout
- known render behavior
- timing/state transitions

Example conceptual profile:

```yaml
game: mario_kart_64

states:
  main_menu:
    viewport: full

  character_select:
    viewport: full

  course_select:
    viewport: full

  race_2p:
    viewport: split_2

  race_3p:
    viewport: split_3

  race_4p:
    viewport: split_4

  results:
    viewport: full
```

---

### 2. Emulator/Runtime Signals

If no handcrafted profile exists, inspect emulator/runtime information.

Potential signals:

- viewport commands
- framebuffer regions
- render targets
- camera count
- scissor rectangles
- split render passes
- game-state callbacks
- emulator debugging information

This is preferable to pure computer vision when available.

---

### 3. Visual Split Detection

Fallback.

Possible techniques:

- persistent divider detection
- duplicated HUD structures
- multiple independent camera regions
- repeated screen-edge patterns
- temporal analysis across frames
- confidence scoring over time rather than one-frame decisions

Do not switch layouts on a single uncertain frame.

Visual detection should use hysteresis/confidence to avoid flicker.

---

### 4. Manual Override

Advanced users should be able to teach Avrana.

Possible options:

```text
Full screen
2-player split
3-player split
4-player split
Automatic
```

The platform may save the override/profile for that game.

Manual control is preferable to an unreliable “smart” system with no escape hatch.

---

## Personal Viewport Profile Storage

Profiles should be independent of execution method.

One profile should be reusable by:

- browser local emulation
- native-app emulation
- central Avrana emulation
- streamed fallback
- potentially TV companion displays

Conceptually:

```text
game/emulator state
      ↓
Personal Viewport policy
      ↓
seat-specific output rectangle
```

The rendering mechanism changes.

The viewport decision should not.

---

## Local Emulation + Personal Viewport

When every phone runs the full emulated game:

```text
full emulator framebuffer
        ↓
local Personal Viewport policy
        ↓
crop/scale appropriate seat region
        ↓
display full-screen on phone
```

During shared menu states, the phone displays the entire framebuffer.

During split gameplay, it expands the player-specific region to the whole phone display.

This preserves normal game logic while producing a better per-player experience.

---

## Central Fallback + Personal Viewport

If a browser-only or weak client cannot emulate locally:

```text
Avrana emulator
      ↓
full framebuffer
      ↓
Personal Viewport policy
      ↓
crop seat region
      ↓
encode only needed output
      ↓
stream to that seat
```

This allows mixed parties.

Example:

- three native-app seats execute locally
- one browser seat receives one centrally rendered personal stream

This is significantly cheaper than centrally rendering/encoding four seats.

---

## Shared Menu Synchronization

All seats should transition between shared and personal views consistently.

The session authority should be able to distribute Personal Viewport state:

```text
viewport_mode = FULL
```

or:

```text
viewport_mode = PERSONAL
layout = SPLIT_4
```

For distributed emulation, each phone may also derive the state locally, but authoritative synchronization may help prevent mismatched presentation.

---

## Imported Game Identification

When users import game content, Avrana should attempt to identify it using hashes and metadata.

Potential uses:

- identify title/system/revision
- select emulator/core
- select known compatibility profile
- select Personal Viewport profile
- verify deterministic netplay compatibility
- apply recommended settings
- warn about unsupported revisions

Do not rely only on filenames.

---

## User Experience

Normal consumer:

```text
Mario Kart 64
4 players
Play
```

Possible Advanced details:

```text
Execution:
3 local / 1 streamed

Core:
N64 Emulator X

Viewport:
Known profile

Game hash:
verified

Sync:
healthy

Average input latency:
12 ms
```

Expert information should be available without appearing in the default interface.

---

## Failure/Degradation Examples

### Phone too weak

Fallback to Avrana-rendered stream if capacity allows.

### Browser lacks secure context

Use native app if available.

Otherwise use HTTP-compatible browser execution or central fallback.

### Emulator compatibility failure

Move affected seat to central streaming.

### Personal Viewport detection uncertain

Temporarily show full framebuffer or use manual/known safe fallback.

### Avrana lacks encoder headroom

Reduce fallback seats, resolution, frame rate, or mark that execution path unavailable.

The capability scheduler decides.

---

## Important Open Questions

1. Which N64 emulator/runtime is best suited to browser-local execution?
2. Which native mobile emulator strategy best fits the future Avrana app?
3. What legal/license constraints apply to bundling emulator cores?
4. How deterministic are target emulators across ARM/iOS/Android?
5. Can N64 Personal Viewport states be detected reliably from emulator/game state?
6. Can split-screen render regions be extracted before final composition instead of cropping completed frames?
7. What per-seat compute cost exists for central fallback?
8. How should save states/saves synchronize across devices?
9. How should imported game profiles be distributed or shared?
10. Should community-created Personal Viewport profiles eventually be supported?

---

## Near-Term Proofs

Priority experiments:

1. run an N64 emulator on the target iPhone class
2. test phone-local four-player synchronized execution
3. confirm identical game hash/settings requirements
4. implement manual Full vs 4-way Personal Viewport switching
5. detect gameplay/menu state for one known title
6. prove one player can use central streaming while others execute locally
7. measure Avrana CPU/GPU/encoder load for the mixed case
8. measure end-to-end input latency for each execution method

---

## Strong Current Principles

- Advanced emulation must not complicate normal Avrana use.
- User-supplied game data and emulator runtimes are separate concerns.
- Prefer client-side execution when client hardware can do the work.
- Mixed execution within one party is valid.
- Personal Viewport is a state-aware presentation system, not a permanent crop.
- Known game/emulator state beats computer vision.
- Computer vision should be a fallback.
- Manual override should always exist for advanced users.
- One Personal Viewport model should serve every execution path.
