# Avrana Party telemetry

Two small pieces, deliberately not a second monitoring stack:

1. **Beszel agent** on party, reporting to the existing hub on **avrana**
   (`http://10.0.0.218:8093`, hub v0.18.7). Beszel is the **main historical
   dashboard**: CPU, RAM, load, temperature, disk and network throughput over
   time.
2. **`pi-throttle-check.sh`** - a lightweight companion that records what Beszel
   cannot read on a Pi: the `vcgencmd` throttle/undervolt flags, CPU temp, ARM
   clock, V3D (GPU) clock and core voltage, as JSON lines.

## Why both

Beszel gives sustained trends and the shared dashboard. It polls on the order of
a minute, so it will **not** catch this Pi's brief under-voltage dips. The
authoritative count of transient dips is the kernel journal:

```bash
sudo journalctl -k -b | grep -icE 'undervoltage|voltage normalis'
```

`pi-throttle-check.sh` sits between the two: it logs the sticky "has occurred"
bits and clocks over time (60 s via timer, or 1 s during a test window) so a
PSU/cable change can be compared before vs after.

## Deploy (run on party, as root)

The Pi checkout tracks `origin/main`, so pull first, then install:

```bash
cd ~/avrana-party && git pull
sudo bash telemetry/install-beszel-agent.sh
sudo bash telemetry/install-pi-throttle-check.sh
```

Then in the hub UI (`http://10.0.0.218:8093`) → **Add System**:
name `party`, host `10.0.0.142`, port `45876`. (Since 2026-09-24 the Pi reaches the home LAN over
**eth0 = `10.0.0.142`**; the old `10.0.0.143` was the Wi-Fi address before the internal radio became the
party AP. Both are DHCP leases; a router reservation for eth0 is worth adding. **On 2026-09-24 the agent
had no connection from the hub** (it was set up with `10.0.0.143`; the hub's config was not read) —
check the `party` system's host in the hub UI and change it to `10.0.0.142`.)

Confirm in the dashboard that CPU, RAM, load, temperature, disk and network are
all graphing for `party`.

## Baseline snapshots

Capture three windows so later optimization is measured against a fixed
reference. Under-voltage is **currently unresolved**, so these are provisional
until the power fault is fixed - re-take them afterward.

Each window: 60 samples at 1 s. Also grab arcade `/stats` for windows 2-3.

```bash
# 1) Pi idle (arcade stopped)
sudo systemctl stop avranaparty-arcade
sudo /opt/avrana-telemetry/pi-throttle-check.sh --interval 1 --count 60 \
     --label idle --append /var/log/avrana/baseline.jsonl

# 2) Arcade running, no viewer
sudo systemctl start avranaparty-arcade   # wait ~20s to settle
curl -s http://party.local/arcade/stats
sudo /opt/avrana-telemetry/pi-throttle-check.sh --interval 1 --count 60 \
     --label arcade-idle --append /var/log/avrana/baseline.jsonl

# 3) Arcade + one iPhone streaming (join Avrana Party, open /arcade/, press Play)
curl -s http://party.local/arcade/stats
sudo /opt/avrana-telemetry/pi-throttle-check.sh --interval 1 --count 60 \
     --label arcade-1phone --append /var/log/avrana/baseline.jsonl
```

Dip count during each window (authoritative):

```bash
sudo journalctl -k --since "-2 min" | grep -icE 'undervoltage|voltage normalis'
```

### Results

Fill in from `/var/log/avrana/baseline.jsonl`, the Beszel `party` dashboard for
that window, and the dip counts. `throttled` is the raw `get_throttled` hex.

| Window | Date | temp C (med/max) | ARM MHz (min) | V3D MHz | core V (min) | throttled | live-throttle seen? | undervolt dips in window | CPU % (Beszel) | net Tx (Beszel) | arcade fps / kbps (/stats) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 idle | 2026-09-19 | 40.9 / 49.1 | 600 | 500 | 0.86 | 0x50000 | no | 0 (60 s window) | pending | pending | n/a |
| 2 arcade, no viewer |  |  |  |  |  |  |  |  |  |  |  |
| 3 arcade + 1 iPhone |  |  |  |  |  |  |  |  |  |  |  |

Idle notes: ARM 600 MHz min / core 0.86 V min are the **normal idle DVFS floor**,
not throttling (full 1800 MHz was available in the same window). `0x50000` is the
sticky "occurred since boot" flag; it cannot clear without a reboot. CPU %/net
are "pending" until party is added in the hub. **0 dips in 60 s is not proof of a
clean idle** - at the ~1 dip / 3-4 min seen under load, a 60 s window expects <1
dip regardless, so idle needs a longer window (see below).

Note the PSU/cable in use when these were taken:

## Isolating the recurring under-voltage

The cause is **not yet identified**. Treat these as independent hypotheses and
change **one variable at a time**, holding load and window length constant, using
the kernel dip count as the metric:

```bash
# dips per fixed window (run the same window length each time)
sudo journalctl -k --since "<window start>" | grep -icE 'undervoltage|voltage normalis'
```

- **Load** (CPU + USB/Wi-Fi TX): compare a long idle window vs. arcade-no-viewer
  vs. arcade + phone streaming. If dips scale with load, power delivery is
  marginal under draw. Use windows of **>=10 min each** so the ~1/3-4 min rate is
  visible (the 60 s baseline above is too short to conclude anything about rate).
- **PSU**: swap to a known-good official 5.1 V / 3 A supply, nothing else changed;
  re-measure the same window/load.
- **Cable**: swap the USB-C cable only (short, thick); re-measure.
- **USB load isolation**: the Realtek Wi-Fi 6 + BT adapter is a *hypothesis*, not
  the confirmed cause. Test it by comparing dip rate at Wi-Fi idle vs. under
  sustained TX, and (as a separate change) by powering the adapter from a powered
  hub so its draw is off the Pi's 5 V rail.

Record each run as a row: {change made, load, window length, dips, temp, min ARM,
min core V}. Only after a change drives dips to zero across a full arcade-load
window is the fault considered resolved.
