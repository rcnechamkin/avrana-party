# PS1 on Avrana Party (RetroArch + PCSX-ReARMed)

> **Status (2026-09-24 night):** the supervised stage passed on clean power (7 bounded runs, `0x0`,
> 0 kernel dips); 4 phone slots proven independent in a real Bomberman match; the party can launch
> Bomberman from Party Home with seat tickets. **The limit is CPU:** with the live arcade running,
> the emulator gets ~65-70% speed at 5 viewers. Findings and numbers:
> `docs/findings/2026-09-24-ps1-bomberman-party-slice.md` (branch `docs/party-platform`); real-phone
> runbook: `docs/runbooks/ps1-bomberman-party-test.md` (same branch). Runs stay bounded and
> supervised (`tools/supervised-run.sh`); no unattended runs, soak or viewer scaling past 5 without
> the owner.

Two PS1 games run through one shared stream:

- Worms Armageddon (USA), SLUS-00888
- Bomberman Party Edition (USA), SLUS-01189

## Model: video shared, input individual

```
RetroArch + PCSX-ReARMed ── private Xvfb ── ximagesrc ── ONE v4l2h264enc ─┐
          ▲                 private Pulse ── pulsesrc ── ONE opusenc ─────┤ same encoded
          │ XTest key banks                                               │ buffers
   stream_ps1.py ◄── WebSocket input (per phone) ── phone N  ◄── webrtcbin ┘ per viewer
```

- **One emulator, one capture, one encode.** `stream_ps1.py` reuses `arcade/stream.py`
  (imported, unchanged) for the capture/encode/fanout. Each viewer gets `appsrc →
  h264parse/rtph264pay → webrtcbin`. That is payloading plus DTLS/SRTP, with no encoder.
- **Each phone owns at most one controller slot.** The server assigns the lowest free slot
  and a random token. The client stores the token in localStorage and uses it to reclaim the
  same slot within 30 s of a disconnect. Phones that join when every slot is taken, or that
  choose Watch, are spectators, and their input never reaches a pad. The first message on every
  socket is `{type:'hello', role:'play'|'watch', token}` (5 s deadline, otherwise closed with 1008):
  the token never appears in a URL, so it can't reach an access log.
- **The client only sends `{type:'state', b:<14-bit mask>, seq}`.** Bits, in order: up, down,
  left, right, cross, circle, square, triangle, L1, R1, L2, R2, start, select.
  - The server replays the mask as XTest key events from that slot's fixed key bank (`BANKS`
    in `stream_ps1.py`, which must match `mode-xvfb.cfg`), into the PS1 instance's private
    display only.
  - No input devices are created. The live arcade RetroArch hot-plugs any new uinput
    joystick into Gauntlet P3/P4, so uinput is avoided while the two can co-run.
  - Safety rules: 40 ms minimum hold (RetroArch polls once per frame), release after 300 ms
    without a snapshot, release on disconnect/takeover/expiry, strict mask/seq validation,
    per-socket rate budget (drop above 120 msg/s, close above 1200 msg/s), and the arcade's
    Origin check.
- **Slot mapping (RetroArch user = slot):**
  - Worms: 1 slot. The game is hot-seat on port 1, and the teams take turns.
  - Bomberman: 4 slots, with the Multitap on **port 2**: user 1 is port 1 (in-game P1), and
    users 2–4 are Multitap pads 2A–2C (P2–P4). User 5 is 2D, unused by the stream.

## Two ways to run it

- **Standalone** (tests): `tools/supervised-run.sh <title> <seconds> [stream args]` — the stream binds
  10.42.0.1 (+ any `--host`), first-come slots with a reclaim token.
- **In a party** (the product path): the dev front door (`experiments/party-service/front.py --ps1
  <this folder>`, branch `experiment/party-service`) starts `stream_ps1.py <title> --host 127.0.0.1
  --capture 320x240` when the host picks the title, proxies only `/ps1/<title>/` and its `ws`, and
  stops it when the game ends. **Party mode** is on when `AVRANA_SEAT_KEY` is in the environment: a
  slot comes only from a seat ticket (`v1.<slot>.<exp>.<game>.<hmac>`, sent in the hello; the page
  fetches its own from `/party/state`), first-come is off, and the page goes back to Party Home when
  the party's game changes.

Stream options: `--capture WxH` (default 640x480; **use 320x240**, the PS1 native size — the grab and
colour conversion cost ~4x less), `--viewports split2|quad` (experiment: each slot gets a crop of the
shared frame in its `player` message; the page crops client-side). Launcher env:
`AVRANA_PS1_CAPTURE`, `AVRANA_PS1_SHOW_FPS=1` (RetroArch draws its real FPS into the picture — the
reliable speed meter). Each viewer costs ~14% of a core (its own payload + SRTP); capture + encode
~20% in total.

## Files

| File | Purpose |
|---|---|
| `run-ps1.sh <title> [retroarch args]` (titles: `python3 profiles.py list`) | Preflight (core checksum, BIOS, cue/bin), single-instance lock, private Pulse + Xvfb, RetroArch; cleans up on exit/SIGTERM |
| `launch-worms-ps1.sh`, `launch-bomberman-ps1.sh` | Thin wrappers around `run-ps1.sh` |
| `stop-ps1.sh` | SIGTERMs the running PS1 RetroArch, which flushes the memory card. Signals nothing unless `tools/ps1-pid.sh` proves the identity |
| `tools/ps1-pid.sh` | The one identity check every tool uses before trusting `runtime/retroarch.pid` or `runtime/display` (see below). Exit 0 = proven (PID on stdout), 1 = no live instance, 2 = not proven |
| `stream_ps1.py <game> [--host A]... [--port 8198]` | Shared-stream server: spawns `run-ps1.sh`, then capture/encode/fanout plus slot-owned input |
| `index.html` | Phone page: PS1 pad, Play/Watch, stats |
| `retroarch.cfg` | Base config template (`@PS1_HOME@`), isolated from `arcade/retroarch.cfg` |
| `mode-xvfb.cfg` | Headless mode: private Xvfb, Pulse null sink, X keyboard banks per user, hotkeys gated behind scroll_lock, joypads pinned to a nonexistent index |
| `mode-kms.cfg` | TV mode via KMS/ALSA/udev pads. **Untested** (no HDMI display attached) |
| `titles/<title>.json` | **Title profiles** (data only): cue path relative to the ROM folder, RetroArch users, stream slots, Multitap setting, notes |
| `profiles.py` | Loads and validates profiles against an allowlist (only hardware-verified values; no raw RetroArch keys) and GENERATES `runtime/core-options.opt` and `runtime/game.cfg` on every launch |
| `evidence/selected-core.json` | Core provenance and pinned sha256 (the launcher refuses a mismatch) |
| `tools/` | Test tools: `supervised-run.sh` (bounded run + power guard + verdict), `phones.mjs` (laptop simulated phones: presses, screenshots, metrics, leave/reload, per-phone crops), `xkeys.py` (keys into the private display), `shot.sh`, `audio-level.sh`, `monitor.sh`, `viewers.py` (older Python simulated phones) |

## Where things live (never in git)

- Game images and BIOS (read-only): `/srv/avrana/roms/psx/`
  - BIOS: `SCPH1001.BIN`, 512 KiB, md5 `924e392ed05558ffdb115408c263dccf` (SCPH-1001 v2.2, US)
  - Games: single-track bin/cue, MODE2/2352; the cue `FILE` names match the bins, so no conversion was needed
- State: `~/avrana-lab/ps1/` (override with `AVRANA_PS1_HOME`)
  - `cores/pcsx_rearmed_libretro.so` (buildbot, see `evidence/selected-core.json`)
  - `system/scph1001.bin` → symlink to the BIOS
  - `saves/<game>.srm`: memory card (`pcsx_rearmed_memcard2 = none`)
  - `states/`: save states (none are made automatically)
  - `runtime/`: generated cfg/opt, logs (`logs/<game>-latest.log`), Pulse socket, pid/display/xauthority files, lock
  - `screenshots/`, `evidence/`

## Process identity (never trust a bare PID)

The live arcade RetroArch is also called `retroarch`, and a crash or reboot leaves
`runtime/retroarch.pid` and `runtime/display` behind. The display number can then belong to the
arcade's Xvfb (`:99`), and the PID can belong to the arcade's RetroArch. So `run-ps1.sh` records
`PID STARTTIME BOOT_ID` (written atomically, last), and `tools/ps1-pid.sh` returns the PID only if
all of these hold:

- the boot ID matches the current boot, and the process start time matches (so the PID was not reused);
- `comm` is `retroarch`, the process is owned by this user, and one of its arguments is exactly
  `$AVRANA_PS1_HOME/runtime/retroarch.cfg` (the arcade uses `arcade/retroarch.cfg`);
- `runtime/display` and `runtime/xauthority`, when present, equal that process's own `DISPLAY` and
  `XAUTHORITY`.

Otherwise it refuses, and callers fail closed: `stop-ps1.sh` signals nothing (exit 1 when something
unproven is at the recorded PID), `shot.sh` and `xkeys.py` refuse to pick a display, `monitor.sh`
reports the emulator as `-`, and `run-ps1.sh`'s cleanup re-checks the identity before each signal.
`stream_ps1.py` also requires the proven process to be in the session of the `run-ps1.sh` it started,
and it never deletes runtime files itself (`run-ps1.sh` does that under the lock).

## Setup on a fresh Pi

```sh
sudo apt install retroarch          # Debian trixie: 1.20.0 (already installed on party)
mkdir -p ~/avrana-lab/ps1/cores && cd ~/avrana-lab/ps1/cores
curl -O https://buildbot.libretro.com/nightly/linux/aarch64/latest/pcsx_rearmed_libretro.so.zip
unzip pcsx_rearmed_libretro.so.zip && sha256sum pcsx_rearmed_libretro.so   # must match evidence/selected-core.json
```

The buildbot "latest" file changes over time. If the checksum differs, record the new build
in `evidence/selected-core.json` deliberately rather than bypassing the check.

## Commands

```sh
cd ~/avrana-lab/avrana-party-docs/ps1          # the dev clone; not the deploy checkout
./launch-worms-ps1.sh                          # headless (no HDMI): private Xvfb, keyboard banks
./launch-bomberman-ps1.sh --max-frames=1800 --max-frames-ss --max-frames-ss-path=/tmp/b.png
./stop-ps1.sh
python3 -X faulthandler stream_ps1.py bomberman   # phones: http://10.42.0.1:8198/
curl -s 127.0.0.1:8198/stats                   # measured encoder count, slots, peers, capture age (localhost only)
```

The BIOS check: `grep -E "found (US|EU|JP) BIOS|No BIOS|HLE" ~/avrana-lab/ps1/runtime/logs/<game>-latest.log`
should print `found US BIOS file, crc32 37157331`.

Bomberman menu path: title Start → Down to BATTLE GAME, then **Cross** (Start does not confirm
in menus) → Battle Royal → Beginner → Single Match → rules (Cross) → "How many players" (all
slots Human by default) → characters → stage. Transitions load from the emulated CD and take
several seconds, and presses during a fade are ignored.

## Known issues

- Headless rendering is software GL (llvmpipe) in Xvfb: about 1.2 cores for RetroArch alone.
  A real HDMI/KMS session would use the GPU instead. This is untested.
- Viewer cost on clean power: ~14% of a core per viewer; with the live arcade co-running, 5 viewers leave the emulator at ~65-70% speed (stop the arcade for real play).
- The live arcade must be stopped for PS1 play with physical/uinput pads, because it
  hot-plugs them. The XTest path used by the stream does not have this problem.
- Worms is hot-seat: one controller slot, and everyone else watches.
- `stream_ps1.py` duplicates about 100 lines of `arcade/stream.py`'s per-peer setup. Fold both
  into a `Profile` refactor of `stream.py` later, keeping the arcade byte-identical until it
  is re-verified.
