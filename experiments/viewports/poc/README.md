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

Find the laptop's IP (`ipconfig` → Wi-Fi IPv4, e.g. `10.0.0.174`) and open on each phone:

- `http://<laptop-ip>:8765/?layout=4` — four quadrants (4 phones get seats 1–4; a 5th spectates)
- `?layout=2h` — two players, top/bottom (8:3 crops: hold the phone in **landscape**)
- `?layout=2v` — two players, left/right (2:3 crops: **portrait**)
- `?layout=3` — one half + two quarters
- add `&mode=full` to start in full view; `&source=canvas` to force the canvas path

What to look at: put two phones side by side — the clocks in their crops should read the same
time (the header shows the sync accuracy); reload one phone — it must keep its seat; rotate a
phone — the crop re-fits (contain) and the hint follows the crop's preferred orientation; press
and hold — the full frame appears, showing that every phone has the whole picture.

## Tests

```bash
python experiments/viewports/test_viewport_geometry.py         # 16 geometry vectors
python experiments/viewports/poc/test_poc_server.py            # 5 server tests (seats, geometry, input, offline page)
npx playwright test -c experiments/viewports/poc/playwright.config.ts   # 4 browser tests × Chromium + WebKit
```

(From this worktree, point Node at the main checkout's `node_modules`, e.g.
`NODE_PATH=<repo>/node_modules <repo>/node_modules/.bin/playwright test -c …`.)

The browser tests read **real rendered pixels**: four clients get four distinct seats and each crop
shows only its own colour (centre and all four edges — the 2-px inset trims dividers and bleed),
while the same client's full view shows all four regions of the one source frame; a reload keeps
the seat and crop; an 8:3 crop fits by width in landscape and shows the rotate hint in portrait;
the crop CSS is static across frames.

## What this proves — and what it does not

**Proves:** identical source imagery per instant on every client; a different crop per client from
metadata alone; the crop is a one-time CSS change with no per-frame application work (so no
application-side latency is added); contain-fit and orientation behaviour for 4:3, 8:3 and 2:3
crops; seat stability across reconnects; spectators fall back to the full frame.

**Does not prove:** the real WebRTC path from the Pi (stage B, after the power problem is fixed);
H.264 edge bleed and bitrate per quadrant (the synthetic frame is perfect; the Pi encoder is not);
readability of a 160×120-native-pixel quadrant of a real PS1 game; decode behaviour on older phones.
In CI-style runs, Playwright's Windows WebKit has no `captureStream`, so WebKit exercised the
canvas fallback; Chromium exercised the MediaStream `<video>` path. Real iOS Safari supports
`captureStream` — confirm on a phone.
