# Wi-Fi qualification, Pi health and restricted AP control (AVR-296)

Status: **tooling implemented in the repository; the Pi-side pieces (health timer, AP-control helper) are
prepared and NOT installed** (owner steps below, tracked as AVR-297 and AVR-298). Evidence behind it:
[2026-10-06 finding](../findings/2026-10-06-wifi-channel-36-vs-149.md). Channel policy:
[network runbook](network.md#channel-policy-measured-2026-10-06-read-before-changing-the-channel).

Everything here is laptop-side except two optional Pi installs. The harness lives in
[`tools/wifi-lab/`](../../tools/wifi-lab/README.md) and needs `adb`, an authorised Android client joined to
the Avrana SSID, and the `party` ssh alias.

## Commands

| Purpose | Command |
|---|---|
| Pi hardware health | `python tools/wifi-lab/wifilab.py health` |
| **Pre-event gate** (about 2-3 min) | `python tools/wifi-lab/wifilab.py gate` |
| Normal idle baseline (3 trials) | `python tools/wifi-lab/wifilab.py baseline --label X --trials 3` |
| Loaded latency | `python tools/wifi-lab/wifilab.py loaded --label X --seconds 30` |
| Channel qualification (lab only) | `python tools/wifi-lab/wifilab.py qualify --lab` |
| Multi-client steps | `python tools/wifi-lab/wifilab.py multi --counts 1,2,4` |
| Tables / Markdown report | `python tools/wifi-lab/wifilab.py report --write` |
| One specific Android device | `python tools/wifi-lab/wifilab.py --device SERIAL gate` |
| Every attached device, separate results | `python tools/wifi-lab/wifilab.py --all-devices gate` |
| Recover after an interrupted qualification | `python tools/wifi-lab/wifilab.py ap-recover` |

`gate` exits 0 PASS, 1 WARN, 2 FAIL. Run `baseline`/`loaded`/`gate` only when nobody is playing: they
generate load. `qualify` additionally disconnects every client at each step.

## Pi health states (`telemetry/pi-health-check.py`)

One bounded check (every command has a time limit; a stuck process is abandoned, never waited on; it never starts
another `vcgencmd` while one is already stuck). It observes only: no restart, no reboot. Highest row wins.

| State | Caused by (observations) |
|---|---|
| `FIRMWARE_MAILBOX_SUSPECT` | `vcgencmd get_throttled` did not answer within 5 s, **or** one or more `vcgencmd` processes are in uninterruptible sleep (D state). Kernel mailbox lines (`Firmware transaction ... timeout`, `Failed to get throttled`, `vchi message timeout`, `raspberrypi-clk ... Failed to set clock`) are added as supporting reasons |
| `POWER_THROTTLE_DETECTED` | `get_throttled` shows under-voltage (0x1), ARM frequency cap (0x2), throttling (0x4) or soft temperature limit (0x8) **right now** |
| `UNKNOWN` | the throttle state could not be read for a reason other than a hang (missing `vcgencmd`, non-zero exit, unparsable output) |
| `DEGRADED` | none of the above, but at least one of: sticky "has occurred since boot" bits (0x10000-0x80000); kernel under-voltage lines this boot; mailbox error lines earlier this boot while `vcgencmd` answers now (intermittent or recovered); brcmfmac warning lines (known-benign `txcap_blob` and `vndr ie set error` ignored); CPU temperature >= 75 C; processes in D state that are not `vcgencmd` (I/O, not attributed to the mailbox); load > 2 x cores (stated as CPU-bound unless D-state processes exist); < 10 % memory available; unreadable kernel log |
| `HEALTHY` | everything observable is normal |

High load alone is **not** the mailbox failure: it never produces `FIRMWARE_MAILBOX_SUSPECT`. The state is
`avrana.pi-health/v0` JSON with the evidence; thresholds are constants at the top of the script.

**Persistent watchdog (prepared, not installed): AVR-297.** Owner step on the Pi after merge and pull:
`sudo bash telemetry/install-pi-health-check.sh`. It installs `pi-health-check.service`/`.timer` (every 60 s,
unprivileged `DynamicUser` with groups `video adm`), logs one line per run to journald
(`journalctl -u pi-health-check`) and writes `/run/avrana/pi-health.json`. It **never reboots or restarts
anything**; any automatic recovery needs an explicit owner decision. A Host-UI notice such as "Network hardware
health degraded. Restart recommended." is a later change that would read that file; Beszel cannot ingest custom
states, so it stays the CPU/RAM/temperature dashboard. The existing `pi-throttle-check.sh` sampler is now bounded
too (5 s limit, skips while a `vcgencmd` is stuck) so it cannot stack D-state processes.

## Pre-event gate

Steps: Pi health, client route verification, 150 idle pings (30 s), 100 pings under 20 Mbps downlink, thresholds,
Pi health again. Thresholds live in `tools/wifi-lab/config.json` under `gate` and are **provisional**, derived from
the healthy channel-36 runs of 2026-10-06 (one tablet, one Pi). Any metric that cannot be obtained produces WARN or
FAIL, never a silent pass.

| Metric | WARN above | FAIL above |
|---|---|---|
| idle p95 / p99 RTT | 80 / 150 ms | 200 / 300 ms |
| idle packet loss | 0.5 % | 2 % |
| idle client TX retries per success | 3 | 10 |
| loaded p95 / p99 RTT | 250 / 400 ms | 600 / 1000 ms |
| loaded packet loss | 1 % | 3 % |
| loaded client TX retries per success | 10 | 30 |
| loaded delivered / offered (20 Mbps) | below 0.8 | below 0.5 |
| Pi health | DEGRADED | SUSPECT, POWER, UNKNOWN or not collectable |

**Retry ratio is corroborating evidence, not a stand-alone FAIL.** On a clean channel-36 gate run (2026-10-07) the
client counter read 129 retries per success (about 140 retries/s against 8 successes/s) while latency, loss and
delivered throughput were all perfect, so the counter is noisy. A retry-ratio breach is a FAIL only when another metric
of the same phase (latency, loss, delivery) is also degraded; otherwise it is reported as a WARN that says so.

Retry ratios come from the Android client's counters (`cmd wifi status`); the Pi's brcmfmac exposes only
`tx failed` in AP mode and no channel-utilisation data, so neither is used as a verdict input.

## Channel qualification and ranking

`qualify --lab` takes the configured candidates (36, 40, 44, 48, 149, 153, 157, 161), keeps those the Pi's
regulatory domain permits on this radio (enabled, no radar detection, no "no IR"), and for each: switches the AP
through the helper, waits for the client (recovering one that roamed to another saved network by toggling its
Wi-Fi; saved networks are never edited), verifies the route and the channel, then runs idle (150 pings), downlink
20 Mbps (100 pings) and uplink max-effort (60 pings). The AP always returns to `default_channel` (36) in a
`finally`; an interruption leaves `results/.ap-dirty.json` and `ap-recover` finishes the job.

Ranking: gate verdict first (PASS, WARN, FAIL, then errors), then this score, highest first:

```
score = 100 - 25*min(1, idle_p99/300) - 25*min(1, loaded_p99/1000) - 15*min(1, max_loss/3)
            - 15*min(1, idle_retry/10) - 10*min(1, loaded_retry/30) - 10*(1 - min(1, uplink_mbps/20))
```

A missing metric takes its full penalty and is listed. This is a heuristic for ordering candidates for one client
at one place; it is not a universal quality measure and the weights are judgement. The number of neighbouring
networks is recorded as information only and never scored (empty-looking channel 149 was bad on 2026-10-06).

## Restricted AP control (prepared, not installed): AVR-298

The SSH user cannot change NetworkManager (polkit) and must not get broad sudo. `ops/ap-control/` provides a
root-owned helper and a sudoers rule that allows exactly these argument vectors and nothing else:

```
avrana-ap-control show
avrana-ap-control restore
avrana-ap-control set-channel <36|40|44|48|149|153|157|161> [--lab]
```

The helper takes no free-form input, runs no shell, uses absolute binary paths and a cleared environment, touches
only the profile "Avrana Party Internal", checks the regulatory domain, saves the original band/channel on the
first change, logs every call to the journal, and refuses a change while a Party session is active (and, without
`--lab`, while any station is associated or when it cannot confirm that no session is active). `--lab` means "the
associated station is my own test device".

Owner install (validates the sudoers file with `visudo` first):

```bash
bash ops/ap-control/install-ap-control.sh --print-sudoers cody      # review what would be granted; changes nothing
sudo bash ops/ap-control/install-ap-control.sh --user cody          # install (on the Pi)
sudo bash ops/ap-control/install-ap-control.sh --remove             # uninstall
```

Validation to run after install (AVR-298): `ssh party sudo -n /usr/local/sbin/avrana-ap-control show` works;
`set-channel 13`, `set-channel 52`, `set-channel '36;id'` and any other `sudo -n` command are refused.

## Adding a second Android device (AVR-300)

1. Enable Developer options and USB debugging on the device, plug it in, accept the RSA prompt ("Always allow").
2. `adb devices -l` must show it as `device`; note the serial.
3. Join the device to the Avrana Wi-Fi (the harness refuses a device whose route is not a Wi-Fi interface on the
   Avrana subnet, or that also holds another interface such as USB tethering).
4. With two devices attached the tool refuses to guess: pass `--device SERIAL` or `--all-devices`. Results go to
   separate directories named with the device's last four serial characters, with the model and MAC in each summary.
5. A/B for AVR-300: on channel 36 then 149, `wifilab.py --device <serial> gate` for each device; fill the matrix
   tablet-on-36, tablet-on-149, second-on-36, second-on-149. **No mechanism is claimed until the matrix exists.**

## Multi-client load (`multi`)

Avrana is latency-, jitter- and reconnect-sensitive, so this is **not** a throughput test. Real devices ping the AP
over their own Wi-Fi; synthetic clients are TCP echo clients (20 Hz, 64 B) run on the development machine and are
always labelled by path: `avrana-subnet` (this machine is itself a client of the AP) or `other-path` (it does **not**
exercise the radio, only the Pi's CPU/RAM and the application side). Capacity claims come from real-device steps only.
Per client: RTT p50/p95/p99, loss, reconnects, and for real devices RSSI and retry ratio; per step: Pi health,
temperature, load and memory. Planned counts: 1, 2, 4, 6, 8, 10 (AVR-301; related AVR-12).

## Real Party workload instrumentation (design; AVR-302)

What exists today (read from source, 2026-10-07): Party's heartbeat is the HTTP long-poll
`GET /party/api/state?since=V&wait=25` (`web/party/lib/party-client.js`); each poll or `POST /party/api/heartbeat`
calls `Core.touch` and a member counts as `here` for 45 s (`LIVE_WINDOW`); game pages use a WebSocket (`{"t":"hello",
"ticket":...}` first, a `{"t":"ping"}` verb in Games `core/net.py`, transport keepalive pings in `core/ws_limit.py`).
Nothing records heartbeat gaps, long-poll turnaround or reconnect counts.

A future Gauntlet workload module would plug into `wifilab.run_trial`'s `traffic` seam (`start()` / `stop(handle)`)
and must correlate four streams by wall-clock timestamp: (1) Android/network (ping CSV, link counters), (2) Pi
radio/health (`pi_health`, snapshots; add a background sampler in `start()`), (3) Party/WebSocket (needs the AVR-302
counters or client-side timing: poll turnaround, WebSocket ping RTT, reconnect count, missed 45 s windows) and
(4) game events (join, round start, input bursts) written to `meta["events"]` with timestamps. Chrome is driven with
`adb shell am start -a android.intent.action.VIEW -d https://party.avrana.net/` and `input tap/text` or uiautomator.
**No browser or game metric is claimed until it is observed.** No Party code is changed by AVR-296; the proposed
server-side counters (behind a diagnostics flag, separate from `/party/api/status`) are an owner decision in AVR-302.

## What is automated and what stays manual

Automated: health classification, the gate verdict, channel matrix with guaranteed restore, per-device results,
reports. Manual (owner): installing the health timer (AVR-297) and the AP helper (AVR-298), plugging in a second
device (AVR-300), running anything on real phones, and every decision about automatic recovery or boot-time channel
selection (AVR-299). Changing channels remains forbidden during play.
