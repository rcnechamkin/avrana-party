# ADR 0001 — Load / soak / fault / regression harness

Status: accepted · Date: 2026-09-20

## Context

The Avrana Party arcade (one emulator → one HW H.264 encode → per-phone WebRTC)
had good ad-hoc verification (Playwright E2E, a real 2-phone session, the
read-only `arcade/capture-load.py` /stats poller) but **no repeatable way to**:

- hold N clients under load for a sustained window (soak) and get a pass/fail;
- inject client faults (abrupt drop, churn, over-subscription) and assert recovery;
- detect regressions in the streaming path automatically;
- measure server/client behaviour over time (e.g. the audio-latency drift).

Two known code-level reliability issues (audio capture-age ratchet; fatal-error
non-restart — see `docs/findings/2026-09-20-audio-ratchet-and-recovery.md`)
require a `stream.py` change + service restart to fix, which needs root. In this
session passwordless `sudo` was unavailable, so shipping those blind would risk
the working WebRTC path with no way to verify. A harness that touches none of the
service is the highest-leverage, fully-verifiable improvement, and it becomes the
before/after tool for those fixes.

## Decision

Add a reusable **load / soak / fault / regression harness** driven from a machine
on the Avrana Party Wi-Fi, in three layers:

1. **`tests/lib/soak-metrics.ts`** — pure functions (median/percentile, per-client
   and server summaries, threshold `evaluate`, `formatReport`). No I/O, no
   Playwright → unit-tested in isolation (`tests/soak-metrics.spec.ts`).
2. **`tests/lib/soak-driver.ts`** — Playwright helpers: `connectClient`,
   `tryConnect` (tolerates rejection), `readClientMetrics` (reads the page's own
   `#metrics`), `sampleServer` (/arcade/stats), `assertReachable` (fast, actionable
   failure when the laptop drops off the AP).
3. **Specs** — `tests/soak.spec.ts` (N clients held for a duration, sampled, gated,
   JSON artifact) and `tests/fault.spec.ts` (abrupt drop, churn, over-subscription
   → recovery). Both tagged **`@heavy`** so the everyday `npm test` stays fast.

### Threshold philosophy (important)

The load model is **N Chromium clients co-located on ONE laptop over a sometimes
flaky Wi-Fi link** — pessimistic for client-side jitter/RTT vs N independent
phones (real phones: ~31 ms jitter; co-located Chromium: 30–130 ms depending on
contention). So the **hard gates are the signals that stay meaningful**: server
did not error, the expected number of clients connected, median per-interval
packet loss is 0, and fps did not collapse (median ≥ 45, floor ≥ 20). jitterBuf
and RTT are **reported, not gated**. Real phones remain authoritative for absolute
latency/jitter.

### Run it

```bash
npm run soak                     # 2 clients, 90 s (defaults)
SOAK_CLIENTS=4 SOAK_SECONDS=600 npx playwright test tests/soak.spec.ts --project=chromium   # 4-client 10-min soak
npm run fault                    # fault injection & recovery
npm test                         # fast suite (excludes @heavy)
```

Artifacts land in `test-results/soak/` (per-run JSON + attached report).

## Consequences

- **Pros:** repeatable 1–N load/soak + fault/recovery + regression gates with zero
  changes to the WebRTC stack; a reproducer + before/after tool for the audio and
  recovery fixes; pure logic is unit-tested.
- **Limitations:** co-located Chromium ≠ real phones (client-side jitter is
  pessimistic; that's why it isn't gated). Context-close is a clean TCP FIN, not a
  silent network partition (that needs packet-level tooling + the WS heartbeat).
  The laptop's Wi-Fi to the AP drops intermittently — an environmental flake that
  can interrupt long runs (`assertReachable` fails fast; a stable AP client or
  disabling the adapter's Wi-Fi power-save is the real fix).
- **Side effect:** running a soak connects real peers, which ratchets the audio
  capture-age bug; it resets on service restart.
