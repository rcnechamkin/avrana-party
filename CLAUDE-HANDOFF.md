# Claude Code handoff: Avrana Party

> **Read this first (2026-09-24 evening).** This file is mostly a **historical log** of the arcade
> work (2026-09-19/20) with dated banners. Current truth lives elsewhere — start at `README.md` →
> "Start here": status and the next action in `docs/ROADMAP.md`, machines/repos/branches in
> `docs/SYSTEM.md`, networking in `docs/runbooks/network.md`, tests in `docs/TESTING.md`.
> **Since 2026-09-24:** the USB Wi-Fi adapter is gone; the party AP runs on the Pi's internal radio
> (`wlan0`, `10.42.0.1`) and the Pi reaches home over `eth0` (`10.0.0.142`). Anything below that
> says `wlan1` is the AP or `wlan0` is the home link, or `10.0.0.143`, is historical. Power is clean
> without the adapter (`docs/findings/2026-09-24-no-usb-power-baseline.md`).

> **2026-09-24 update: product direction.** Avrana Party is now explicitly **one party
> platform with many games** ("the game may change; the party does not"). Avrana is designed
> to own identity, party, seats, host, navigation, chat and stats (none of it is built yet);
> games consume them. Start at `docs/design/PARTY-PLATFORM.md` (the hub, with links to the
> lifecycle, integration, native-games, Personal Viewports, onboarding and installation docs) and
> the ADRs `0002-party-platform` and `0003-ids-and-keys` before designing any player-facing
> feature; phasing is ROADMAP **N5**. Locked: one appliance = one party; TV optional; host
> disposable; late joiners spectate by default; no app/captive portal/store required. Until the
> BLUFF real-phone playtest, the platform is documents and offline simulations only
> (`experiments/` on branch `experiment/party-sim`): don't change BLUFF's identity code or live
> services for it. Development runs laptop → GitHub → Pi; the Pi is a deploy/test target. The
> games fork is backed up on the laptop (`~/avrana-party-games.git`); its GitHub repo is not
> created yet. ~~Current blocker: power~~ — resolved for the tested workloads by removing the USB adapter
> (see the banner above). BLUFF playtest runbook: `docs/runbooks/bluff-playtest.md`.

> **2026-09-23 update. Read `docs/ROADMAP.md` first.**
> - The **repository is now the documentation source of truth**. The BookStack API/MCP is
>   unreliable; do **not** try to repair it unless the owner asks.
> - The first native-game target is a **Coup-inspired Avrana bluffing card game**, working
>   title **BLUFF**, built as a LAN Games module (`games/bluff/`) in the Avrana Party Games
>   fork. Dev clone: `~/avrana-lab/avrana-party-games/` on `party`, running on port 8196
>   (`http://10.42.0.1:8196/games/bluff/` from the party Wi-Fi). Reference:
>   `docs/findings/2026-09-23-vtt-coup-reference.md`.
> - **BLUFF status (2026-09-23):** the baseline game plus a phone lifecycle passed a
>   six-workstream robustness pass: 1,197 tests, protocol privacy and attack checks, a
>   full-game simulator (0 violations), and 2–6 player screenshots. **Next milestone: a real
>   3–4 iPhone playtest** (2026-09-24: widened to 3–6 phones including an Android, tested truly offline, with the measurements in ROADMAP N5). Details: `docs/findings/2026-09-23-bluff-multi-agent-pass.md`.
>   Next-agent prompt: `docs/handoff/2026-09-23-next-agent-prompt.md` (partly superseded
>   2026-09-24; see the banner at its top).
> - **Not yet published:** the repo `rcnechamkin/avrana-party-games` must be created by the
>   owner (empty, not a fork). The laptop pushes `main` from its backup, never
>   `abandoned/classic-diplomacy`; `party` should become pull-only later.
> - **Classic map-based Diplomacy and `diplomacy/diplomacy` are ABANDONED** (a
>   misunderstanding). Don't continue them. The local commit is on branch
>   `abandoned/classic-diplomacy`, never pushed.
> - The arcade items below are still open and unchanged.

## Current status and priorities (updated 2026-09-19)

*Historical snapshot of the arcade work as of 2026-09-19/20. For current status read the banners
above and `docs/ROADMAP.md`; some items below were later superseded (e.g. two-phone play is now
verified, and the recovery gap appears twice). The arcade items are otherwise still open.*

Status of the Gauntlet II phone-streaming prototype, from a read-only inspection of the Pi and the current code:

- **P1 is verified** for basic gameplay and streaming on a real iPhone (see the comment at `arcade/stream.py:23`). An earlier report said the experience was “super laggy”; that predates the P1 phone verification. **Input-to-photon latency and gameplay performance have NOT been formally measured.** Do not describe latency as solved or low, and do not mistake 60 encoded frames per second for low latency. Measure before choosing a major rewrite.
- **`MAX_PLAYERS = 2`**: two player slots are enabled. **Two-phone play is now
  VERIFIED on two real iPhones (2026-09-20).** A 3-min captured session
  (`arcade/capture-load.py`, 177 samples, both phones connected throughout) held
  both phones at **~60 fps, 0 median packet loss, ~26 ms jitter buffer, ~3 ms pair
  RTT, ~6-7 ms input-ack RTT, 2-3 freezes total**; server video capture-age p50
  ~11 ms (one shared encode). One brief (~3 s) under-voltage/throttle event early,
  otherwise clean (temp 47-51 C). Independent slot assignment / third-client
  rejection / slot reclaim are also covered by the Playwright suite. Caveats: this
  is a 3-min window (not a soak test) and audio capture-age was ~1.5 s (the still-
  open drift). **Do not raise beyond 2 without a longer multi-phone soak.**
- **Boot:** service startup after a reboot is verified (Pi up about 50 minutes at inspection; nginx, NetworkManager, avahi-daemon, avranaparty-games and avranaparty-arcade all active and enabled; arcade started at boot with 0 restarts). **Phone-side behavior after a boot and fully offline operation are not verified.**
- **Power (OPEN, gating):** the earlier "0x50000 ~50 min after boot" reading was
  **not** a one-time boot inrush. On 2026-09-19 the kernel journal
  (`sudo journalctl -k -b | grep -icE 'undervoltage|voltage normalis'`) showed
  **~23 "Voltage normalised" events spread evenly across a ~100-min session**
  (roughly one dip every 3-4 min) - recurring, transient under-voltage. A 20 s
  live watch looked clean only because the dips are shorter than the sampling.
  `0x50000` is the sticky "occurred since boot" flag (bits 16 + 18); no live bits
  were ever caught set. **Treat this as unresolved and do not trust any latency
  measurement until it is gone.** Cause is NOT identified: PSU, USB-C cable, USB
  load (the Realtek Wi-Fi 6 + BT adapter), and Pi power delivery are all
  hypotheses - isolate experimentally, one variable at a time, over matched
  >=10 min windows using the kernel dip count (method in `telemetry/README.md`).
  Config is stock (`arm_freq=1800`, `over_voltage=0`); idle temps ~40 C.
- **A/V audio ratchet — ROOT CAUSE CONFIRMED, fix UNVERIFIED (2026-09-20).**
  Cause: pipeline runs on the system (wall) clock while `pulsesrc`
  (a `GstAudioBaseSrc`) timestamps from its sample-position ringbuffer clock and
  ignores `do-timestamp`; on an audio-thread stall the sample clock falls
  permanently behind wall-clock, so `capture_age = now − pts` ratchets per session
  (13→313→1003→2142 ms measured). PulseAudio latency ~0 (content fresh, only the
  PTS is mislabelled); video immune (ximagesrc clock-stamped). Full evidence +
  fix journey: `docs/findings/2026-09-20-audio-ratchet-and-recovery.md`.
  - **Fix `6acf0b0` on main** re-stamps audio `pts=now` in `distribute()`
    (`buffer.copy()`), deployed to party's checkout. ~~The RUNNING service still has a broken interim build (audio down) until a restart loads
    `6acf0b0`.~~ *Superseded: the Pi has rebooted since (latest 2026-09-24); the deploy checkout
    (`f93f0fc`) contains `6acf0b0` and the arcade service started at that boot. The fix is loaded
    but still **unverified** (the soak below has not been run).*
  - **To verify** (no restart needed now): `SOAK_SECONDS=60 npx playwright test tests/soak.spec.ts --project=chromium`
    → expect audio-age drift ~0 (was +2782 ms) + no server error. Real iPhone
    confirms A/V by ear. Rollback if worse: `git revert 6acf0b0` + redeploy.
- *(Duplicate of the "CONFIRMED" entry below: the defect is confirmed, the fix is not started.)*
  **Recovery gap (defect #2):** `Stream.watch()` returns instead of
  exiting on a fatal error, so systemd never restarts the zombie 503 service. Fix
  plan in the same findings doc.
- **Load/soak/fault harness (NEW 2026-09-20):** `npm run soak` / `npm run fault`
  drive N real WebRTC clients against the live Pi (regression gates + JSON
  artifacts), with fault-injection/recovery coverage. Design + threshold rationale
  in `docs/adr/0001-load-soak-fault-harness.md`. It reproduces the audio ratchet
  and is the before/after tool for the audio + recovery fixes.
- **Recovery gap (CONFIRMED 2026-09-20):** `Stream.watch()` returns instead of
  exiting on a fatal pipeline/emulator error, so systemd never restarts the unit
  (zombie 503s). Fix plan in the same findings doc.
- **Documentation:** the BookStack shelf “Avrana Party”
  (http://10.0.0.218:6875/shelves/avrana-party) now has the **Avrana Party book**
  with Overview, Architecture, Runbook, and Decisions & Current State pages.
  **SUPERSEDED 2026-09-22:** the repository is now the working source of truth,
  because the BookStack MCP is unreliable (it failed on 2026-09-19 and 2026-09-20).
  Do **not** try to repair it or "reconcile BookStack early" unless the owner asks.
  The pages are stale. `docs/bookstack-update-2026-09-20.md` holds a paste-ready
  update for when it's reliable. See `docs/ROADMAP.md`. Don't confuse it with the
  “Avrana Homelab” shelf (the separate media server).
- **Telemetry (NEW 2026-09-19):** party now reports to the existing Beszel hub on
  avrana (`http://10.0.0.218:8093`) via a pinned systemd agent, plus a small
  `vcgencmd` sampler/timer for Pi-only metrics. See the Telemetry section below.

*Superseded 2026-09-24 — current next steps are in `docs/ROADMAP.md` "Next action"; (4) is done.*
Your next jobs (as of 2026-09-20), in order: **(1) resolve the recurring under-voltage** (isolate
PSU/cable/USB-load/power-delivery experimentally — do this before trusting any
latency numbers); (2) confirm Beszel history for `party` and finish the three
baseline snapshots; (3) measure real one-phone latency; (4) verify two phones
with independent slots; (5) boot and offline acceptance.

## Product and constraints

Avrana Party is a portable, self-contained local multiplayer appliance. One central device hosts games; phones connect to its Wi-Fi and act as screens/controllers. Core gameplay must eventually work without internet, accounts, or app installation. Normal players should see Avrana Party, clean local URLs, and simple game flows—not IPs, ports, Linux or emulator administration.

Current hardware is a Raspberry Pi 4 Model B Rev 1.5, approximately 4 GB RAM, ARM64 Debian 13 Trixie. Kernel observed: 6.18.39+rpt-rpi-v8. About 100+ GB storage remains. Both HDMI ports are disconnected. This is a headless machine.

The original MVP is browser-native LAN Games. A later explicit user request authorized emulation, streaming, and virtual controllers for a NEW MVP. Do not treat the earlier “no streaming/emulation” scope as still prohibiting this new work.

New MVP target:

Gauntlet II arcade runs ONCE on the Pi -> one shared render -> ideally one hardware video encode -> same encoded content to all phones. Each phone independently controls its own player. Never launch an emulator session per phone. Priorities: latency, stability, low Pi resource usage, independent players, then picture quality. 480p is acceptable; 720p is plenty.

Preserve LAN Games, nginx, Avahi, systemd, NetworkManager and management access. Avoid Docker/cloud/HTTPS certificate hacks unless a concrete need emerges. No public STUN/TURN or internet dependency is needed on this local network. Do not download ROMs. Keep the user's supplied archive UNCHANGED.

## Existing infrastructure: working, preserve it

- `wlan1`: USB Realtek Wi-Fi 6 adapter (USB ID 0bda:b851), dedicated AP.
- NetworkManager connection and SSID: `Avrana Party`.
- Shared IPv4 mode, AP address `10.42.0.1/24`, autoconnect enabled. NetworkManager supplies DHCP, NAT and dnsmasq.
- `wlan0`: home Wi-Fi / management fallback, address previously `10.0.0.143`. Currently connected to profile `SpicyMamiMrKiwi IoT`. Do not casually disconnect it.
- `eth0`: currently disconnected. This is not an offline test: wlan0 still provides upstream internet.
- System hostname remains `RaspberryPi`; Avahi explicitly advertises `party.local` via `host-name=party` in `/etc/avahi/avahi-daemon.conf`. Do not rename it to avrana.local; another real server uses that name.
- LAN Games: `/home/cody/LAN-Games`, existing venv `.venv`, Python server on port 8096.
- Service: `avranaparty-games.service`, enabled and active. Do not modify its Python environment for the arcade experiment.
- nginx site: `/etc/nginx/sites-available/avrana-party`, enabled by symlink, default site removed.
- `http://party.local/` proxies to `127.0.0.1:8096` with WebSocket support.
- `http://party.local/arcade/` now proxies to `127.0.0.1:8097/` with WebSocket support and proxy buffering disabled.
- All of nginx, NetworkManager, avahi-daemon, avranaparty-games and avranaparty-arcade were active at handoff.

### Captive portal: user confirmed it works perfectly

- **DESIGN CHANGED 2026-09-18 (reversal):** `/hotspot-detect.html` now returns
  Apple's literal `Success` page (served locally, `Cache-Control: no-store`) ON
  PURPOSE, so the iPhone marks the network usable and connects **silently with no
  captive popup**. See `avrana-party.nginx:7`. The player then opens the browser
  to `http://party.local/` (the LAN Games hub) themselves.
- The old landing page (`portal/index.html`; live copy
  `/var/www/avrana-portal/index.html`) is therefore **no longer wired to the
  probe** — it is an artifact of the previous "intercept probe with a landing
  page" design and is not currently served at any route. Don't assume it renders
  on connect.
- Captive DNS config: `/etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf`.
- Important fix: intercept BOTH `captive.apple.com` AND `captive.g.aaplimg.com` to 10.42.0.1, with `local=/.../` rules for both. Without the alias/local rules, iPhone queried Apple's alias directly and fetched Apple's actual Success page through upstream internet. A packet capture proved this. Do not regress that fix.
- Other existing interception names include Google/Android, Microsoft and Firefox, but their complete captive flows have not been validated.
- Returning Apple's `Success` page at the probe is now **intentional** (the
  no-popup design above); do **not** "fix" it back to serving the landing page.
  Do not otherwise break the working portal.
- iOS captive assistant does not provide a dependable webpage-controlled handoff to the preferred browser. User accepted manually opening the regular browser. Arcade testing was requested in the regular browser.
- Earlier boot test of LAN Games/AP/nginx/Avahi worked according to owner. On 2026-09-19 the Pi was observed about 50 minutes after a reboot with the arcade service active at boot (0 restarts), so service startup after boot is verified. Phone-side behavior after a boot and a true offline test have NOT been done.
- Server-side re-check on 2026-09-19: the Apple probe returns 200 with `Cache-Control: no-store`, and both `captive.apple.com` and `captive.g.aaplimg.com` resolve to 10.42.0.1 via the AP's DNS.

## ROM compatibility: solved, do not reopen unnecessarily

User means **Gauntlet II arcade (1986), four-player, short name `gaunt2`**, NOT the original 1985 Gauntlet.

Original archive:
`/srv/avrana/roms/arcade/gaunt2.zip`

Original SHA-256:
`ba854a6494fde461138f00550bd2fd38e6afe4cb93bc8e42a15245a0bc8d090e`

Debian standalone MAME 0.276 was installed first and rejected this legacy set:
- `136043-1104.6p`: expected 16384 bytes / CRC bddc3dfc; supplied 8192 bytes / CRC 1343cf6f.
- `82s129-136043-1103.4r`: missing; archive instead has legacy `74s287-136037-103.4r`, CRC 6c5ccf08.

This does NOT mean the supplied ROM is unusable. The user explicitly preferred finding a compatible older emulator rather than replacing individual files.

**Selected solution: RetroArch + MAME 2010 (MAME 0.139). All 26 supplied files match name, size, CRC and SHA-1 against the EXACT source revision reported by the installed core. The actual game loads and runs.**

- Core binary: `/home/cody/avrana-party/arcade/cores/mame2010_libretro.so`.
- Core reports `MAME 2010`, version `0.139 dff8aad`.
- Source revision: `dff8aadd1c3f38215af3955746d6e19abe0ddcea`.
- Official download used: `https://buildbot.libretro.com/nightly/linux/aarch64/latest/mame2010_libretro.so.zip`.
- Core SHA-256: `c57b5072c1b3963bd54766bfc9b68c2123b62c78831f2721fd07d4c8405a775b`.
- Provenance: `arcade/evidence/selected-core.json`.
- Pinned driver source: `arcade/evidence/mame2010-gauntlet.c`.
- Re-run audit: `python3 /home/cody/avrana-party/arcade/audit-legacy-rom.py`.
- Audit report: `arcade/evidence/gaunt2-mame2010-audit.json`.
- No ROM files were downloaded, patched, padded, renamed, or replaced.
- MAME 2010 supports four joypads. Its old non-commercial MAME license makes it a private prototype choice, not a cleared commercial distribution choice.

## Current arcade implementation

All project files: `/home/cody/avrana-party/arcade/`.
There was no existing RetroArch setup before this experiment. OS packages were installed; no Docker was introduced.

### Runtime chain

`avranaparty-arcade.service`
-> `run-stream.sh`
-> `with-audio.sh` starts a private PulseAudio null sink
-> `xvfb-run` starts private 640x480 X display
-> `stream.py` starts virtual controller(s), one RetroArch instance, capture/encode, and HTTP/WebSocket signaling.

- Service runs as `cody`, supplementary groups `input video render`.
- Enabled at boot; `Restart=on-failure`, `KillMode=control-group`, stop timeout 10 sec.
- Service definition: `/etc/systemd/system/avranaparty-arcade.service`; editable copy in arcade directory.
- The emulator and encoder currently keep running even with zero viewers. This is intentional prototype behavior, not optimized appliance idle behavior.
- PulseAudio socket: `arcade/runtime/pulse/native`; sink `avrana_arcade`, monitor `avrana_arcade.monitor`.
- Audio wrapper: `with-audio.sh`; pulse log `runtime/pulse.log`.
- RetroArch config: `retroarch.cfg`; core options `core-options.cfg`.
- RetroArch GL display path works in Xvfb using software rendering. SDL2 video path segfaulted during display initialization even with software renderer forced. Do not switch back blindly.
- Emulator log: `runtime/emulator.log`, capped by `stream.py` (copy-truncated at 20 MB to `emulator.log.1`; the file is truncated again at each service start). `retroarch.cfg` uses `libretro_log_level = "2"` because the MAME 2010 core otherwise logged ~100 KB/s of `read 'pokey' POT*` INFO warnings (6 GB in a day). Runtime/save directories under `arcade/runtime/`; RetroArch also writes its per-core options under `/home/cody/.config/retroarch/config/MAME 2010/`—check overrides when tuning.
- `run-local.sh` runs only the audited game on a private display; `with-audio.sh sh run-local.sh ...` adds paced audio.

### Video/audio transport

`stream.py` uses distro Python 3.13, aiohttp and PyGObject/GStreamer.

One capture pipeline:
- `ximagesrc use-damage=false show-pointer=false`
- 60 fps raw capture, conversion to I420
- **one `v4l2h264enc` on `/dev/video11`**
- target bitrate 2.5 Mbit/s, IDR period 60, repeated sequence headers
- H.264 constrained baseline, level 3.1, byte-stream access units
- encoded `appsink` distributes buffers to per-peer nonblocking bounded `appsrc` queues
- each peer has its own RTP packetizers, `webrtcbin` and DTLS/SRTP transport pipeline
- one PulseAudio capture -> Opus encode (64 kbit/s, 10 ms frames), similarly distributed.

The initial dynamic tee/branch approach stalled during connect/disconnect, so current implementation separates capture from peer transport using appsink/appsrc. Source comments/docs in older sections may describe the abandoned tee topology; inspect current code.

Peer pipelines use the capture pipeline clock/base time to preserve timestamps. This is worth reviewing when diagnosing accumulating delay. Generic GStreamer defaults were not comprehensively tuned for gaming.

No public ICE servers. Per-peer WebRTC connections are unicast: one encode does not imply one Wi-Fi transmission for all viewers.

### Controller path

- **`MAX_PLAYERS = 2`** in stream.py: two slots enabled. P1 is verified on a real iPhone; P2 and two-phone behavior were verified on 2026-09-20 (see "Current status" above). Do not raise beyond 2 without a longer multi-phone soak.
- Creates one named evdev/uinput pad per slot (P1 is `Avrana Player 1`) BEFORE starting RetroArch.
- RetroArch joypad driver is `udev`; explicit axis/button mappings are in retroarch.cfg.
- Directions use ABS_X/ABS_Y. Fire/Magic/Coin/Start map to BTN_SOUTH/BTN_EAST/BTN_SELECT/BTN_START.
- MAME core maps RetroPad A/B/select/start to action buttons/coin/start.
- The browser sends full held-button snapshots over a SAME-ORIGIN WebSocket at 20 Hz and immediately on touch changes. Video/audio travel over WebRTC; controller input currently does NOT use a WebRTC data channel.
- Server assigns/reserves the player slot; clients cannot select another slot or submit arbitrary OS keys.
- Server clears held inputs after ~300 ms without updates and on disconnect. Browser clears on blur/background/pagehide.
- `/dev/uinput` initially existed as a node but the module was not loaded. `modprobe uinput` fixed this.
- Boot module config: `/etc/modules-load.d/avrana-uinput.conf`.
- Permission rule: `/etc/udev/rules.d/70-avrana-uinput.rules` gives existing `input` group mode 0660. No root web service, no world-writable uinput.

### Browser UI

`arcade/index.html` is served by aiohttp through nginx at `http://party.local/arcade/`.

- Video element uses autoplay, playsinline, muted.
- User must tap Play to establish the connection. User initially saw black and had not pressed Play; pressing Play made the difference.
- Latest change puts a large **Play Gauntlet II** button over the black video area; overlay disappears on video `playing` event. This file-only update needs page refresh, not service restart.
- Audio enabled separately by a user gesture.
- Touch D-pad plus Fire, Magic, Add coin, Start.
- Connection details show browser inbound frame rate, decoded frames and lost packets.
- UI is rough. Touch ergonomics, landscape layout, reconnection, stats/error messages and browser lifecycle handling need real-device testing.

## Verified results—understand their limits

1. ROM audit: 26/26 exact match; original ZIP checksum unchanged.
2. Compatible core actually loads Gauntlet II. Title/attract screenshots saved.
3. Paced local run: 3600 frames in 62.06 seconds including startup. Screenshot showed ~60 fps; core target 59.92 Hz. CPU time 79.06 sec (~1.27 cores average). Maximum child RSS ~215 MiB. This is attract-mode evidence, not sustained four-player gameplay.
4. Hardware FFmpeg synthetic tests passed: 600 frames each at 640x480 and 960x720 using h264_v4l2m2m on video11. Throughput exceeded real time. NOT latency measurements.
5. Local independent GStreamer receiver negotiated and decoded video + Opus, then disconnected/reconnected without stopping capture. Test file `test-receiver.py`; `--controls` inserts P1 coin and a short direction/fire input. Do not run this while the owner is using the sole P1 slot.
6. Kernel input capture proved coin/fire/right events. After stopping updates while held, fire and axis released after ~310 ms. Evidence `controller-events.json`. Screenshot shows the red player's character-selection state responding.
7. 10-second full-service baseline with ZERO viewers: ~59.96 encoded fps, ~2.01 of four CPU cores, summed process RSS ~332 MiB (shared pages double-counted), actual encoded bitrate ~1.50 Mbit/s during that scene. File `evidence/service-measurement.json`.
8. `/dev/video11` was owned by one service Python process. The stats field `video_encoders: 1` is hardcoded descriptive metadata, NOT an independent encoder-count measurement.
9. Wrong-Origin WebSocket request returns 403; arcade UI and existing LAN Games return 200. Captive probe continued returning landing HTML *(at that time; since changed — Apple's probe now gets "Success", see `docs/design/ONBOARDING.md`)*.
10. User could reach UI and start the stream and first reported the experience as SUPER LAGGY. P1 has since been verified for basic gameplay and streaming on a real iPhone (per the `stream.py` comment). End-to-end latency, real-phone frame timing, audio drift and sustained control responsiveness are still unmeasured. Do not declare low latency from local tests or from “it plays”.

Useful evidence files in `arcade/evidence/`:
- `gaunt2-paced-run.json`, `gaunt2-paced-run.log`, `gaunt2-paced.png`
- `gaunt2-player1.png`
- `receiver-test.log`, `receiver-controls-test.log`
- `controller-events.json`
- `encode-*.json`, `encode-summary.log`
- `service-measurement.json`
- pinned/downloaded source and initial comparisons

Older failed run files exist, including SDL segfault runs and receiver GDB output. Receiver crash was fixed by retaining/copying Gst promise structures/session descriptions. Keep that lifetime fix. SDP offer creation now waits until both media caps reach the WebRTC pads; early offers previously omitted video.

## Open work: measure latency, then verify two phones

Latency was reported as poor earlier and P1 has since been verified playable, but no formal measurement exists. Use this sequence to measure it and to investigate any remaining lag or instability.

1. Reproduce with ONE phone. Confirm exact browser, actual SSID/interface, visible frame rate, and whether “lag” means low fps, a smooth-but-delayed picture, delayed controls, audio drift, or all of them. Inspect existing logs first; do not make the owner repeat things you can observe.
2. Verify the actual network path. Several iPhone requests in nginx logs used a **global home-network IPv6 source**, while AP clients are normally 10.42.0.x/link-local. Do NOT assume every test used wlan1. This is evidence to investigate, not proof of the cause. Check selected ICE candidate pair and interface traffic, AP signal/rate/retries/frequency, and browser path. Preserve wlan0 management.
3. Add useful browser diagnostics: selected ICE candidate pair/RTT, inbound frames received/decoded/dropped, jitterBufferDelay divided by jitterBufferEmittedCount, processing time, frame age where measurable, video playback state. Read stats over intervals, not lifetime counters alone. Avoid calling network RTT “input-to-photon latency.”
4. Measure per-process/cgroup CPU while the PHONE decodes, memory, thermal flags, game pacing, captured/encoded fps, Wi-Fi throughput and packet loss. Do not benchmark with the Pi simultaneously decoding the test stream and extrapolate that CPU load to phone playback.
5. Inspect buffering/timestamps at every stage. Current stack uses generic PulseAudio/pulsesrc, appsrc queues, RTP and webrtcbin defaults. Check audio buffering/clock sync, WebRTC jitter-buffer latency, accumulated PTS offsets, appsrc queue levels and whether frames are already old when sent. Enforce short bounded queues and recoverable frame dropping. PLI/keyframe feedback in per-peer pipelines is not explicitly bridged back to the shared encoder; periodic IDRs are currently the fallback.
6. Isolate audio: test video/control latency with audio capture/transport disabled while preserving emulator pacing. Muting the browser is not equivalent to removing audio transport/synchronization.
7. Try a controlled lower-cost profile (e.g. encode/capture 480p30 or near-native size, while keeping emulation full speed), measure benefit before changing defaults. The software GL/Xvfb capture path consumes significant CPU; evaluate simpler capture/render approaches only if measurements justify them.
8. Check touch/UI and input latency separately. WebSocket snapshots are simple but can suffer TCP ordering delays; a small unordered WebRTC data channel with full-state snapshots and timeout release is a candidate improvement if input transport is the bottleneck. Do not assume it fixes video buffering.
9. Measure real input-to-photon latency with high-frame-rate filming of touch and screen response if possible. Report limitations and median/p95 rather than invented numbers.
10. *(Two-phone assignment verified 2026-09-20.)* P2 is enabled (`MAX_PLAYERS = 2`): with two real phones, verify independent controller/coin/player assignment with one emulator and one encoder; only then consider P3/P4 and viewer-scaling metrics. Finally phone-side cold boot and full offline acceptance.

Power: `vcgencmd get_throttled` read `0x50000` about 50 minutes after boot on 2026-09-19 (under-voltage and throttling have occurred since boot); temperature was about 49.6 C. This is a current open power/hardware issue. Check the supply, cable and USB load, and re-read the flags during load, before attributing lag to software.

## Alternatives already considered

- Sunshine currently publishes ARM64 Debian Trixie packages. Don't claim it lacks ARM64 support. Its inspected video.cpp creates per-session encoding contexts and lacks the Pi V4L2 encoder backend; its input code does allocate separate global gamepad IDs per client. Not shown to meet one-Pi-hardware-encode/multiple-clients requirement.
- Wolf is session/container-oriented; no verified simpler Pi shared-encode route established.
- Current Selkies offers ARM64 packages/browser support but documented hardware encoder backends are NVENC/VA-API, not bcm2835 V4L2. Could be a reference, not assumed turnkey Pi acceleration.
- Current FBNeo driver expects the newer graphics dump too. MAME 2010 is the established exact ROM match, so no need to switch emulators merely for recency.

Sources:
https://docs.libretro.com/library/mame_2010/
https://github.com/LizardByte/Sunshine/blob/master/src/video.cpp
https://github.com/selkies-project/selkies/blob/main/docs/component.md
https://gstreamer.freedesktop.org/documentation/webrtc/
https://gstreamer.freedesktop.org/documentation/rtp/rtph264pay.html

## Telemetry (added 2026-09-19)

Source: `telemetry/` in this repo. Deliberately small — Beszel is the main
historical dashboard; a `vcgencmd` sampler covers only what Beszel cannot read.

- **Beszel hub**: already running on avrana in Docker (`beszel:0.18.7`), web UI at
  `http://10.0.0.218:8093`. Hub keypair lives at
  `/home/cody/avrana/services/beszel/data/id_ed25519` on avrana; the agent’s `KEY`
  is that public half (safe to store; baked into `install-beszel-agent.sh`).
- **Agent on party**: pinned v0.18.7 arm64 binary, checksum-verified, installed by
  `sudo bash telemetry/install-beszel-agent.sh` as systemd `beszel-agent.service`
  (user `beszel`, `/opt/beszel-agent/`, env `/etc/beszel-agent.env`). Listens on
  `:45876`; the hub dials it (classic model — no token/HUB_URL; the “HUB_URL not
  set” log line is expected). `health` returns ok. avrana→`10.0.0.143:45876` is
  reachable. **Still TODO: add system `party` (host `10.0.0.143`, port `45876`) in
  the hub UI** — requires a hub login, not yet done. party’s `10.0.0.143` is a DHCP
  lease; a router reservation is advisable.
- **Pi sampler**: `sudo bash telemetry/install-pi-throttle-check.sh` installs
  `/opt/avrana-telemetry/pi-throttle-check.sh` + a 60 s systemd timer
  (`pi-throttle-check.timer`) writing JSON lines to
  `/var/log/avrana/pi-throttle.jsonl`: `get_throttled` flags, CPU temp, ARM clock,
  V3D/GPU clock, core volts. For a test window use `--interval 1 --count N`. The
  60 s cadence and even 1 s sampling MISS most sub-second dips; the kernel journal
  is the authoritative dip counter.
- **Baselines**: written to `/var/log/avrana/baseline.jsonl`, summarized in
  `telemetry/README.md`. **Idle done** (arcade stopped): temp 40.9/49.1 C, no live
  throttle bits, 0 dips in 60 s; min ARM 600 MHz / core 0.86 V are normal idle
  DVFS, not throttling. **Arcade-no-viewer and arcade+1-phone snapshots are not yet
  taken.** All baselines are provisional until the under-voltage is fixed.

## Operations, rollback and cautions

```sh
sudo systemctl status avranaparty-arcade
sudo journalctl -u avranaparty-arcade -n 100 --no-pager
curl http://party.local/arcade/stats
sudo systemctl restart avranaparty-arcade
python3 /home/cody/avrana-party/arcade/audit-legacy-rom.py
# telemetry
systemctl status beszel-agent pi-throttle-check.timer
sudo journalctl -k -b | grep -icE 'undervoltage|voltage normalis'   # authoritative dip count
sudo /opt/avrana-telemetry/pi-throttle-check.sh --label adhoc        # one sample now
tail -n 5 /var/log/avrana/pi-throttle.jsonl
```

To stop just this experiment:
`sudo systemctl disable --now avranaparty-arcade`
LAN Games/AP/portal remain operational; /arcade/ will return 502 while stopped.

nginx backup before arcade route:
`/home/cody/avrana-party/backups/20260919T043756859916Z/avrana-party`
Do not blindly restore it if newer site edits exist. Editable copies of current site are `/home/cody/avrana-party/avrana-party.nginx` and `arcade/nginx-site`; keep relevant copies aligned if changing routing. `arcade/install-service.py` installs `arcade/nginx-site` over the live site and then copies it over `avrana-party.nginx`, so `arcade/nginx-site`, `avrana-party.nginx` and `/etc/nginx/sites-available/avrana-party` MUST stay byte-identical (reconciled 2026-09-19 after `nginx-site` had drifted and would have reverted the captive-portal `/hotspot-detect.html` behavior; check with `cmp`).

`install-service.py` and the older portal installers exist for provenance/recovery; do not rerun them blindly over later changes. `arcade/README.md` keeps superseded material under its “History” headings; this handoff and current runtime code should guide the next step.

Deploy path (DEFINED as of 2026-09-19): the Pi checkout `/home/cody/avrana-party`
now has the GitHub `origin` and tracks `origin/main`. Deploy = commit + push from
the laptop, then `git pull --ff-only` on party. Verified working (party pulled up
to `df3763c`). System files under `/etc` and `/opt` are still installed by the
repo’s install scripts run with sudo on party; the byte-identical nginx invariant
still applies (`cmp`). Passwordless sudo worked from the SSH session on
2026-09-19 — do not assume it always will; never request a password in chat.

Normal systemd stop currently logs shell exit 143 / XIO because the whole process group is stopped. Clean shutdown/reporting could be improved; distinguish intentional stops from real crashes. Fatal pipeline error handling also needs review: it can mark an error and close peers without necessarily exiting the process to trigger Restart=on-failure. Not yet appliance-grade.

The prior session sometimes needed the owner to run sudo locally, but `sudo -n` later worked. Test current privileges; never request passwords in chat. Use reversible scoped changes, backups and nginx validation. No need to ask permission repeatedly for already authorized diagnostic/development work.

Do not spawn additional agents unless the user or applicable local instructions explicitly authorize it. The user values direct action, clear evidence and short progress updates. If you reach a physical-phone test gate, prepare everything first and ask one concrete test question.

Start by inspecting the active service and real client statistics. Measure latency honestly rather than assuming it is good or bad, then verify two-phone play and investigate the power flags. Preserve the existing successful browser-party platform throughout.
