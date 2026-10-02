# New PSU power baseline (2026-09-24): fewer dips, not zero — power is NOT cleared

Boot `b90bd6d2`, booted 08:21:33 PDT on the owner's replacement "known-good" PSU (cable **not**
known to have changed), with the RTL8851BU USB Wi-Fi adapter carrying the party AP plugged in.
Raw evidence remains on the historical `docs/party-platform` branch under
`docs/findings/evidence/2026-09-24-power/` (per-second `pi-throttle-check.sh` JSONL
and per-minute context logs). It is intentionally absent from production `main`.

**Verdict: FAIL.** The success bar was `0x0`, zero new under-voltage events, a stable USB Wi-Fi
adapter, no resets and reasonable thermals. Everything held **except** the first: the kernel
logged **8 under-voltage dips** in the first 1 h 27 min of this boot (≈ 5.5/h), and a 9th at 09:52
(~91 min after boot; see the addendum). The PS1/stream gate stays closed; the recurring
under-voltage stays open (`docs/archive/handoffs/2026-09-25-claude-log.md`).

## How to read the counters

- `vcgencmd get_throttled` bits 16–19 are **sticky** (since boot): `0x50000` = under-voltage and
  throttling *have occurred*. Bits 0–3 are **live**: `0x50005` = under-voltage *now* + throttled
  *now*. A sticky flag is not a new event.
- The authoritative event count is the kernel's hwmon log (no sudo needed):
  `journalctl -k -b | grep -icE 'undervoltage|voltage normalis'` — **2 lines = 1 dip**.
- A 1 s poller catches only part of a dip; the minute sampler undercounted ~15× on 09-19
  (Kevin's analysis). Count dips from the kernel, not from samples.

## Runs

| Run | Window (PDT) | Conditions | Kernel dips | Live-bit samples | Temp | Notes |
|---|---|---|---|---|---|---|
| A `newpsu-adapter` | 08:25:08–08:46:29 (1,200 samples) | adapter in; iPhone associated from ~08:40; arcade stream process running (Gauntlet II, load 2.5–3.9); agents mostly idle | **0** | 0 | 44.3–48.7 °C | all `0x0`, ARM 1800 MHz, core 0.926 V; no boot-time dip (both old-PSU boots with the adapter dipped at +15–20 s) |
| (between runs) | 08:45–09:00 | **parallel agent audits** over SSH: ~7–19 logins/min, a 391-test BLUFF pytest (~94 % CPU), ~50 `dig`s, `avahi-browse`, `iwconfig` | **2** (08:53:56, 08:55:13) | — | — | sticky flag became `0x50000` |
| B `newpsu-quiet` (S0) | 09:00:16–09:48:24 (2,700 samples) | adapter in; one idle iPhone associated; arcade process running; **no agent work on the Pi** except one light status SSH every ~30 s (see below) | **5** (09:01:30, 09:01:50, 09:02:16, 09:42:22, 09:44:06) | 14, in 5 episodes of 2–3 s | 44.8–49.6 °C | every episode read `0x50005` with **ARM cut to 600 MHz and core at 0.86 V**; 40 min clean between 09:02:22 and 09:42:22 |
| (after run B) | 09:48:47 | an evidence copy (`scp`) + status SSH | **1** | — | 46.2 °C | |

Other facts from the same boot ("Kevin" = the power/hardware review agent of this session,
read-only): no USB disconnects after the adapter's normal
mode-switch at +12 s; no mmc/ext4 errors (Samsung 119 GiB card, 0 ext4 errors); no failed units;
ARM held 1800 MHz throughout; only `cpu-thermal` exists (no fan) with ~30 °C of headroom to the
80 °C throttle point; `rtw89` logged two "timed out to flush queues" warnings when the phone
associated (the only driver warnings).

## Dips follow SSH session starts

The Pi's journal shows 87 SSH sessions opened between 09:00:16 and 09:49 (the session agent's ~30 s status
polls and evidence copies). **Six of the eight dips this boot began within −0.4 … +1.6 s of an SSH
session opening** (`kernel-dips.txt` vs `ssh-session-opens.txt` in the evidence folder): 08:53:56
(+1.0 s), 08:55:13 (+1.5), 09:01:30 (−0.4: during the handshake, before authentication was
logged), 09:42:22 (+1.6), 09:44:06 (+1.4), 09:48:47 (+0.7). The two others (09:01:50, 09:02:16)
were 8–14 s from any session. From 09:00 on, the "−1 … +2.5 s around a session start" window covers
~10 % of the time, so 4 of 6 dips landing in it by chance has a probability of ≈ 0.14 %. A session
start is a short CPU burst (TCP + key exchange, a forked shell and command) on top of the arcade's
steady load (2.4–3.9); most sessions did **not** trigger a dip — the Pi runs close to the margin and
a burst sometimes tips it. (Run A had 63 SSH sessions in 21 min and **no** dip, so the margin
itself varies — with radio activity, the arcade's load, or something not logged here.) Consequences:

- It supports the "short bursts" hypothesis (the audit-time dips also came during bursts of SSH and
  a pytest run) and makes a CPU-burst test (S1) the most informative next software-side check.
- **Remote polling perturbs the measurement.** Future power runs log on the Pi and are read once at
  the end — no SSH polling during the window.

**Addendum (09:52):** a 9th dip at 09:52:29, **+0.75 s** after an SSH session that ran the PS1 unit
tests (~5 s of Python on the Pi; no emulator). That makes 7 of 9 dips this boot within 2 s of an SSH
session start. `kernel-dips.txt` and `ssh-session-opens.txt` include it.

## History for context (`/var/log/avrana/pi-throttle.jsonl`, minute samples; kernel counts where known)

| Setup | Hours | Result |
|---|---|---|
| Old PSU + adapter (09-19 … 09-23, 5 boots) | ~93 | live under-voltage in the minute telemetry on every boot (kernel ≈ 14–18/h on 09-19: 23 dips in ~100 min, and 6 in a 20-min window); one brownout **reset** during PS1 streaming on 09-23 |
| Old PSU, **adapter unplugged** (from 09-23 19:08; 2 boots to ~08:05 on 09-24) | ~13 | **0** in the minute telemetry; kernel count 0 where checked (~5 h) |
| **New PSU + adapter** (this boot) | 1.45 | **8 dips** (≈ 5.5/h), in bursts: 08:53–09:02 and 09:42–09:48 |

## What this does and does not show

- **Shows:** the new PSU is an improvement — no boot-time dip, and the dip rate fell from ≈ 14–18/h to
  ≈ 5.5/h over this boot — but it does **not** eliminate under-voltage with the adapter attached.
- **Suggests (not proven):** the adapter's current draw is the dominant factor. With no adapter the
  old PSU was clean for ~13 h; with it, both PSUs dip. Dips cluster in bursts rather than tracking load average, which never left
  the clean run's range; the SSH correlation above points at **short CPU bursts on top of the
  arcade's steady load** as the trigger, with the adapter's draw leaving too little margin.
- **Does not show:** anything about the cable (not known to have changed); anything under real party load (several
  phones, streaming, PS1) — all untested on the new PSU.

## Next isolation steps (one variable each, ≥ 20 min, kernel count before/after)

1. **Adapter on a powered USB hub** (or a USB-C PD splitter feeding the hub): if dips stop, the Pi's
   5 V rail can't carry the adapter's peaks. Cheapest discriminating test; no software change.
2. **Short, thick USB-C cable** (≤ 1 m, 20 AWG power pair), then 3 cold boots watching +15–20 s.
3. **New PSU, adapter unplugged**, 60 min: confirms the new PSU alone is clean.
4. Only after a clean quiet baseline ("S0": one idle phone, no agent activity, 60 min): S1 CPU
   bursts (10 × BLUFF pytest, 60 s apart), S2 radio load (3–5 phones + `iperf3 -b 20M` through the
   AP), then S3 supervised PS1 (owner go-ahead).

Stop a stage at the first live bit, > 2 dips, > 75 °C, a wlan1/USB drop or any reboot. **No
parallel agent work and no SSH polling on the Pi during a power measurement** — run A's clean 20 minutes were
followed by two dips during the audit burst.
