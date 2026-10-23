# Performance measurement (AVR-138)

Measure first, decide later. This runbook has two parts:
- **local**, which anyone can repeat on a laptop or in a Linux container;
- **appliance and phones**, owner-run and not yet done.

Laptop numbers never stand in for the Pi, the radio or a phone. Each result states its evidence type.

## 1. Local harness

```bash
python tools/perf/party_perf.py --games ../avrana-party-games --out perf-results
```

- **Opt-in and bounded.** Nothing runs it automatically, and every option has a hard range (repeats 1-10, windows ≤ 60 s, ≤ 16 clients).
- **Duration.** A default run takes 8-12 minutes. `--quick` is a smoke run, not a measurement.
- **Dependencies.** It needs `psutil` for the CPU, RSS and thread figures; without it those fields are null and say why. The two Games scenarios need an interpreter with the Games requirements.
- **Output.** `perf-<time>.json` (schema `avrana.perf-result/v1`) and a Markdown summary.
- **Recorded with every run:** environment (OS, CPUs, Python, Party and Games commits, and whether either checkout was dirty), configuration, sample sizes, every repeat, and failures.

| Scenario | What it measures | Real | Simulated |
|---|---|---|---|
| `idle` | Party Core CPU, RSS and threads with no members, then with 8 members long-polling; idle long-poll duration, requests and bytes per client (from completed idle polls) | Party Core process | phones: Python HTTP clients using the page's own wait (`party-client.js` `WAIT_S`) |
| `longpoll_{1,4,8}_clients` | host action POST latency; delay from the host's tap until every phone's long poll has the new state (p50, p95); Party Core and harness CPU; bytes per client per update | Party Core process | phones as above |
| `lifecycle_bluff_4_phones` | Start (Party Core's launch call to the already-running Games server, not a process start); ticket + WebSocket hello + first state; one phone's reconnect; End; everyone home; Party Core and Games memory and threads after each of 5 cycles, and growth after the first | Party Core + Games server processes, BLUFF | phones: Python WebSocket clients |
| `realtime_dodgeball_{2,4,6}_players[_mixed]` | messages, full state frames and decoded payload KB/s per client; state frames that repeat the last tick; ticks seen per second and the gap between new ticks at a client; frame age since the server stamped it (`now`, same-host wall clock); input to authority (a joystick reversal until a frame shows the player's own unit moving the new way); 1 Hz ping round trip through the WebSocket handler; Games server CPU and RSS; harness CPU. A repeat fails if the round is not in play at the end of the window | Games server, dodgeball's 30 Hz simulation | players: Python WebSocket clients. Plain: every player sends the joystick at dodgeball.js's moving rate (~11 Hz) and reverses every 0.6 s. `_mixed`: half the players rest the stick and send only the 4 Hz keepalive. All add the 1 Hz ping. **Standalone admission**, because dodgeball has no Party contract |

**Method.**
- Every repeat starts fresh processes.
- Timing uses `time.perf_counter` (monotonic, high resolution).
- Percentiles interpolate linearly, and every figure carries its n.
- The report gives the median across repeats, the range, and the coefficient of variation.

**Reading the results.**
- **Harness CPU.** "load generator CPU" is the harness's own CPU. All simulated phones share one Python process, so their timings include their own scheduling. Above 70% of a core the report marks the repeat as possibly client-bound.
- **Windows.** Use a Linux host for numbers you intend to keep. On Windows, timers and CPU accounting are coarse (about 15.6 ms), and short CPU windows read as 0. Dodgeball's 30 Hz tick runs at only 22-25 ticks per second on Windows: its 33 ms asyncio sleep rounds up to the timer (AVR-674 runs, `docs/findings/perf/2026-10-19-windows-avr674-*.json`). Compare tick-driven figures only between runs on the same host.
- **Failures.** A failed repeat keeps its error and the tail of the processes' output in the JSON.

Regression coverage for the harness itself is in `tests/unit/test_perf_harness.py`: statistics, bounds, the report, and a few-second smoke run against a real Party Core.

## 2. On the appliance and real phones (owner-run, NOT RUN)

Run these only when approved, outside a party, with the services the appliance normally runs. Nothing here changes configuration or installs anything. Each step writes to a dated directory outside Git.

**Prerequisites (each needs owner approval):**
- the power baseline is clean (no under-voltage during the run: `pi-throttle-check.sh --interval 1`);
- a laptop on the party Wi-Fi for the harness;
- the phones listed in `docs/runbooks/party-load-test.md` (L2).

**Steps:**
1. **Pi at rest.** For 10 minutes, sample `ps -o pid,rss,nlwp,pcpu -C python3` for Party Core and the Games server, plus `vcgencmd measure_temp`, every 5 s. Record `uname -a`, the Party and Games commits, and the arcade state.
2. **Party Core under phones.**
   - Run the harness from the laptop against the Pi's Party Core, over the radio and through nginx: `--only idle,longpoll`, pointed at the Pi. This needs a small `--party-url` addition, made and reviewed before the run.
   - Record the same Pi samples during the run.
   - This measures laptop → radio → nginx → Party Core. Its latency includes the radio. It is not a phone.
3. **Real phones, lightweight game.**
   - 4, then 6, then 8 phones join and play one BLUFF round.
   - Capture Pi CPU, RSS and threads; `iw dev wlan0 station dump` every 5 s (MACs redacted); and each phone's perceived lag (1–5).
   - Host action → phones' screens: film the host's tap and two phones at 240 fps, and count frames from the tap to each screen changing. That is the only phone-side propagation figure we can trust.
4. **Real phones, realtime game.** 2, 4 and 6 phones play dodgeball (standalone) or Tanks. Record Pi CPU for the Games process, per-station airtime (`iw ... station dump` `tx bytes`/`tx retries` deltas), and phone frame pacing where the browser exposes it.
5. **Repeat** each step 3 times. Report the median and range, and the phones' models and OS versions.

**Record:**
- results in `docs/findings/<date>-appliance-performance.md`, each figure labelled Pi, radio or phone;
- raw logs on the Pi's test-data area, outside Git.

Do not derive hardware requirements from section 1.
