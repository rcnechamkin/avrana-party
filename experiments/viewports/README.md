# Personal Viewports geometry — test vectors (experiment)

Math only, for `docs/design/PERSONAL-VIEWPORTS.md`: which rectangle of the ONE shared encoded
frame each seat's phone shows, and the arithmetic a client uses to crop it. No browser, no
video, no Pi; nothing in production imports it.

```bash
python experiments/viewports/test_viewport_geometry.py
```

What the vectors fix (640×480 square-pixel 4:3 capture, today's PS1/arcade setup):

| Layout | Seat crop aspect | Best orientation | On an iPhone landscape box (750×369) |
|---|---|---|---|
| 4 quadrants | 4:3 | either | 492×369, fills 66% |
| 2 players top/bottom | 8:3 | landscape | 750×281, fills 76% (portrait: ~17%) |
| 2 players left/right | 2:3 | portrait | better in portrait |
| 3 players (half + two quarters) | 8:3 / 4:3 / 4:3 | mixed | — |
| 3 quadrants + shared map | 4:3 (map is not a seat) | either | — |

Also pinned down: the inset that trims divider lines/edge bleed; letterboxed content areas; the
CSS `width/height/left/top` for a `<video>` inside an `overflow:hidden` container (round-trips
exactly to the seat rectangle); the `drawImage` source rectangle for a canvas crop; H.264
macroblock alignment (640×480 and 1280×960 put every split on a 16-px edge; 1280×720 and
1920×1080 do not); and native detail (a quadrant of a 320×240 PS1 game holds 160×120 native
pixels).

The profile shape used here is a **draft**; the real metadata format is still open.
