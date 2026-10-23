# Local performance baseline (AVR-138), 2026-10-19

**Evidence: local loopback simulation.** Party Core, the Games server, BLUFF and dodgeball are real processes. Phones are Python clients on the same machine. **Nothing here is a Pi, the party radio or a phone.** No hardware requirement follows from these numbers. The procedure for those measurements is in [performance-measurement](../runbooks/performance-measurement.md) §2 (owner-run, not run).

**Harness:** `tools/perf/party_perf.py` at Party `d38d770`, with Games `a84017f` (Linux) and `e0d2035` (Windows). Each scenario was repeated with fresh processes. Each figure below is the median across repeats.

**Raw results** are in [`perf/`](perf/):
- **Linux:** aggregates and growth series, relayed from a cloud session. The values are verbatim; one HTML-escaped `>` was restored.
- **Windows:** the full result document.

| Host | Party / Games | Repeats |
|---|---|---|
| **Linux** (headline): KVM container, 4 vCPUs (Xeon @ 2.1 GHz per the run's `lscpu`, relayed; not in the JSON), 16 GB, Python 3.13.16 | d38d770 / a84017f | 3 (growth: 2 × 20 cycles) |
| Windows 11 laptop: 4 logical CPUs, Python 3.12.3 | d38d770 / e0d2035 | 3 |

## Party Core

| Measure (Linux) | 1 phone | 4 phones | 8 phones |
|---|---|---|---|
| host action POST, p50 / p95 | 1.9 / 2.5 ms | 2.6 / 4.5 ms | 3.1 / 6.5 ms |
| tap → every phone's long poll has it, p50 / p95 | 1.8 / 2.6 ms | 3.2 / 4.8 ms | 4.7 / 7.0 ms |
| Party Core CPU during 30 back-to-back moves | 4.8% | 7.8% | 12.0% |
| response bytes per phone per update* | 3.4 KB | 2.4 KB | 2.8 KB |

*The figure includes the host's extra state read and POST reply, spread over the phones (3, 1.5 and 1.25 requests per phone per update). One state view is about 1.1, 1.6 and 2.2 KB.

- **At rest:** 24.7 MB RSS and 2 threads. With 8 members waiting: 25.3 MB, 10 threads, 0.05% CPU. A waiting long poll holds one thread (ThreadingHTTPServer, capped by `MAX_WAITERS = 64`).
- **Idle cost per phone:** one 20.0 s poll, so 3 requests and 5.7 KB per minute.
- **Repeat variability** for Party Core and the lifecycle was small: the cv of p50 across repeats was at most 0.13.

## BLUFF lifecycle (4 phones, real Games server)

| Measure (Linux) | p50 |
|---|---|
| Start: Party Core's launch call to the running Games server | 7.3 ms |
| ticket + WebSocket hello + first state | 5.1 ms |
| one phone's reconnect (state read, ticket, hello) | 7.6 ms |
| End | 7.9 ms |
| everyone home after End (p95) | 10.7 ms |

- **Games server at rest:** 56 MB RSS. With 4 BLUFF phones at rest it uses 0.2% CPU.
- **Growth over 20 cycles:**
  - Party Core: +0.28 MB, threads flat at 6.
  - Games server: threads flat at 1. RSS rises +1.5 MB on the first cycle, about +0.3 MB per cycle through cycle 7, then about +0.035 MB per cycle through cycle 20 (+3.6 MB in total).
  - Most of it looks like warm-up, but the climb slows rather than stops, and 20 cycles cannot tell a slow leak from caching. Watch item.

## Realtime game (dodgeball, standalone, real 30 Hz simulation)

| Measure (Linux) | 2 players | 4 players | 6 players |
|---|---|---|---|
| full state frames received per client | 51/s | 74/s | 96/s |
| decoded payload per client | 155 KiB/s | 219 KiB/s | 364 KiB/s |
| server output, all clients (decoded) | 0.30 MiB/s | 0.86 MiB/s | 2.13 MiB/s |
| Games server CPU | 4.6% | 7.8% | 14.4% |
| ping through the WebSocket handler, p95 | 1.6 ms | 3.1 ms | 5.0 ms |

- **Above 2 players the input rate, not the tick, drives the fan-out.** The frame counts match 30 + 11 × players within 2%, where 11 Hz is the rate the harness sends joystick input (dodgeball.js's rate while moving).
- **Cause:** `core/net.py` `GameBinding.push_all` sends every socket its full per-player state after **every** dispatched message. That includes `move`, which changes only an intent the next tick reads.
- **Scaling:** messages grow with players² × input rate. Payload per state frame is about 3.0 KiB at 2-4 players and 3.8 KiB at 6, including the non-state messages.
- **Upper bound:** every simulated player moves the stick for the whole window. A player who stands still sends only dodgeball.js's 4 Hz keepalive, so real rounds sit below these figures.
- No pings were lost or ambiguous. The harness used at most 15.2% of a core, so these results are not client-bound.
- The ping p50 varied across repeats (cv 0.20-0.30), so the 2/4/6-player ping differences are within noise.

## Bottlenecks and uncertainty

| # | Observation | Confidence | What would settle it |
|---|---|---|---|
| 1 | **Realtime fan-out** is the largest measured cost and grows quadratically: up to 2.1 MiB/s of state for one 6-player round with everyone moving. On the party radio that is airtime, not just CPU. | High for the mechanism and the local numbers. Unknown on the radio: permessage-deflate and the AP were not involved. | AVR-301-style radio measurement. A Games change that broadcasts on the tick only, then this harness again (AVR-674, Games owner's decision). |
| 2 | **Party Core** answers 8 phones in single-digit ms and is mostly idle. It is not a bottleneck at the 8-phone target on this host. | Medium: a KVM Xeon core is several times a Pi core, by an unmeasured factor. | §2 step 2 of the runbook (harness against the Pi). |
| 3 | **One thread per waiting phone** in Party Core: 10 threads for 8 phones, bounded at 64 waiters. | High; cheap at party scale. | None needed now. |
| 4 | **Games server RSS** grows fast over the first ~8 rounds, then slowly (about 0.035 MB per round). | Low: 20 cycles. | A 100+ cycle soak in one process. The harness caps a run at 20 cycles, so a soak needs that bound raised deliberately. |
| 5 | **Windows numbers are noisier.** In the archived Windows run, the 8-phone propagation p50 was 78 ms (repeats 74-88) and the p95 660 ms, against 4.7 and 7.0 ms on Linux. Dodgeball used 30% CPU at 6 players against 14%. *Unarchived observations:* an earlier Windows run with the first harness commit (8b8a678) had an 8-phone p50 of 6 ms; an ad-hoc probe showed ~14 ms connect stalls on a host POST and 21 state frames/s with no input. | High for Party Core: Linux at the same Party commit is tight. The dodgeball comparison is confounded (Games e0d2035 on Windows, a84017f on Linux). | Use Linux hosts for kept numbers (runbook); compare games at one Games commit. |

**Not measured here:** phone rendering, CPU or memory; the radio (airtime, retries, roaming); nginx/TLS; the Pi's CPU, thermals and power; browser package cold and warm launch; streaming and encoding; wire bytes after WebSocket compression. Each needs §2 or another ticket (AVR-139, AVR-301, AVR-302, AVR-507).
