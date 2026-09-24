# Personal Viewports — proof of concept (experiment; not production)

Stage A of `docs/design/PERSONAL-VIEWPORTS.md`: prove that several phones can show the **same
source frame** while each renders **only its assigned seat's crop**, using client-side crop
metadata. No Pi, no emulator, no ROMs, no new streaming architecture, no dependencies beyond
Python's standard library and a browser.

## What it is

- `serve.py` — a tiny stdlib HTTP server. It hands each browser a **seat** (a random id kept in the
  browser's localStorage gets the same seat back after a reload; a new browser gets the lowest free
  seat; when all seats are taken the viewer is a spectator with the full frame) and serves the crop
  geometry for that seat from `../viewport_geometry.py` — the same code the 16 geometry tests pin.
- `index.html` — the phone page. It draws a synthetic **split-screen "game" frame** (coloured
  P1–P4 regions with white dividers, a moving ball, a millisecond clock and a frame counter) from a
  **server-synchronised clock**, so every phone draws identical pixels for the same instant. The
  frame goes into a `<video>` via `canvas.captureStream()` — the same element type a WebRTC stream
  plays in — and the seat's crop is applied as **static CSS** on that element (scale + offset inside
  an `overflow:hidden` window). Browsers without `captureStream` crop the canvas with the identical
  CSS (the footer says which path is active).
- Controls: **Full view** toggle, **press-and-hold** the picture to peek at the full frame,
  **Leave seat**. The header shows the seat, the crop rectangle and aspect, the screen orientation
  and which orientation the crop prefers (with a "rotate your phone" hint when they disagree). The
  footer shows clock-sync accuracy and the video frame-gap p50/p95 (`requestVideoFrameCallback`).

## Run it on your phones (laptop + phones on the same Wi-Fi)

```bash
cd experiments/viewports/poc
python serve.py                 # listens on 0.0.0.0:8765 (Windows may ask to allow Python through the firewall)
```

Find the laptop's IP (`ipconfig` → Wi-Fi IPv4, e.g. `192.168.1.23`) and open on each phone:

- `http://<laptop-ip>:8765/?layout=4` — four quadrants (4 phones get seats 1–4; a 5th spectates)
- `?layout=2h` — two players, top/bottom (8:3 crops: hold the phone in **landscape**)
- `?layout=2v` — two players, left/right (2:3 crops: **portrait**)
- `?layout=3` — one half + two quarters
- add `&mode=full` to start in full view; `&source=canvas` to force the canvas path

**Shared source (WebRTC, 2026-09-24):** open `http://<laptop-ip>:8765/?role=source&layout=4` on
ONE device (the laptop is fine): it draws the frame once and streams it. Then each phone opens
`?layout=4&source=rtc`: it receives that one stream over WebRTC (LAN only, no STUN/TURN; signalling
through the PoC server), decodes it, and crops its seat with the same CSS. The source also stamps
its draw time into the bottom 8 rows as a 32-bit barcode, so each viewer shows **latency p50/p95** =
source draw → encode → network → decode → frame callback (not glass-to-glass: no display or touch
time). The barcode is visible as a stripe at the bottom of seats 3/4 — it is a test pattern.

What to look at: put two phones side by side — the clocks in their crops should read the same
time (the header shows the sync accuracy); reload one phone — it must keep its seat; rotate a
phone — the crop re-fits (contain) and the hint follows the crop's preferred orientation; press
and hold — the full frame appears, showing that every phone has the whole picture.

## Tests

```bash
python experiments/viewports/test_viewport_geometry.py         # 16 geometry vectors
python experiments/viewports/poc/test_poc_server.py            # 8 server tests
npx playwright test -c experiments/viewports/poc/playwright.config.ts   # 7 browser tests × Chromium + WebKit (WebRTC test: Chromium only)
```

(From this worktree, point Node at the main checkout's `node_modules`, e.g.
`NODE_PATH=<repo>/node_modules <repo>/node_modules/.bin/playwright test -c …`.)

- **Server (8):** WebRTC signalling round trip and limits (bad SDP, size cap, bounded memory); distinct seats that survive reconnects; a spectator when full; Leave frees the
  seat in every layout; geometry served equals the tested vectors; bad input (short id, unknown
  layout, bad JSON, negative Content-Length) refused; the page loads nothing from outside.
- **Browser (6 × 2 engines), on real rendered pixels:** for layouts 4, 2h, 2v and 3, every client
  gets a distinct seat and its crop shows only its own colour — including a ring scan 1–2 CSS px
  inside every edge, where divider or neighbour bleed would appear — while a full view shows every
  region of the one frame; the Leave button frees a seat that a spectator then gets; a reload keeps
  seat and crop; an 8:3 crop fits by width in landscape and hints in portrait; a 4:3 quadrant in
  portrait does not nag; the crop CSS is static across frames, and crop-vs-full frame gaps are
  recorded (Chromium, headless: identical — p50 16.7 ms, p95 33.4 ms both ways; not asserted).
- **Shared WebRTC source (Chromium):** one source page streams to four viewers; each gets a distinct
  seat and shows its own colour through the real VP8 codec. Measured on one laptop, headless
  (5 pages sharing one CPU): the 1–2 px edge rings of seats 1/2 had **0 off-colour pixels** (no
  encoder bleed across the 2 px dividers at 640×480), seats 3/4 only on their bottom edge (the
  barcode); latency p50 60–250 ms, p95 150–660 ms across runs — a headless-laptop number, NOT a phone
  number. Latency is asserted only as p50 < 1 s. Playwright's Windows WebKit has no usable WebRTC,
  so the iPhone path is a manual test.

## What this proves — and what it does not

| Owner's assertion | Status |
|---|---|
| 1. All clients may receive identical source imagery | **Shown for a browser source** (`?role=source` + `?source=rtc`): one page encodes once per viewer (browser WebRTC encodes per peer connection) and every viewer decodes the same source frames. Still simulated: the Pi's single shared hardware encode (stage B) and H.264 — Playwright's Chromium has no H.264, so the test uses VP8. The default mode (no `source=`) still draws locally per client. |
| 2. Each client can show a different crop | **Proven** (pixel tests, every layout and seat, both engines). |
| 3. Cropping adds no meaningful application-side latency | **Supported.** The crop is one static CSS rule (no per-frame work, test-verified); headless frame gaps are identical crop vs full; the WebRTC mode now measures source→viewer frame latency per phone (the barcode). Input-to-photon latency is still not measured. |
| 4. Orientation / aspect behaviour understood | **Tested for 8:3 and 4:3** (contain-fit; the rotate hint appears only when rotating makes the picture ≥ 1.5× bigger). 2:3 portrait crops fit by the same code but have no dedicated test. |
| 5. Reconnect doesn't change a player's view | **Proven for a reload in the same browser.** Not held across: a server restart (seats are in memory and re-issued in reconnect order), a private tab that was closed (new id), or a URL without the same `?layout=`. |

**Deviations from stage A in the design doc:** the source is a canvas stream (locally drawn, or one
browser source over VP8 WebRTC), not an H.264 test video, so H.264 edge bleed and bitrate per quadrant
are untested (the Pi encoder must be tested in stage B); dividers are 2 px, not 1 px; the doc's canvas `drawImage` crop mode is not built (the
canvas path here crops the canvas element with the same CSS); there is no `seat=` URL parameter
(the server assigns seats); layout `3` is one half + two quarters (the design doc's alternative
"three quadrants + shared map" is covered only by the geometry tests).

**Known limits of the toy server:** seats never expire — a phone that closes the tab without
pressing Leave keeps its seat until the server restarts, and anyone on the LAN could take every
seat with made-up ids (it's a demo, not the party service). In CI-style runs, Playwright's Windows
WebKit has no `captureStream`, so WebKit exercised the canvas fallback and Chromium the MediaStream
`<video>` path; real iOS Safari supports `captureStream` — confirm on a phone. If autoplay is
blocked (e.g. Low Power Mode) the page shows a "Tap to start video" button.

**Bug fixed 2026-09-24:** the crop window was sized only on window resize; when the footer wrapped to
more lines later (e.g. once latency stats appeared on a narrow phone), the stage shrank and the
window's top and bottom rows were clipped. The page now re-fits on any stage size change
(`ResizeObserver`); the WebRTC test caught it.
