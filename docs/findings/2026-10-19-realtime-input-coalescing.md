# Realtime input coalescing (AVR-674), before and after, 2026-10-19

**Evidence: local loopback simulation on one Windows 11 laptop.** The Games server and dodgeball's simulation are real processes. Players are Python WebSocket clients on the same machine. **Nothing here is a Pi, the party radio or a phone.**

**Change measured.** Games PR `claude/avr-674-realtime-coalesce`: a dodgeball `move` no longer triggers its own full-state push to every socket. The next simulation tick's broadcast carries it.

**Runs.** `tools/perf/party_perf.py --only realtime --rt-clients 2,4,6 --repeats 3` (default `--rt-mix moving,mixed`, 5 s windows). Party harness at `53f1a57`.
- **Before:** Games `4acc5ae` (main).
- **After:** Games `f69a68f`.

Both runs were back to back on the same host, configuration and harness. Each figure is the median across 3 fresh-process repeats; ranges are in the JSON. All 36 repeats succeeded.

Raw results:
- [`perf/2026-10-19-windows-avr674-before-games-4acc5ae.json`](perf/2026-10-19-windows-avr674-before-games-4acc5ae.json)
- [`perf/2026-10-19-windows-avr674-after-games-f69a68f.json`](perf/2026-10-19-windows-avr674-after-games-f69a68f.json)

## Traffic

| Workload | state frames per client per s | of which repeat the last tick | decoded payload per client | server output, all clients | Games CPU (% of one core) |
|---|---|---|---|---|---|
| 2 moving | 43.4 → **22.0** | 21.0 → **0** | 130 → **68** KB/s | 0.25 → **0.13** MiB/s | 6.9 → 4.4 |
| 4 moving | 66.4 → **23.1** | 42.2 → **0** | 197 → **74** KB/s | 0.77 → **0.29** MiB/s | 11.5 → 4.7 |
| 6 moving | 81.9 → **23.2** | 58.6 → **0** | 311 → **94** KB/s | 1.82 → **0.55** MiB/s | 27.4 → 8.3 |
| 2 mixed (1 idle) | 36.8 → **22.4** | 13.6 → **0** | 111 → **69** KB/s | 0.22 → **0.13** MiB/s | 5.0 → 3.7 |
| 4 mixed (2 idle) | 52.3 → **22.6** | 27.7 → **0** | 157 → **72** KB/s | 0.61 → **0.28** MiB/s | 10.2 → 7.5 |
| 6 mixed (3 idle) | 67.7 → **23.8** | 42.6 → **0** | 258 → **96** KB/s | 1.51 → **0.56** MiB/s | 20.2 → 15.0 |

- **State frames now equal the tick rate.** After the change, no frame repeats a tick, and frames per client match the ticks the client saw within 1.
- **Six players moving: 70% less server output** (1.82 → 0.55 MiB/s). Output now grows with players × tick rate, not players² × input rate.
- **Games CPU fell in every workload.** Windows CPU accounting is coarse and the ranges overlap at 2 players, so take the direction, not the exact percentages.
- **Games RSS was unchanged:** about 59 MB both times.

## Responsiveness and the tick

| Workload | input to authority p50 / p95 (ms) | frame age p50 / p95 (ms) | ticks seen per s | gap between new ticks p95 (ms) |
|---|---|---|---|---|
| 2 moving | 126 / 143 → 126 / 142 | 1.4 / 6.0 → 1.4 / 5.1 | 22.3 → 21.8 | 56 → 51 |
| 4 moving | 116 / 146 → 125 / 143 | 1.7 / 5.2 → 2.1 / 6.6 | 24.0 → 22.9 | 51 → 51 |
| 6 moving | 113 / 160 → 115 / 145 | 2.5 / 13.7 → 2.8 / 8.7 | 23.8 → 23.0 | 65 → 52 |
| 2 mixed | 116 / 146 → 127 / 143 | 1.5 / 8.9 → 1.6 / 5.4 | 22.8 → 22.2 | 55 → 51 |
| 4 mixed | 126 / 139 → 127 / 169 | 1.8 / 8.1 → 2.0 / 7.6 | 24.4 → 22.4 | 55 → 54 |
| 6 mixed | 110 / 138 → 125 / 136 | 2.3 / 9.1 → 2.7 / 8.0 | 24.8 → 23.6 | 58 → 53 |

- **Input to authority** is a joystick reversal timed until a state frame shows the player's own unit moving the new way.
  - It did not change measurably: p50 is 110-127 ms before and 115-127 ms after, with overlapping ranges.
  - Most of it is physics, not delivery: velocity eases toward the stick (`ACCEL_TAU` 0.10 s), and a reversal must cross zero.
  - The removed echo frames carried no new tick, so they could never show an input sooner.
  - The one higher p95 (4 mixed: 139 → 169 ms) has a wide range across repeats (143-179 ms), and the other five p95s fell. It is within noise.
  - Unmatched reversals (a knockback or stun hid the reversal for over 1 s) were 0-2 per run, the same before and after.
- **Frame age** is server stamp to client receipt. It stayed at single-digit ms at p95, apart from the 6-moving baseline at 13.7 ms. The 6-player p95 fell, with fewer frames queued per socket.
- **Tick consistency.** The ticks seen were unchanged within noise. The p95 gap between new ticks fell or held.
- **Tick rate.** On Windows the 30 Hz tick ran at about 22-25 Hz in both runs, because the 33 ms asyncio sleep rounds up to the timer. That affects before and after alike.

## Not shown here

- **Pi, radio and phones:** nothing here measures them. Phone rendering and battery were not measured either.
- **Wire bytes:** payloads are decoded sizes, before WebSocket compression.
- **Linux:** no Linux re-run. The cloud measurement session used for AVR-138 was not available.
- **Other realtime games:** brickade, gridiron, smelterskelter, snake, tanks and others are unchanged. They are not opted in.
- **Remaining non-state traffic:** about 60 `bounce` events per second per client from resting balls ([AVR-675](https://linear.app/avranakern/issue/AVR-675)). That is now most of the messages, but small in bytes.
- **Procedure:** the Pi and real-phone procedure is still [performance-measurement](../runbooks/performance-measurement.md) §2, owner-run and not run.
