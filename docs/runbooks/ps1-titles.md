# Runbook: PS1 titles, what remains for the owner (AVR-309)

Status: **OWNER CHECKLIST, NOT RUN** (2026-10-07). No step here is authorized by this document.

Nothing in CI, in an agent's task or in this file authorizes anything on the Pi: deploying, restarting or
stopping a service, stopping the production arcade, editing nginx, granting a game, or running an
emulator is the owner's decision and the owner's action. Written from source; no step was run on any
device. Tick a box only for something you did yourself.

## Where things stand

What AVR-309 put on `main` (see [ps1/README.md](../../ps1/README.md)): the two title profiles and the
core pin as data, a strict loader that proves a profile equals its Game Contract, deterministic
RetroArch configuration, a check of the owner's content, and an XTest input provider, proven by fixture
tests with synthetic bytes. **Nothing launches.** There is no PS1 service, unit, route, appliance grant,
Party Core key or phone page, and the catalog still lists both titles as experimental and not installed.

The decisions that the steps below depend on are not made here. They are on Linear
[AVR-310](https://linear.app/avranakern/issue/AVR-310): where the content and the core live and what the
configuration names are, the route, the button sets and hot-seat semantics, the "content missing"
wording, the priority against V1.0 (the draft intent excludes PS1 from the night), and the default
resolution.

Steps 1 and 2 only read files and are safe on a laptop. From step 3 on, a step changes the appliance and
waits for its decision.

## Checklist

### 1. Where the owner's content and the core live (AVR-310, decision 1)

- [ ] Content root: a read-only folder outside every repository and every release tree. The BIOS image
  `SCPH1001.BIN` (exactly 524288 bytes) sits directly in it, and each disc folder is laid out as its
  profile's `cue` says (`ps1/titles/<id>.json`, relative to the root). The images are the owner's own.
- [ ] The core: the pinned `pcsx_rearmed_libretro.so` build for the machine that will run it (aarch64 on
  the Pi), also outside every repository.
- [ ] The configuration names. This repository reads `AVRANA_PS1_CONTENT` and `AVRANA_PS1_CORE`; they are
  provisional, and AVR-310 may rename them.

### 2. Content and core pin check (read-only)

```bash
export AVRANA_PS1_CONTENT=<content root>
export AVRANA_PS1_CORE=<path to pcsx_rearmed_libretro.so>
python3 -m avrana.providers.ps1 check bomberman
python3 -m avrana.providers.ps1 check worms
```

- [ ] `bomberman` exits 0 and reports every check passed.
- [ ] `worms` exits 0 and reports every check passed.

The command looks at the cue sheet and every file it names, the BIOS size and the core's SHA-256, and
prints one line each. It reads the cue sheet and the core only (it never opens a disc image or the BIOS)
and never prints an absolute path. Each failure has its own code, so the line says what to fix:

| Code | Means | What to do |
|---|---|---|
| `content_root_unset` | no content root was given | set `AVRANA_PS1_CONTENT` or pass `--content` |
| `content_root_missing` | the content root is not a folder | correct the path |
| `unreadable` | the user running the check may not look at a file or folder | give that user read access (read-only is enough) |
| `cue_outside_root` | the profile's cue path resolves outside the root, or loops, through links | replace the link with the real folder under the root |
| `cue_missing` | the cue sheet is not at the profile's path | lay the disc folders out as the profile's `cue` says |
| `cue_invalid` | the cue sheet is not UTF-8 text, is over 1 MiB, or names more than 99 files | use the disc's own cue sheet |
| `cue_no_files` | the cue sheet has no `FILE` line | use the disc's own cue sheet |
| `bin_unsafe` | a `FILE` line is absolute or climbs out of the disc folder | fix the cue sheet so the images sit in its folder |
| `bin_missing` | a file the cue sheet names is not there | put the image next to the cue sheet under exactly the name it states |
| `bios_missing` | `SCPH1001.BIN` is not in the content root | place the BIOS image there |
| `bios_wrong_size` | the BIOS image is not 524288 bytes | a PS1 BIOS image is 512 KiB; replace it |
| `core_unset` | no core was given | set `AVRANA_PS1_CORE` or pass `--core` |
| `core_missing` | there is no file at the core path | correct the path |
| `core_pin_invalid` | the repository's `selected-core.json` is unusable | a repository problem, not the content: report it |
| `core_hash_mismatch` | the core is not the pinned build | install the pinned build; do not edit the pin |

- [ ] **Core pin verification:** `sha256sum "$AVRANA_PS1_CORE"` equals `so_sha256` in
  [`ps1/evidence/selected-core.json`](../../ps1/evidence/selected-core.json); the check above compares the
  same two values. If they differ, do not edit the pin to make the check pass. The libretro buildbot's
  "latest" file changes over time: a different build is a new core to validate on the Pi first and to
  re-pin deliberately, in its own change.

### 3. The unit (AVR-310, decision 2)

- [ ] The unit or drop-in that runs the emulator and its stream is decided, written and reviewed. The donor
  ran a foreground process of the operator account; ADR 0016's native-game unit (`avrana-game@.service`,
  behind an AF_UNIX socket) is the model for service identity, keys and state directories, and AVR-310
  records that WebRTC, X11 and the hardware encoder cannot live inside it. Follow
  [ADR 0016](../adr/0016-service-identities-and-local-trust-boundary.md) for whatever is decided, and
  [provision-game](provision-game.md) where it applies. Owner-merge class (`deploy/`).
- [ ] The unit is installed on the Pi by the owner.

### 4. The route (AVR-310, decision 2)

- [ ] A new nginx `/ps1/` location (the arcade pattern) or a profile mode inside the arcade service is
  chosen. The two nginx site files (`avrana-party.nginx`, `arcade/nginx-site`) stay byte-identical, edited
  by tool. Owner-merge class; the owner reloads nginx.

### 5. The grant

- [ ] An appliance grant for each title in `contracts/appliances/avrana-pi4.json` (an `installed` entry with
  its `runtime`), and the `xtest-keys` provider's `adapter` set to
  `avrana.providers.ps1:XTestKeysProvider` (it is `null` today). The catalog snapshot is regenerated
  (`npm run catalog`), with "content missing" as its own catalog state (AVR-310, decision 4). Both titles
  stay `experimental` until the real-phone test below has passed. A contract change: the owner merges.

### 6. The Party Core games entry and key

- [ ] A Party Core games entry and a per-game key for each title (`/etc/avrana-party/games.d`, the key
  store under `/etc/avrana-party/game-keys`), made the way [provision-game](provision-game.md) makes them
  for a native game: the key is never printed, committed or pasted. The donor's HMAC seat tickets are not
  used; the follow-up uses the current ticket and bridge model.

### 7. The arcade stopped during PS1 runs

- [ ] Before any emulator run, the production arcade is stopped by the owner (`sudo`) and started again
  afterwards. Gauntlet II uses about 1.4 to 1.7 cores with nobody playing, and with it running the
  donor's emulator reached only about 35 percent speed at 640×480 and 40 to 44 frames per second at
  320×240 with five viewers ([finding](../findings/2026-09-24-ps1-bomberman-party-slice.md)). That
  stopping it fixes this is the finding's expectation, not something verified. A run is bounded and
  supervised, and never overlaps a power measurement.

### 8. The real-phone test (Tier 3)

- [ ] Both titles are played on real phones on the party Wi-Fi with the arcade stopped, and the result is
  recorded as a **new** dated finding (the 2026-09-24 findings are history and are not edited). Record at
  least: that each phone moves only its own player; that the seat Party Home shows matches the player;
  sound on each phone and whether it keeps up with the picture; input feel; what a 30-second lock and
  unlock does; that ending the game takes everyone home; Worms as hot-seat; the power state
  (`get_throttled`) at the end. The last real-iPhone playtest showed stalls of up to 2.2 seconds
  ([latency finding](../findings/2026-09-24-ps1-latency.md)); its Wi-Fi power-save test is the finding's
  recommended next step, and this repository has no record that it ran.
  The experiment-only [2026-09-24 procedure](ps1-bomberman-party-test.md) used the donor's own join page,
  not Party Core; reuse its table of what to record, not its steps.

## Never

A ROM, BIOS image, core, save, save state, memory card or any other owner content, or a path into the
owner's content, goes into this repository, a pull request, a Linear issue or a log. A report from the
content check names files relative to the content root; keep it that way when copying it.
