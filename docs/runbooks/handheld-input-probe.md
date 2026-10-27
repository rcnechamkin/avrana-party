# Handheld input probe: hardware worksheet and compatibility matrix (AVR-330)

Status: **PROPOSED owner/tester procedure, NOT RUN on any handheld** (2026-10-26). The probe and its synthetic
tests exist in source; no physical Android handheld has been tested. **AYN Thor and Anbernic RG Rotate are
UNVERIFIED.** Chrome desktop responsive mode is not hardware proof and is never recorded as such.

## What exists

| Piece | Where | Evidence level |
|---|---|---|
| Probe module | `web/party/lib/input-probe.js` (schema `avrana.input-probe/v0`) | source |
| Diagnostics section "Controller and input" | `/party/diag/`, button **Start input probe** (nothing runs until tapped) | source |
| Synthetic tests: Gamepad API missing or blocked, empty until the first press, nonstandard mapping, keyboard-emulation mode, connect and disconnect, touch fallback, id and text redaction, 720×720 viewport | `tests/offline/input-probe.test.mjs` (node), `tests/offline/diag.spec.ts` (Chromium, Tier 2) | **simulated** |

Privacy, by construction: a controller's id string (vendor, product, sometimes a serial) is never put in the
report; printable keys are recorded as `character`; there is no storage, telemetry or network call. The report
exists until the page closes, and the tester decides whether to copy it. The probe is on the diagnostics page,
which ordinary players do not reach from the party flow.

The probe reports what it **observed**, as `path`:
- `gamepad-standard`: a controller press arrived through the Gamepad API with the W3C standard mapping.
- `gamepad-nonstandard`: a controller press arrived, with the device's own numbering.
- `keyboard-emulation`: navigation keys arrived with no controller press.
- `touch-only`: only touch was seen.
- `nothing-yet`: nothing was seen.

A path is never a support claim.

## Before you start

- [ ] Record the exact model and variant: for example Thor Lite (SD865, 8 GB), Thor Base/Pro/Max (SD 8 Gen 2), or
  RG Rotate (T618, 3 GB). Also record the Android version, the browser and its version, and the controller mode
  setting (Xbox / Nintendo / keyboard / d-pad).
- [ ] The Pi runs a Party build that contains this probe. Updating the Pi is an owner action; this sheet does
  not authorise it.
- [ ] One ordinary phone (iPhone or Android) is ready for the mixed test.

## Session A: joining with no internet and no QR

| # | Step | Record |
|---|---|---|
| A1 | On the handheld, join the Party Wi-Fi by typing the SSID and password (no QR) | Did Android show "no internet" or "stay connected?"; which choice kept the connection |
| A2 | Open the browser and type the Party address by hand | Did the page load; how long it took; any certificate warning (wording) |
| A3 | Join as a guest | Name shown; seat; any keyboard problem with the name field |
| A4 | Move around Party Home with only the controller (no touch) | Can every control be reached; is focus visible; which buttons move and select |
| A5 | Start a game the Host picks; take one game action with the controller, then with touch | Which input worked |
| A6 | Sleep the screen for 30 s, then wake it | Did it reconnect to the same seat; how long it took |
| A7 | Turn Wi-Fi off for 10 s, then on | Same seat; any error shown |

## Session B: the probe

1. Open `/party/diag/` on the handheld and tap **Start input probe**.
2. Press every face button, the d-pad, the shoulders and triggers, both sticks, Start/Select/Home, then touch the
   screen once.
3. Switch the controller mode in the device's settings, return to the browser, and repeat step 2.
4. Rotate the device (RG Rotate: rotate the screen) and note the viewport line.
5. Tap **Stop input probe**, then **Copy report**, and paste the `input` object into the matrix row below.
   **Do not paste the user agent line** into a public place.

| # | Record from the probe | Why |
|---|---|---|
| B1 | Viewport: CSS px, DPR, device px, orientation, safe area | the RG Rotate's 720×720 panel; layouts must fit the **CSS** size |
| B2 | Gamepad API and secure context | some browsers hide gamepads outside https |
| B3 | Path and the controller's mapping, button and axis counts | what a game can rely on |
| B4 | Which button indexes each physical button produced (write the physical label next to each index) | a nonstandard device needs a binding table (AVR-137) |
| B5 | Keys seen in keyboard mode | whether navigation works without the Gamepad API |
| B6 | Timeline around sleep, wake and mode switch | connect and disconnect behaviour |

## Session C: mixed play (only when hardware is available)

One ordinary phone and one handheld in the same party: join, play a full round of a turn-based game, and then a
round of a real-time game if one is installed. For each round record: who could act, input latency as felt
("immediate" / "noticeable" / "unplayable"), any stuck controls, the result screen, and the return to Party.

## Compatibility matrix

Every row is **NOT RUN** until a person fills it in from a real device. Write "simulated" only for the synthetic
tests.

| Device (variant) | Android / browser | Controller mode | A: join offline | B path | Mapping (buttons/axes) | CSS viewport @DPR | Sleep/reconnect | C: mixed play | Tester, date |
|---|---|---|---|---|---|---|---|---|---|
| Synthetic (node and Chromium) | – | – | – | all six paths exercised | 17/4 standard; 11/8 nonstandard | 360×360 @2 (720×720); 390×664 @3 | simulated connect/disconnect | – | tests, 2026-10-26 |
| AYN Thor (variant?) | ? | ? | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | – |
| Anbernic RG Rotate | ? | ? | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | – |
| Any Android phone already available | ? | ? | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | – |

## Compute and performance (AVR-330 viability gate)

This probe does not measure frame rate, WebGL2/WebGPU/WASM performance, thermals or memory pressure. The
capability report on the same diagnostics page records WebGL2 and WebGPU presence ("Run deep checks"). Sustained
FPS and thermal runs need a representative game loop and are a follow-up (AVR-138). Record them separately, and
never infer browser performance from the device's native emulator performance.

## Follow-ups this sheet is expected to produce

- A binding table per observed nonstandard mapping (AVR-137), and only from real B4 rows.
- Any layout that breaks at the measured CSS viewport (Party or game), filed with the B1 numbers.
- Any join failure from session A, filed against onboarding (AVR-11 / AVR-76).
