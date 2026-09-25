# No-USB power baseline (2026-09-24, afternoon): the USB Wi-Fi adapter was the problem

Boot `0d18f4ca` (owner reboot 11:16 PDT) on the replacement PSU (cable unchanged as far as known),
**with the RTL8851BU USB Wi-Fi adapter removed**: the party AP now runs on the Pi's internal radio
(`wlan0`), eth0 is upstream (`docs/runbooks/network.md`). Raw evidence remains on the
historical `docs/party-platform` branch at
`docs/findings/evidence/2026-09-24-power-nousb/`; it is intentionally absent from `main`.

## Verdict

**Removing the USB Wi-Fi adapter eliminated the observed under-voltage under the tested
workloads.** Zero kernel under-voltage events and `get_throttled` = `0x0` for the whole boot
(3 h 26 min at the last check, 14:42), through an idle hour, light activity, deliberate SSH connections
(the trigger seen this morning), all-core CPU bursts and Wi-Fi transmit load. The same PSU with the
adapter attached logged 9 dips in ~91 minutes this morning (`2026-09-24-new-psu-power-baseline.md`).

This is not universal proof: see "Not tested" below.

## Runs (all sampled ON the Pi, 1 per second, read once at the end — no SSH polling)

| Run | Window (PDT) | Workload | Samples | Kernel dips | Flags seen | ARM min | Temp |
|---|---|---|---|---|---|---|---|
| A idle | 11:40:25 – 13:00:30 | appliance as usual (arcade stream process running, load 2.4–3.5), 2 phones associated, **no agent SSH** | 4,500 | **0** | `0x0` only | 1800 MHz | 46.2–49.6 °C |
| B light | 13:52:42 – 14:08:01 | every 20 s: nginx hub, Apple probe, LAN Games API, arcade page; every minute: a 20 MB fsync write + `find`, a 5 s single-core burst; **12 SSH sessions** opened in the window (10 scheduled from the laptop, 1 unplanned, 1 other) | 859 | **0** | `0x0` | 1800 MHz | 47.2–51.6 °C |
| C CPU | 14:08:01 – 14:23:04 | 10 × **all four cores** busy for 20 s, 70 s apart | 823 | **0** | `0x0` | 1800 MHz | 47.7 – peak **56.9 °C** |
| D radio | 14:23:04 – 14:33:05 | ~24,300 × 1,200-byte pings at 50/s to the one phone in the neighbour table (AP transmit ≈ 0.4 Mbit/s) | 563 | **0** | `0x0` | 1800 MHz | 47.2–50.1 °C |

Whole boot at the end: `0x0`, 0 kernel under-voltage lines, no reboot, `wlan0` up, 2 stations. Core
voltage read 0.926 V in every one of the 7,260 samples (this morning it dropped to 0.86 V during dips).

**Contrast with this morning (adapter attached, same PSU):** 9 dips in ~91 minutes, 7 of them within
2 s of an SSH session opening; each dip cut the ARM clock to 600 MHz. This afternoon, 12 SSH sessions in phase B and
23 over the whole boot produced none.

## How to read it

- **Thermal vs voltage:** the only temperature rise was phase C (≈ +8 °C to 56.9 °C, below the
  60 °C soft-temperature threshold and far below the 80 °C throttle point); `get_throttled` never showed the soft-temperature or throttle bits, so there was
  no thermal throttling either.
- **Kernel count is the authority** (`journalctl -k -b | grep -icE 'undervoltage|voltage normalis'`,
  2 lines = 1 dip): it stayed 0, and the per-second sampler never saw a live bit.

## Not tested (limits of this claim)

- **Realistic multi-phone Wi-Fi traffic.** In phase D the one phone in the neighbour table was
  asleep: it answered only 148 of the pings, so the AP transmitted but little came back. Several
  active phones streaming video are a different load.
- **PS1 emulation and the WebRTC stream with viewers** (the 09-23 brownout reset happened during PS1
  streaming). The PS1 power gate can now be reconsidered for a *supervised* emulation-only stage.
- Long duration (hours of play), cold boots (boot-time inrush), a battery pack, and the cable alone.

## What changes

- The **internal radio is the development AP** for now (`docs/runbooks/network.md`); the USB
  adapter stays out until it can be powered separately (a powered USB hub).
- ROADMAP: power is **no longer blocking** the BLUFF playtest (N2). The PS1/stream gate (N4) moves
  from "blocked" to "ready for a supervised emulation-only stage, owner go-ahead".
- Methodology that worked: sample on the Pi, read once at the end, no parallel agent work, and log
  deliberate triggers (SSH times, burst times) so they can be correlated.
