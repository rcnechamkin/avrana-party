# Personal Viewports (split-screen extraction)

Status: **concept + feasibility analysis (2026-09-24). Not built.** Metadata format is OPEN.
Geometry test vectors: `experiments/viewports/` (branch `experiment/party-sim`).

## The idea

A traditional multiplayer console game renders **one** split-screen image:

```
┌────────┬────────┐
│  P1    │  P2    │
├────────┼────────┤          one emulator → one render → one capture → one H.264 encode
│  P3    │  P4    │          → the SAME encoded frame sent to every phone
└────────┴────────┘
```

Avrana keeps that single pipeline, but **each player's browser shows only its own seat's crop**:
seat 1 sees the top-left quarter full-screen on their phone, seat 2 the top-right, and so on.
Four people get their own "screen" from a game that was designed for one TV — with no TV.

This could become a real differentiator: it turns the whole back catalogue of couch split-screen
games into private-screen phone games, which neither a Switch nor Jackbox nor AirConsole does.

## Why it fits the current architecture

The streaming path already sends **the identical encoded frame to every phone**: one encoder feeds
one appsink (`arcade/stream.py:145-156`), and `distribute` pushes the same buffer into each
viewer's appsrc (`arcade/stream.py:195-201`); PS1 reuses it (`ps1/stream_ps1.py`). So a
Personal Viewport is **a client-side change plus one metadata field**. No per-player encoder, no
change to capture, encode or WebRTC.

Two honest limits:

- **It saves encoders, not Wi-Fi.** Every phone still receives the whole frame (unicast WebRTC).
  Wi-Fi load stays N × bitrate.
- **It is not private.** Every phone holds every quadrant; a viewport can't hide anything. Games
  with secret per-player screens need native private UI, not cropping.

## How the phone crops (client-side)

| Approach | How | Cost | Verdict |
|---|---|---|---|
| **CSS** | `<video>` inside an `overflow:hidden` container with the crop's aspect; the video scaled to `100%/w` × `100%/h` and offset by `-x/w`, `-y/h` | 0 added frames, no per-frame JS, least battery; reuses today's element | **First PoC** |
| Canvas 2D | `drawImage(video, sx,sy,sw,sh, 0,0,dw,dh)` from `requestVideoFrameCallback` | 0–1 frame, one GPU copy per frame | When insets/inset maps/nearest-neighbour matter |
| WebGL | texture sampling / shaders | context loss, Safari upload cost | Later, if ever |

Notes: smoothing bleeds about one pixel of the neighbour into the edge, so trim each crop with a
small inset; on iPhone the only true fullscreen is the native player (which shows the uncropped
frame), so use a fixed-position `100dvh` pseudo-fullscreen; `object-view-box` is Chromium-only.
The stream is same-origin, so canvas isn't tainted (nothing reads pixels back anyway).

## Geometry

Crops are rectangles `(x, y, w, h)` normalized to the active **content area** of the capture;
the crop's display aspect is **a = (w/h) · D**, where D is the content's display aspect (4:3 for
PS1/N64-era). RetroArch already maps every PS1 video mode to square-pixel 4:3 in the 640×480
capture, so this holds regardless of the game's internal resolution.

| Layout | Seat rectangles | Crop aspect | Best phone orientation |
|---|---|---|---|
| 2 players, top/bottom | (0,0,1,½) (0,½,1,½) | 8:3 | landscape (76% of an iPhone landscape box; ~17% in portrait) |
| 2 players, left/right | (0,0,½,1) (½,0,½,1) | 2:3 | portrait |
| 3 players, half + two quarters | (0,0,1,½) (0,½,½,½) (½,½,½,½) | 8:3 / 4:3 / 4:3 | mixed |
| 3 quadrants + shared map | three quadrants; the fourth is a shared region, not a seat | 4:3 | either |
| 4 players | quadrants | 4:3 | either (landscape: 492×369 of 750×369, 66%) |

Fit rule: **contain** by default (the whole crop visible, bars elsewhere); cover cuts HUD off.
Wide crops (a > 1) want landscape, tall crops want portrait. The test vectors pin these numbers.

**Detail reality check:** a 4-player quadrant of a native 320×240 PS1 game is **160×120 native
pixels** (Game Boy Advance-class detail, ~3 CSS px per native pixel on a phone). It is playable
because it is exactly what each player saw on a split-screen TV, but it is not HD.

## Menus and full-screen moments (no auto-detection)

A crop is wrong on a full-screen menu. Without detection:

- default to the **full frame**; each seat opts into "My view", with a **hold-to-peek full view**;
- the **host** can switch split view on/off for everyone;
- the layout key is the **in-game player count the host chose** (not the number of connected
  seats), with variants like `2h` / `2v` where the game lets players choose;
- per-title adapters (menu detection, player-count detection via emulator/memory inspection or
  video analysis) are **future work**.

## Quality, bitrate, resolution

- Today: 640×480 capture, 2.5 Mbps, level 3.1, keyframe every 60 frames (`ps1/stream_ps1.py`).
  A quadrant gets ~¼ of the bits; four independently moving cameras compress far worse than
  Bomberman's static arena (~0.97 Mbps measured). Try 2.5 / 4 / 6 Mbps at 640×480@60, or 30 fps
  for twice the bits per frame. Wi-Fi load = phones × bitrate (4 × 6 Mbps = 24 Mbps).
- **Macroblock alignment:** 640×480 and 1280×960 put every split on a 16-px boundary; 1280×720
  (split at 360) and 1920×1080 (540) do not, which increases edge bleed. Prefer capture sizes that
  are multiples of 32.
- **Bigger capture ≠ better** at native resolution: 640×480 already holds every native pixel.
  A larger capture only helps with the emulator's 2× internal enhancement (~1280×960@30), which
  costs CPU the Pi 4 may not have (PS1 already uses ~1.2 cores of software GL). 1280×960 or
  anything ≥720p60 needs H.264 level ≥ 3.2; 1080p30 (level 4.0) is roughly the Pi 4 encoder's
  ceiling — **unverified**. One encoded 1080p stream would give a comfortable 960×540 per quarter,
  but it is not a realistic Pi 4 path today.

## Orientation, safe areas, controls

`screen.orientation.lock` works only in Android fullscreen and not on iOS: show a "rotate your
phone" hint instead. Use `env(safe-area-inset-*)` and `dvh`. When a crop is narrower than the box,
put the touch controls in the side bars (~130 px each on an iPhone landscape quadrant); overlay
translucent controls only for 8:3 halves.

## Seats and input

**Viewport seat = party seat = controller slot = RetroArch user = in-game player N.** PS1's
`claim()` already returns the slot to the phone (`mySlot`); the crop is `layouts[key].seats[slot]`.
The multitap port must make RetroArch's user order match the game's player order (Bomberman:
port 2, users 2–4 = pads 2A–2C) — verify per title. Spectators get the full frame (or follow a
chosen seat).

## Metadata (draft; format OPEN)

```json
"viewports": {"v": 0, "grid": [640, 480], "content": [0, 0, 640, 480], "aspect": "4:3",
  "inset": 2, "default": "full",
  "layouts": {
    "2h": {"seats": {"1": [0, 0, 640, 240], "2": [0, 240, 640, 240]}},
    "3":  {"seats": {"1": [0, 0, 320, 240], "2": [320, 0, 320, 240], "3": [0, 240, 320, 240]},
           "shared": {"map": [320, 240, 320, 240]}},
    "4":  {"seats": {"1": [0, 0, 320, 240], "2": [320, 0, 320, 240],
                     "3": [0, 240, 320, 240], "4": [320, 240, 320, 240]}}}}
```

Rectangles are authored in the pixel grid of a reference screenshot and normalized by the client.
It lives in a title's *capabilities* (see `GAME-INTEGRATION.md`), next to `video: shared_stream`.

## Smallest proof of concept (when ready)

1. **Stage A — laptop only, no Pi, no ROMs.** A static page plus a synthetic split-screen test
   video (four labelled, coloured quadrants with 1-px dividers and a frame counter, encoded
   constrained-baseline 640×480@60 at 2.5/4/6 Mbps, plus a 1280×960 variant), served from the
   laptop to a real iPhone and Android phone with `?layout=4&seat=2&mode=css|canvas`.
   **Pass:** each crop correct with no neighbour colour after the inset; contain-fit right in both
   orientations; full↔viewport switch instant; frame-gap p95 within ±2 ms of full-frame viewing.
   (Laptop x264 ≠ the Pi encoder, so bitrate judgements wait for stage B.)
2. **Stage B — Pi, after the power gate.** Client-only viewport mode in `ps1/index.html` with a
   hard-coded layout table, using Bomberman just for plumbing. **Pass:** `/stats` still reports one
   video and one audio encoder with 4 cropped phones; encoder ≥ 55 fps; viewers ≥ 45 fps.
3. **Stage C — a real split-screen title** with multitap (candidates to verify: Crash Team Racing,
   Speed Freaks, South Park Rally, V-Rally 2, Quake II for 4 players; Twisted Metal 2, Tony Hawk's
   Pro Skater 2, Chocobo Racing, Medal of Honor for 2). **Pass:** 4 players, 10 minutes, each
   phone's input moves the player in its own crop.

## Deferred

Automatic detection of menus/player count/layout; server-side per-seat crops or encoders;
per-region bitrate; secrecy; distributed multi-phone displays (see `PARTY-PLATFORM.md`, experimental
concepts); freezing the metadata format.
