# Device requirements in the Game Contract (AVR-469)

Status: **EXPERIMENTAL, additive.**

Implemented in source, run only against simulated phones
(Tier 2); no real phone, Safari or Pi has seen it. Changes no frozen schema field: a game that
declares nothing behaves exactly as before.

## What it is

A presentation may declare measured device needs under `requires.device_caps`, beside the
existing `requires.device` list of named capabilities (which keeps its meaning):

| key | value | checked by Party Home by |
| --- | --- | --- |
| `memory_mb` | whole number, 1 to 4096 | reserving a WebAssembly memory of that size, then letting it go: a refusal fails; a success only shows the reservation is possible (pages are not touched, so it does not prove the RAM) |
| `shared_memory` | `true` / `false` | **not checkable here** (see below) |
| `webgl2_offscreen` | `"worker"` or `"main"` | making a WebGL 2 context on an OffscreenCanvas, in a Worker (`lib/device-probe-worker.js`) or on the page |
| `opfs` | `true` / `false` | `navigator.storage.getDirectory()` |
| `storage_mb` | whole number, 1 to 102400 | `navigator.storage.estimate()`: free space (quota minus usage) |

The validator (`avrana/contracts/game.py`) refuses unknown keys, wrong types and implausible
values; it allows the object only under `requires`, never `optional`, and not without at least one
real requirement (an object of only `false` values is refused). The catalog
build passes it through to `web/party/catalog.json` only when declared. The browser side is
`web/party/lib/device-check.js`. The same keys are what the OpenCE page's own preflight checks
(rcnechamkin/avrana-party-games#73, not merged); the two are independent and neither imports the other.

## What the phone sees

The setup panel keeps the existing Play/Watch choice. Before it offers Play for a game that
declares needs, the phone runs the probe (once per page, then kept). Results are per check:

- **fail**: Play is disabled, Watch stays open, and the panel says in plain words what is missing
  ("This phone does not have enough free storage for this game (about 2000 MB). You can watch
  this one."). Nobody else's choice changes.
- **unknown** (the probe threw, took longer than its time limit, or the API does not report; each
  check has a limit, and the whole probe another, so a check that never finishes cannot hold Play): never a pass, and does not
  block Play. It is shown: "Could not check this phone's memory. The game checks again when it
  starts."
- **launch** (`shared_memory` only): neither pass nor fail: "The game checks this phone's shared
  memory when it starts."

While the probe runs Play waits ("Checking that this phone can run it..."); Watch never does. No
new Party Core route or message, no change to the session lifecycle or Host flow.

## What it can and cannot prove

- Party Home is **not cross-origin isolated**, so `SharedArrayBuffer` and shared
  `WebAssembly.Memory` cannot be proven there. The game page's own preflight stays the final check
  for every requirement; this panel only keeps a phone that clearly cannot run the game from being
  offered Play.
- Memory, OPFS and storage are measured on Party's origin, standing in for the game's origin. A
  separate origin has its own storage usage; a phone's memory ceiling is the browser's.
- A reservation succeeding now does not mean the game will keep running; one failing is strong
  evidence it will not.
- The probe's memory is freed when the browser collects it, so the probe runs once per page.
- Worker probing uses a file of Party's own origin (the shell's `worker-src` is `'self'`); the CSP
  is unchanged.
- Real phones (low-memory Android, iPhone Safari) are Tier 3 and the owner's.

## Tests

`tests/unit/test_contracts.py` (`DeviceCaps`), `tests/offline/device-check.test.mjs` (decision logic
and probes with injected environments), `tests/party/device-requirements.spec.ts` (Chromium against
the dev server's Party Core: an impossible storage need leaves Watch; a no-requirements phone is
unchanged).
