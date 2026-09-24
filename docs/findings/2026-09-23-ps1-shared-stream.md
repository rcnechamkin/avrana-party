# PS1 on one shared stream: state of proof, 2026-09-23

> **PS1 PERFORMANCE / MULTI-VIEWER LOAD TESTING BLOCKED:** Replace/verify Pi power first.
> After clean power is installed, confirm `get_throttled=0x0` from a fresh boot before
> repeating the staged test matrix (`2026-09-23-ps1-post-power-test-plan.md`).

Code: `ps1/` on local branch `ps1-emulation` (see `ps1/README.md`). Nothing has been pushed.
Evidence (untracked, on `party`): `~/avrana-lab/ps1/evidence/2026-09-23/`
(`lead-shots/`, `harness/`, `runtime-snapshot/` with `SHA256SUMS`),
`~/avrana-lab/ps1/screenshots/agentA-*.png`, and `/var/log/avrana/pi-throttle.jsonl`.

## Environment

- **Emulator:** RetroArch 1.20.0 (Debian trixie package, git b2ceb50), already installed for
  the arcade.
- **Core:** PCSX-ReARMed r26l-111-g94e8a03 (aarch64, ari64 dynarec, NEON GPU), from the
  official libretro buildbot over verified TLS (CN=libretro.com).
  - zip sha256 `e9d0494f…a59e`, .so sha256 `9b9b116a…af0c`
  - Provenance: `ps1/evidence/selected-core.json`. The launcher refuses a checksum mismatch.
- **BIOS:** `/srv/avrana/roms/psx/SCPH1001.BIN`, 512 KiB, md5 `924e392e…dccf` (SCPH-1001 v2.2,
  US).
  - The RetroArch log confirms the real BIOS: `found US BIOS file, crc32 37157331` and
    `BIOS: 19951204 'CEX-3000/1001/1002'`. HLE is not used.
- **Games:** Worms Armageddon (USA) SLUS-00888 and Bomberman Party Edition (USA) SLUS-01189.
  - Both are single-track bin/cue, MODE2/2352, and the cue `FILE` names match the bins. No
    conversion was needed.
  - Bomberman's bin SHA-1 matches the Redump value in its accompanying note.
- **Isolation:** all state lives in `~/avrana-lab/ps1/`: the core, a BIOS symlink,
  `saves/*.srm`, states, logs, and a private Pulse and Xvfb. Nothing was installed system-wide,
  and `arcade/` is byte-identical.

## Proven

**Worms**
- It boots on the real BIOS; the intro, menus and a match between two human teams all render
  (`lead-shots/worms/w01–w17`, `w-10min`).
- Audio is produced: RMS about 975 from the private null-sink monitor.
- It is hot-seat on port 1:
  - w14: P1 moves team 1's worm.
  - w15: the turn passes to team 2.
  - w16: the P2 key bank does nothing.
  - w17: P1's keys move team 2's worm.
- The session ran about 13 minutes (17:46–17:59), turns kept cycling, it exited with rc 0, and
  the `.srm` was written. No orphans were left.
- Monitoring covered about 8 minutes: AP interface up, dnsmasq running, nginx and LAN Games
  returning 200 throughout. No AP clients were connected, so this is interface state only.

**Bomberman (keyboard banks, no stream; Agent A)**
- `pcsx_rearmed_multitap = "port 2"` gives 5 human players (agentA-33).
  - Each of P1–P5 moved alone with its own bank (agentA-21…28).
  - Simultaneous 4- and 5-player presses all moved (agentA-26, 29).
  - The mapping was identical after a relaunch (agentA-41…45).
- `"port 1"` makes the game ignore all input (agentA-50…60).
- `"disabled"` leaves only P1 and P2 human (agentA-61…63).
- The log line `multitap: 0 1` confirms port 2. Mapping: RA user 1 = port 1 = P1, users 2–5 =
  2A–2D = P2–P5.

**Shared stream (`ps1/stream_ps1.py`)**
- It streams Bomberman from one capture, one v4l2h264enc and one opusenc.
  - A code review confirmed each viewer adds only appsrc, h264parse, an RTP payloader and
    webrtcbin, with no encoder. `/stats` used to hard-code `video_encoders=1`. It now counts
    the encoders actually present in every pipeline, which still needs a run on clean power.
- 4 player pages plus 1 spectator joined and got slots 1–4 plus a spectator, in connection
  order.
- Player 1's page drove the menus through the phone input path: title → main menu → Battle
  Game → Select Mode → Select Level → "Single? Tag?". The frames were decoded from the
  spectator's WebRTC video (`lead-shots/bomberman-stream/b01–b21`).
- Every "phone" was headless Chromium (Playwright) on the avrana mini-PC. No real handset has
  been used yet.

## Strongly indicated, not proven

- A single viewer got about 50 fps, about 970 kbps, 6 ms jitter and 0 loss (client-stats
  segment 18:17–18:19).
- In the final 4+1 run, each client saw about 44 fps, about 550 kbps, 0 loss, but a 69–121 ms
  jitter buffer and 19–26 freezes. The Pi was in recurring under-voltage and avrana was
  decoding 5 streams, so these numbers are not a performance baseline.
- Slot release after the 30 s grace period was seen in a server log that was later
  overwritten. The slot/token logic now has a unit test that runs anywhere
  (`ps1/tests/test_slots.py`).

## Not yet proven

- Players 2–4 each moving their own bomber from their own page, in the menus or in a match.
- Simultaneous multi-phone input in a match.
- Encode CPU at 1, 2 and 4 viewers, network throughput, and input-to-photon latency.
- Stability under streaming load: no streamed run lasted more than about 4.5 minutes.
- Any real iPhone or Safari.
- TV/HDMI mode (`mode-kms.cfg`).

**Exact stop point:** the final run started at 18:41:48, and peers joined from 18:42:29. P1
navigated to "Single? Tag?" at about 18:44. The Pi reset at about 18:44:40. The next steps
would have been Single Match, the rules screen, "How many players", characters, stage, then
per-phone movement.

## The reboot (Agent 4 audit)

- **Timing:** the reset was at about 18:44:05–18:44:55 PDT. The journal's 18:42 is a
  pre-NTP clock artifact.
- **Evidence:**
  - `rsts=0x20`, a watchdog-style reset. systemd `RuntimeWatchdogSec=1m` is armed.
  - `panic=0`, so a hang or panic would be reset by the watchdog.
  - ext4 orphan cleanup on boot, and `client-stats.jsonl` ends in NUL padding: an unclean
    stop.
  - Live under-voltage (`0x50005`) 7 times in the preceding 44 minutes, the worst hour in the
    log (0–3 per hour on earlier days, 0 earlier today). The last one was about 4 minutes
    before the reset.
  - "Undervoltage detected" again 15–20 s into the next boot, with no load running.
- **Ruled out:** thermal (peak 55.5 °C, no soft-temp or cap bits), OOM (it would kill a
  process, not reboot), and a deliberate reboot (dirty filesystem, session never logged out).
- **Verdict:** a power problem, then a hang, then a watchdog reset is most likely, at about
  75% confidence. A software hang or panic from another cause is about 15%. The pre-reset
  kernel log is lost because the journal is volatile.
- **Config:** stock apart from `arm_boost=1` (1800 MHz). `vcgencmd get_config` reports
  `over_voltage_avs=-20000`, but it is firmware-internal and not set in `config.txt` (corrected
  2026-09-23), so it is not an owner undervolt. `vcgencmd pmic_read_adc` is not available on this firmware, so the 5 V rail
  can't be read.
- **Recommended, not applied:**
  - persistent journald (`Storage=persistent`);
  - a 1 s throttle sampler with fsync during tests;
  - an inline USB-C power meter;
  - a known-good 5.1 V 3 A supply and a short cable, and a powered hub for the Realtek Wi-Fi
    dongle;
  - `kernel.panic=10`.

## Architecture review (Agent 2), and fixes applied without load

**Invariants that hold:** one capture/encode, and the same buffers fanned out. The slot comes
only from the server's token table, spectator and replaced sockets can't reach a pad, and
tokens are not exposed in `/stats`.

**Applied (syntax-checked, slot logic unit-tested, not yet run against a live stream):**
1. The rate budget now covers every message type, including stats and ICE.
2. The aiohttp access log is off, so `?token=` can't leak.
3. Non-ASCII tokens no longer raise, and any failure after a claim releases the slot.
4. A takeover's old socket no longer clears the new owner's buttons.
5. The per-peer `ip` subprocess, which blocked the event loop, is now resolved once.
6. `/stats` is localhost-only, because it carries peer IPs.

**Open:**
- Disconnect should free the slot immediately (close code 4000), instead of after the 30 s
  grace. This needs a phone check.
- Drop IP addresses from `client-stats.jsonl`.
- Don't bind the home LAN except for tests.
- Keep `arcade/stream.py` frozen or smoke-test PS1 against it, because `stream_ps1.py` relies
  on its internals.

## Bugs found and fixed during bring-up

- **Orphans on SIGTERM:** `run-ps1.sh` cleanup aborted under `set -e` on a `wait` for a
  grandchild, leaving PulseAudio behind. Fixed with `set +e`, polling, and removal of a stale
  Pulse on launch.
- **Orphans on crash:** a failed server startup skipped aiohttp's cleanup, and a server crash
  or SIGKILL left RetroArch running. Fixed with try/cleanup and `PR_SET_PDEATHSIG` (verified
  with SIGKILL).
- **Over-strict rate limit:** it closed sockets (1008) when network or tunnel bursts delivered
  several seconds of heartbeats at once. It now drops messages; only more than 1200/s closes.
- **Self-inflicted segfault:** reading webrtcbin's `ice-agent` from Python freed the ICE
  object. Reverted. The server now runs with `-X faulthandler`.
- **Stats crash:** `/stats` crashed on spectators because `slot` was None. Rewritten.
- **Wrong assumption about the arcade display:** PS1 is not guaranteed `:99`. With the arcade
  stopped, `xvfb-run -a` handed out `:99`.
