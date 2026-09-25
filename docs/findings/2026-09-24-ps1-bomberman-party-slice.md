# PS1 Bomberman: supervised runs, the CPU finding, and the first Party Home → emulator slice

Date: 2026-09-24 (evening). Pi `party`, no USB Wi-Fi adapter (eth0 upstream, wlan0 AP), boot
`0d18f4ca`. Code: branch `experiment/ps1-title-profiles` (PS1) and `experiment/party-service`
(party service); both pushed, neither merged. Laptop-side "phones" are Playwright Chromium on the
home LAN reaching the Pi over **eth0** — **not real phones, not the party Wi-Fi**.

## Verdict

- **Bomberman boots, streams, and takes input from 4 independent phone slots.** Proven through the
  full phone path (page → WebSocket → XTest key bank → Multitap on port 2): P1 moved only the white
  bomber, P2 only the black, P3 only the red, P4 only the blue, in a real match. P2 cannot drive P1's
  menus. Audio is produced (private sink peak 5213, RMS 244).
- **Power is not the limit any more.** 7 bounded supervised runs (5–10 min, up to 5 viewers, arcade co-running,
  load average up to 14.9): every sample `0x0`, **0 kernel under-voltage lines**, ARM held 1800 MHz,
  max 54.0 °C, every run cleaned up (no PS1 process left); likewise the emulator-only run and 5 party-launched sessions.
- **CPU is the limit.** With the live arcade running (Gauntlet II uses ~1.4–1.7 cores **with nobody
  playing**), the PS1 emulator is starved and the game runs slow:

  | Capture | Viewers | Audio frames | Emulated fps in gameplay | Source |
  |---|---|---|---|---|
  | 640×480 | 5 | 10 ms | ~21 (≈35% speed) | in-game match clock vs wall clock |
  | 640×480 | 1 | 10 ms | ~29 (≈49%) | in-game clock |
  | 320×240 | 5 | 10 ms | 35–43 | RetroArch FPS overlay, demo match |
  | 320×240 | 5 | **20 ms** | 40–44 | overlay, demo match |
  | 320×240 | 1 | 20 ms | 60 (FMV) | overlay |
  | emulator alone (no stream) | — | — | 1800 frames in 33.5 s incl. start ≈ full speed | `--max-frames` |

  Per-thread profile of the stream process (320×240, 5 viewers): **each viewer costs ~14% of a core**
  in its own payload/SRTP threads (~9.5% video, ~4.5% audio); capture + encode ~20% in total.
  Pi 4 = 4 cores: PS1 RetroArch (~1–1.2) + stream (~1.2 at 5 viewers) + **arcade (~1.7)** > 4.
- **So the next real test needs the arcade stopped** (owner sudo), and should run at 320×240. That is
  not verified yet; it is the expected fix, based on the emulator-alone and 1-viewer numbers.

## What changed in code (all experiment branches)

PS1 (`experiment/ps1-title-profiles`):
- `--capture 320x240` (PS1 native size; the phone page upscales), `AVRANA_PS1_SHOW_FPS=1` (RetroArch
  draws its real FPS into the stream — the only reliable speed meter), 20 ms Opus frames.
- `tools/supervised-run.sh`: one bounded run, detached from SSH, per-second power log, stops the
  stream on live under-voltage / > 80 °C / new kernel dips / a stop file; writes a verdict.
- `tools/phones.mjs`: laptop simulated phones (control file: presses, screenshots, metrics, leave,
  reload, per-phone stage screenshots).
- **Party mode:** when the party starts the stream, a controller slot comes **only** from a seat
  ticket (below); the page returns to Party Home when the party's game ends.
- **Personal Viewports on the real stream** (`--viewports split2|quad`, experiment): server-issued
  crop rectangles per slot in the `player` message; client-side CSS crop; Full view toggle.

Party service (`experiment/party-service`):
- `runtimes.py`: 'service' games. The host picks a PS1 title → the party starts `stream_ps1.py` on
  127.0.0.1 → Party Home shows "Starting …" (+ host Cancel) → navigation moves only when the stream
  answers → the front door proxies **exactly** `/ps1/<title>/` and `/ps1/<title>/ws` (never `/stats`,
  never cookies). End game / switch / cancel / party end stop the emulator; a crash brings everyone
  home. One emulator at a time. Manifest v0 PS1 entries now have `entry` paths and are in the catalog.
- **Seat tickets v1 (ROADMAP F5, smallest version):** per-launch random key in the game's
  environment; a seated phone's own party view carries `v1.<slot>.<exp>.<game>.<hmac>` (5 min);
  the PS1 page sends it in its hello. Games never see device tokens, presence ids or names.
- Linux bug found and fixed on the Pi: `PR_SET_PDEATHSIG` fires when the *spawning thread* exits, so
  an emulator spawned from a short-lived thread died at once; one long-lived worker thread per
  runtime now spawns and stops.

## End-to-end on the Pi (dev front door :8190, 2–4 simulated phones)

`experiments/party-service/e2e-ps1-party.mjs`, run 3× green:
Party Home join → host starts Bomberman → "Starting…" → **both phones followed 4.5 s later** →
Ben taps Play first but is **Player 2**, Ana **Player 1** → a late joiner gets an open seat
(`late_join: supported`) and is **Player 3** → an outsider who never joined can **only watch** →
Ben reloads and is **Player 2** again → `/ps1/bomberman/stats` and `/ps1/worms/` answer 503 → the
host goes back to Party Home (banner, not yanked) and ends the game → **the guest is home 0.1 s
later**, the emulator is stopped, nothing is left running, `0x0`.

## Personal Viewports on the real PS1 stream (stage B, partly)

`--viewports quad`, 320×240 capture, 4 players + 1 watcher: each phone shows exactly its quadrant of
the ONE shared H.264 frame (tiled, the four crops rebuild the frame with no seam); the watcher sees
the full frame; `/stats` still counts 1 video + 1 audio encoder. **Stage B's frame-rate criterion is
not met** (viewers 31–47 fps with the arcade co-running). A 320×240 quadrant is 160×120 source
pixels: title text readable but soft. Bomberman is not split-screen, so this proves plumbing only;
stage C needs a split-screen title (candidates in `docs/design/PERSONAL-VIEWPORTS.md`).

## Not proven

Real iPhones (Safari decode, touch, sleep/wake), the party Wi-Fi path, audio by ear, input latency,
anything with the arcade stopped, sessions longer than 10 minutes, Worms in the party flow, 5 players
(pad 2D has no phone slot; set Player 5 to COM or off in the menu), TV/KMS mode.

## Raw evidence (Pi, not in Git)

`~/avrana-lab/ps1/evidence/runs/20260924T{174939,175542,180758,181503,182210,185152,192233}-bomberman/`
(`summary.txt`, `power.jsonl`, `stats.jsonl`, `stream.log`); party slice logs
`~/avrana-lab/party-svc-run/`.
