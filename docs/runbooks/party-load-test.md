# Plan: repeatable party load test for 4, 6 and 8 phones

Status: **design only (2026-09-24); not run.** Gated on power: run it only after a clean S0 power
stage (`docs/findings/2026-09-24-new-psu-power-baseline.md`), because a load test on a supply that
dips measures the supply, not the software. Complements ADR 0001 (the arcade stream harness).

## What it must answer

1. **How many phones can the party AP actually hold?** Since 2026-09-24 the party AP is the Pi's
   **internal** radio (`wlan0`, brcmfmac; the USB adapter was removed). It is widely reported to top
   out around 8 stations on the standard firmware (~19 on the "minimal" firmware) — unmeasured here.
2. **Does a native game stay correct and responsive** with 4, 6 and 8 phones (BLUFF max 6 seats +
   spectators; WORD RUSH up to 12)?
3. **Does power hold** under that radio and CPU load?
4. **Could we reconstruct a failure afterwards** from what was logged?

## Why browser tabs on one laptop are not enough

N Chromium clients on one laptop are **one Wi-Fi station**: they load the game server, but not the
AP's association table, airtime or per-station power save. So the test has two layers:

| Layer | Clients | Tests | Gate |
|---|---|---|---|
| **L1 server** (laptop harness, repeatable) | 4 / 6 / 8 / 12 Playwright clients on one laptop joined to the party AP | game server correctness and fan-out: every client sees the same public state; private state stays private; reconnect keeps seats | automated pass/fail |
| **L2 radio** (real devices) | 4 / 6 / 8 real phones (borrowed or old phones are fine; each must be its own station) | association, DHCP, roaming/sleep, airtime, power | a human-run checklist + logs |

L1 can run many times; L2 is expensive, so it runs once per hardware change.

## Metrics (per step, with Pi clock timestamps)

- **Power:** kernel dip count before/after (`journalctl -k -b | grep -icE 'undervoltage|voltage
  normalis'`), `pi-throttle-check.sh --interval 1` for the whole run, temperature.
- **Radio (every 5 s):** `iw dev wlan0 station dump` → stations, signal, `tx retries`, `tx failed`,
  `inactive time`, bitrate; `ip -s link show wlan0` errors/drops; kernel `brcmfmac` warnings (e.g. "firmware
  halted"). Redact MAC addresses before committing anything (phones randomise them anyway).
- **Server:** `/health` every 1 s (per-game phase, player count); process CPU and RSS; open sockets
  (`ss -tn state established '( sport = :8196 )' | wc -l`).
- **Game (L1):** action → broadcast latency measured in the harness (timestamp the click, wait for
  the state frame that reflects it); reconnect count and time per client; privacy check on every
  frame (no other player's hidden cards).
- **Human (L2):** join time per phone, phones that fell off Wi-Fi, seats lost, perceived lag (1–5).

## Steps

1. Baseline: Pi idle except the services under test; arcade state recorded (running or stopped —
   stopping it is the owner's call).
2. For N in 4, 6, 8 (L2 up to the number of phones available; L1 continues to 12):
   join all N; play one full BLUFF game (≤ 6 seated, the rest spectate), then one WORD RUSH round;
   each step 10 min; lock/unlock two phones mid-step; one phone walks to the edge of range and back.
3. Abort on: a live under-voltage bit, > 2 dips in a step, > 75 °C, a `wlan0` drop or AP restart, a Pi reboot,
   or any privacy violation.
4. Write a dated summary under `docs/findings/`. Keep raw logs in the Pi's
   runtime/test-data area, outside Git, and record their location in the summary.

## Instrumentation still missing (each needs the owner's OK before it runs on the Pi)

- **Session reconstruction:** today's dev-server log has no timestamps and no join/leave lines, and
  BLUFF's event log is in memory only (`docs/runbooks/bluff-playtest.md`). The runbook's
  timestamped log + `/health` poller is the no-code minimum; a **watch-only WebSocket logger**
  (`hello {watch:true}`, takes no seat) would record every public state frame and is the smallest
  addition that makes a failed party reconstructable.
- **An L1 harness for fork games** (the ADR 0001 harness drives the arcade only): Playwright clients
  that join the hub with distinct names, enter a game and act — reusing the BLUFF simulator's rules
  oracle where possible.
- **A radio sampler** script wrapping the `iw`/`ip` reads above into JSONL, like
  `pi-throttle-check.sh`.

## Open questions

The AP's configured station limit (check `iw list` / the driver's limits before buying phones);
whether 20 MHz on channel 149 is the right width for 8+ phones; whether the AP needs its power
save disabled under load (a live NetworkManager change — owner approval).
