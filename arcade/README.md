# Avrana Party Gauntlet II streaming prototype

> **Network note (2026-09-24):** mentions below of `wlan1` as the party AP and `wlan0` as the
> home/management link are from before the USB Wi-Fi adapter was removed. Today the AP is the internal
> `wlan0` (`10.42.0.1`) and management is `eth0` (`docs/runbooks/network.md`). Side effect: `/stats`
> labels every peer's path `other` because `ap_addresses()` looks for `wlan1`; the fix (find the AP
> by its address) is on branch `fix/arcade-ap-interface`, not merged or deployed. Streaming itself
> is unaffected.

## Current state (updated 2026-09-19)

Phone entry: **http://party.local/arcade/**. LAN Games remains at http://party.local/.
The isolated `avranaparty-arcade.service` is enabled at boot and running as cody.

- **Players:** `MAX_PLAYERS = 2` in `stream.py`, so two slots are enabled. P1 is
  verified for basic gameplay and streaming on a real iPhone. **Two-phone
  behavior (independent slots, simultaneous play) is not verified.** Do not raise
  beyond 2 until a two-phone test passes.
- **Measurement:** input-to-photon latency and performance under real gameplay
  have **not** been formally measured.
- **Boot:** service startup after a reboot is verified (all services active,
  arcade 0 restarts). Phone-side behavior after a boot is not verified.

One RetroArch process runs MAME 2010 (`0.139 dff8aad`). One GStreamer
`v4l2h264enc` uses /dev/video11 to encode the 640x480 display at 60 fps.
Encoded H.264 and one Opus audio encode feed bounded, nonblocking appsrc queues
in independent WebRTC transport pipelines. Adding a transport does not instantiate
another emulator or encoder. Multi-phone resource scaling remains unmeasured.
No public STUN/TURN is used.

Open the page in a regular phone browser, tap Play, then Add coin. Use arrows to
select a character and Fire to confirm/attack; Magic is the second action.
Enable sound is a separate user gesture. Controls use same-origin WebSocket
state snapshots at 20 Hz, mapped to a server-assigned virtual gamepad. Stale
held inputs are released after 300 ms, with immediate release on disconnect.
The browser releases held inputs when backgrounded. Only gamepad controls are
accepted; there is no remote keyboard or shell interface.

## ROM compatibility verified

The original `/srv/avrana/roms/arcade/gaunt2.zip` is unchanged. All 26 entries
match names, sizes, CRCs and SHA-1 against the exact source revision reported by
the downloaded core. No ROMs were downloaded, padded, patched or renamed.

- Core: `cores/mame2010_libretro.so`, official Libretro ARM64 buildbot binary.
- Core/ROM checksums and pinned source revision: `evidence/selected-core.json`.
- Repeat audit: `python3 audit-legacy-rom.py`.
- ROM SHA-256: `ba854a6494fde461138f00550bd2fd38e6afe4cb93bc8e42a15245a0bc8d090e`.
- MAME 0.276 rejects two legacy entries; its `probe.py verify/benchmark` modes
  are retained for investigation but are NOT the chosen runtime/compatibility gate.
- MAME 2010 supports four joypads. Its old non-commercial MAME license makes
  this a private prototype selection, not a cleared commercial distribution.
  https://docs.libretro.com/library/mame_2010/

## Tests completed

- Actual core loads Gauntlet II and renders title/attract mode. SDL2 display
  initialization crashed in Xvfb; the working GL path uses software rendering.
- A paced run of 3600 frames took 62.06 seconds including startup; its screenshot
  reports 60.27 fps, with game target 59.92 Hz. Aggregate child CPU time was
  79.06 seconds (~1.27 cores); maximum child RSS 219932 KiB. This is attract-mode
  evidence, not a prolonged four-player gameplay benchmark.
- Hardware FFmpeg tests: 600 synthetic frames at 640x480 and 960x720 both passed
  using /dev/video11. This is encoder throughput, not measured stream latency.
- Local independent WebRTC receiver decoded both video and Opus audio, then
  disconnected and reconnected without stopping the capture pipeline. Local
  receiver decoding consumes Pi CPU and is not equivalent to a phone test.
- WebSocket input inserted a coin in P1's slot and selected the red player's
  character. Kernel event capture shows the fire/axis state released 310 ms
  after updates stopped (evidence/controller-events.json).
- Capture + emulator + audio baseline, zero viewers, 10-second sample: 59.96
  encoded fps, ~2.01 CPU cores, summed RSS ~332 MiB (shared pages counted more
  than once), encoded stream ~1.50 Mbit/s during that scene. Configured target
  bitrate 2.5 Mbit/s. Wi-Fi counters include unrelated AP traffic.
- One process was observed owning /dev/video11. Temperature 49.1 C at that check;
  see Open work for the power flags.
- nginx syntax validated; /arcade/ and existing LAN Games return 200; wrong-Origin
  WebSocket requests return 403. Existing network configuration was not changed.
- 2026-09-19 read-only inspection of the Pi (up about 50 minutes): nginx,
  NetworkManager, avahi-daemon, avranaparty-games and avranaparty-arcade all
  active and enabled; arcade started at boot with 0 restarts; ~60 fps encoded
  with 0 viewers; `/stats` reported `max_players: 2`; live nginx site, portal,
  captive DNS config and arcade unit matched their repo sources.

## Open work

- **Latency and performance:** measure input-to-photon latency during real
  gameplay (high-frame-rate filming of touch and screen; report median/p95). RTT
  and jitter-buffer stats are not input-to-photon latency.
- **Two phones:** verify independent slots, coin/start, reconnect and screen lock
  with two real phones before raising `MAX_PLAYERS`; then four phones and
  CPU/RAM/Wi-Fi/encoder-count scaling.
- **Boot and offline:** phone-side behavior after a reboot; a true offline test
  (wlan0 provides internet, so Ethernet being idle is not an offline test).
- **Power:** `vcgencmd get_throttled` read `0x50000` about 50 minutes after boot
  on 2026-09-19: under-voltage and throttling have occurred since boot. Treat
  this as an open hardware/power issue (check supply, cable and USB load) before
  attributing performance problems to software.
- **A/V sync:** `/stats` reported audio `capture_age_ms` p50 about 152 ms against
  about 10 ms for video on 2026-09-19. Investigate audio buffering before
  drawing conclusions.
- **Robustness:** a fatal pipeline error may not exit the process, so
  `Restart=on-failure` may not fire; normal stop logs exit 143. The emulator and
  encoder run continuously with zero viewers.

## Installed infrastructure

- nginx adds /arcade/ -> loopback:8097; existing root/probe routes retained.
- nginx backup: ../backups/20260919T043756859916Z/avrana-party.
- /etc/systemd/system/avranaparty-arcade.service.
- /etc/modules-load.d/avrana-uinput.conf loads uinput at boot.
- /etc/udev/rules.d/70-avrana-uinput.rules grants the existing input group access
  to /dev/uinput; the web/emulator processes remain non-root.
- Private PulseAudio null sink and private Xvfb display live inside the service.
- Game files are read from /srv; state/configuration lives in runtime and the
  cody RetroArch configuration directory. No existing RetroArch installation
  was present before this experiment.

Commands:

```sh
sudo systemctl status avranaparty-arcade
sudo systemctl restart avranaparty-arcade
sudo journalctl -u avranaparty-arcade -n 80
curl http://party.local/arcade/stats
```

To stop the experiment without affecting LAN Games:
`sudo systemctl disable --now avranaparty-arcade`.
The arcade URL then returns 502 until the service is started or that location
is removed. Do not blindly restore old nginx backups after making later edits.

## History (superseded)

The sections marked superseded below record earlier plans and investigation.
They do not describe the running system. The current stack is RetroArch with
MAME 2010, one GStreamer capture/encode pipeline, appsink/appsrc fan-out to
per-phone `webrtcbin` pipelines, and `uinput` pads (see Current state).

### Measured host state (pre-install, superseded)

- Raspberry Pi 4 Model B Rev 1.5, ARM64, Debian 13 Trixie, kernel 6.18.39+rpt-rpi-v8.
- 3.7 GiB total RAM, approximately 3.3 GiB available at inspection; 108 GiB storage free.
- Both HDMI connectors disconnected; no graphical session found.
- No MAME, RetroArch, Sunshine, FFmpeg or GStreamer command-line tools installed.
- `/dev/video11`: bcm2835-codec-encode, supports H.264 and MJPEG capture.
  Accepts YUV420/NV12 and several RGB formats. H.264 has no B frames, supports
  baseline/constrained-baseline and repeat sequence headers. This is device
  capability evidence, NOT a successful encoding benchmark.
- cody belongs to video/render/input groups; `/dev/uinput` is root-only (0600).
- Temperature 37.9 C. `get_throttled=0x50000` (under-voltage and throttling have
  occurred). This is an open power issue, not a historical curiosity: on
  2026-09-19 it read `0x50000` again about 50 minutes after boot. Check the power
  supply before attributing poor performance to the emulator or encoder.
- wlan1 remains the party AP; wlan0 remains management/upstream; eth0 disconnected.

### Decision (superseded: standalone MAME 0.276 rejected the ROM set; RetroArch + MAME 2010 is used)

Start with the distribution's standalone MAME (candidate 0.276), a private
640x480 Xvfb display, and the Pi H.264 hardware encoder. Gauntlet II is a 4:3 game;
640x480 avoids stretching. Try 60 fps and roughly 2.5 Mbit/s initially, then measure.
If necessary, stream 30 fps while keeping emulation at full speed. Do not slow
the emulator to match the encoder. 960x720 is a later 4:3 quality option.

| Option | Findings | Decision |
|---|---|---|
| MAME | Debian ARM64 package; verifyroms and benchmark tools; explicit player mappings | First emulator |
| RetroArch + FBNeo | FBNeo includes src/burn/drv/atari/d_gauntlet.cpp; a compatible ROM set and frontend/core build still needed | Performance fallback, not a second parallel session |
| Sunshine + Moonlight | Current release has Debian Trixie ARM64 packages. Source allocates global gamepad IDs to client controllers. video.cpp creates per-session encoder contexts; no V4L2 backend found | ARM64 is supported, but shared encode and Pi hardware encoding are not established; not the first choice |
| Wolf | Moonlight server built around containerized apps and multiple sessions | Extra deployment machinery; no verified Pi shared-encode path in this investigation |
| Selkies | Current native ARM64 packages; browser client and virtual gamepads. Encoder documentation lists NVENC/VA-API/software, not bcm2835 V4L2 | Useful reference/fallback, not a demonstrated Pi hardware path |
| Small GStreamer WebRTC service | webrtcbin accepts RTP; V4L2 encoder must pass runtime test; fan out after encoding | Preferred experiment, contingent on hardware encode + Safari receiving tests |

Repository revisions inspected are recorded in evidence/*-revision.json.
Sunshine release inspected: v2026.914.233613, including
sunshine_2026.914.233613-1+debiantrixie_arm64.deb. Selkies release: 2.0.0rc0.
Downloaded source/documentation in evidence contains no game ROM data.

### Proposed shared pipeline (superseded: implemented with appsink/appsrc fan-out, not a tee)

One MAME process -> private X display -> ximagesrc -> conversion to encoder format
-> ONE v4l2h264enc -> h264parse -> tee of encoded H.264 access units.
Each viewer gets a bounded queue, RTP packetizer and webrtcbin connection.
Use constrained-baseline H.264, no B frames, repeated SPS/PPS and periodic IDR.
Handle new viewers' keyframe requests. Keep queues short; validate recovery from
packet loss rather than assuming arbitrary encoded-frame dropping is harmless.

Only packetization/encryption/network transport scale with viewers, not encoding.
Four viewers at 2.5 Mbit/s means approximately 10 Mbit/s outbound video plus
protocol overhead, NOT one 2.5 Mbit/s Wi-Fi multicast transmission. This is a
budget estimate, not a measurement. Wi-Fi airtime and retransmits still matter.

Use local signaling under a dedicated nginx path, host ICE candidates only,
and no public STUN/TURN servers. Keep the service bound to loopback for HTTP.
Restrict admitted sessions to the intended local UI; do not provide generic
keyboard, shell or desktop-control access. Test RTCPeerConnection receiving on
the actual iPhone over HTTP; avoid WebCodecs/getUserMedia/physical Gamepad API
dependencies that impose additional secure-context constraints. Receiving video
does not need camera permission. Captive-assistant compatibility is unproven;
the system browser at party.local is the fallback.

For controls, the server assigns the slot; clients cannot choose arbitrary
kernel events or another player's slot. Create stable, named virtual gamepads
before starting MAME, one per slot, and explicitly map each to that player's
directions, fire, magic and coin/start controls as defined by MAME's driver.
Use full input-state snapshots, sequence numbers, a heartbeat, and release all
buttons on disconnect/backgrounding or a short timeout. Use a narrowly scoped
uinput permission rule/service, never run the web server as root. Validate P1
first, then P2 isolation before opening slots 3 and 4. No uinput permissions have
been changed yet.

Audio is a separate gate: capture one local game audio output and encode Opus
once, fan out to clients. A silent video-only transport test is useful but is
not complete gameplay. Use a user gesture for playback on iPhone. Avoid multiple
phones loudly reproducing the same audio during latency comparisons.

## Original test gates (reference; steps 1-4 passed, step 5 done for P1 only)

Status: steps 1-4 passed; step 5 is done for P1 only (see Current state). Step 6
metrics and step 7 boot/offline testing are still open (see Open work).
`probe.py verify/benchmark` use standalone MAME 0.276 and are NOT the chosen
runtime or compatibility gate; use `audit-legacy-rom.py` for the ROM.

1. Install prerequisites locally:

   `sudo sh /home/cody/avrana-party/arcade/install-dependencies.sh`

   This installs distribution packages only, no ROMs or service changes. Sudo
   requires the owner's terminal password; do not send it in chat.

2. Supply the legally owned four-player arcade Gauntlet II ROM set. Supplied
   archive: `/srv/avrana/roms/arcade/gaunt2.zip`. Keep ZIP archives intact.
   Exact set/parent dependencies must match the installed emulator. No ROMs
   were found in the shallow home/media/mnt inspection; the owner must identify
   the actual location/version rather than assume absence everywhere.

3. Verify and measure CPU emulation headroom:

   `python3 /home/cody/avrana-party/arcade/probe.py verify --rompath /path/to/roms`

   `python3 /home/cody/avrana-party/arcade/probe.py benchmark --rompath /path/to/roms`

   The benchmark disables video/audio and is unthrottled. It establishes CPU
   headroom only. Then run a real-time local rendering/audio test for at least
   60 seconds: target full emulation speed, no frameskip/audio underruns.

4. Test the encoder independently:

   `python3 /home/cody/avrana-party/arcade/probe.py encode`

   Synthetic 640x480 and 960x720 at 60 fps, 600 frames each. Reports FFmpeg exit
   status, wall/CPU time and GStreamer plugin availability. This does not prove
   game capture performance or browser latency. Results are saved in evidence/.

5. Once the above pass, implement capture/signaling and show one phone the game.
   Then implement/test P1 control. Only then add P2 and confirm simultaneous,
   independent movement. Repeat with up to four actual phones.

6. Record emulator speed, per-process CPU/RSS, encoder frame rate, wlan1 TX byte
   deltas, peer packet loss/jitter/RTT, browser frames decoded/dropped and thermal
   flags for 0/1/2/4 viewers. Verify one encoder element/context/process remains
   open across viewer counts. Report CPU with 100% = one core (400% total).
   RTT is NOT input-to-photon latency: measure that with high-frame-rate video
   showing the physical touch and resulting screen change; report median/p95
   and camera time resolution. Benchmark real gameplay, not only attract mode.

7. After success, add isolated systemd units and test cold boot and true offline
   operation. Preserve wlan0 management until local recovery access is available.

## Primary sources

- https://docs.mamedev.org/commandline/commandline-all.html
- https://github.com/mamedev/mame/blob/master/src/mame/atari/gauntlet.cpp
- https://github.com/finalburnneo/FBNeo/blob/master/src/burn/drv/atari/d_gauntlet.cpp
- https://github.com/LizardByte/Sunshine/releases
- https://github.com/LizardByte/Sunshine/blob/master/src/video.cpp
- https://github.com/LizardByte/Sunshine/blob/master/src/input.cpp
- https://github.com/games-on-whales/wolf
- https://github.com/selkies-project/selkies/blob/main/docs/component.md
- https://gstreamer.freedesktop.org/documentation/webrtc/
- https://gstreamer.freedesktop.org/documentation/rtp/rtph264pay.html

## History: ROM selection correction (superseded by the MAME 2010 audit)

The user confirmed Gauntlet II arcade (`gaunt2`), not Gauntlet (1985).
The probe defaults now use gaunt2 and /srv/avrana/roms/arcade.
The supplied ZIP passes its internal CRC checks. Comparison against the MAME
0.276 driver matches 24 of 26 SHA-1 hashes; 136043-1104.6p differs, and
82s129-136043-1103.4r is missing. Current FBNeo expects the same corrected
graphics ROM (and marks that PROM optional). Do not launch or benchmark this
as a validated set until the emulator audit passes. Original ZIP unchanged.
