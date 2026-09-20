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
name `party`, host `10.0.0.143`, port `45876`. (party's `10.0.0.143` is a DHCP
lease; a router reservation for it is worth adding so the hub keeps finding it.)

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
| 1 idle |  |  |  |  |  |  |  |  |  |  | n/a |
| 2 arcade, no viewer |  |  |  |  |  |  |  |  |  |  |  |
| 3 arcade + 1 iPhone |  |  |  |  |  |  |  |  |  |  |  |

Note the PSU/cable in use when these were taken:
