# Avrana Wi-Fi lab

Client-side qualification of the Pi access point: **Android client → Wi-Fi → Pi `wlan0`**, USB used only for
adb control. The harness refuses to run unless the client's route to the AP leaves via a Wi-Fi interface on the
Avrana subnet and no other interface (USB tethering) holds an IPv4 address. Standard-library Python only; nothing
here touches Avrana application code. Raw results stay local (`results/` is gitignored: MACs, IPs, device names).

The procedures, thresholds, health-state table, ranking formula, install gates and the plan for real Party workloads are in
[docs/runbooks/wifi-qualification.md](../../docs/runbooks/wifi-qualification.md); the evidence that motivated them is in
[docs/findings/2026-10-06-wifi-channel-36-vs-149.md](../../docs/findings/2026-10-06-wifi-channel-36-vs-149.md).

## Commands (run from the repository root)

```
python tools/wifi-lab/wifilab.py health                          # Pi hardware health (bounded, never hangs)
python tools/wifi-lab/wifilab.py gate                            # ~2-3 min pre-event PASS / WARN / FAIL
python tools/wifi-lab/wifilab.py baseline --label X --trials 3   # idle latency (alias: idle)
python tools/wifi-lab/wifilab.py loaded --label X --seconds 30   # latency under load (alias: load)
python tools/wifi-lab/wifilab.py qualify --lab                   # channel matrix + ranking (lab only)
python tools/wifi-lab/wifilab.py multi --counts 1,2,4            # multi-client steps (real + labelled synthetic)
python tools/wifi-lab/wifilab.py report --write                  # tables / results/REPORT.md
python tools/wifi-lab/wifilab.py --device SERIAL gate            # a specific Android device
python tools/wifi-lab/wifilab.py --all-devices gate              # every attached device, results kept per client
python tools/wifi-lab/wifilab.py ap show                         # AP state through the restricted helper
python tools/wifi-lab/wifilab.py ap-recover                      # after an interrupted qualification
python -m unittest tests/unit/test_wifi_lab.py                   # offline tests
```

Prerequisites: `adb` on PATH or in a folder listed in `config.json` (`adb_search`); an authorised device joined to the
Avrana SSID; the `party` ssh alias (key auth, no password). `ap set|restore`, `qualify` and boot-time channel changes
need the restricted helper installed by the owner (`ops/ap-control/`, AVR-298); without it they stop with the exact
install command. Defaults and the provisional gate thresholds are in `config.json` (override with `--set key=value`,
e.g. `--set expect_channel=36` makes a trial refuse to run unless the AP is on that channel).

## What a trial records (`results/<stamp>_<label>_<kind>_<device>/`)

`summary.json` / `summary.txt`, `ping.raw.txt`, `ping.csv`, `health.json` (Pi state before/after with evidence),
`pi-before/after.txt`, `tablet-before/after.txt`. Metrics: sent/received/loss, min/avg/p50/p95/p99/max, stdev,
mean |ΔRTT|, spikes, longest loss burst, AP band/channel/width/regdom, client RSSI, link rates, client TX retry
counters, Pi `tx failed`, Pi health state/temperature/load/throttle. A `gate` writes `gate.json` + `gate.txt`
(verdict, reasons, thresholds), `qualify` writes `qualify.json` + `qualify.txt` (ranking), `multi` writes `multi.json`.

## Limits (do not hide them)

- **Channel utilisation is unavailable** (`iw survey dump` is empty for brcmfmac in AP mode); the Pi exposes only
  `tx failed`. Retry ratios come from the Android client's counters: tablet-to-AP direction only, cumulative and noisy.
- **The load generator is not iperf3** (32-bit armv7 Android 11, no first-party build, no unverified binary staged):
  paced UDP from the Pi, max-effort TCP via `nc`. Throughput is the client's own `/proc/net/dev` delta. Compare runs
  with each other, not with iperf3 figures.
- Ping at 200 ms is the non-root Android minimum and lets the radio doze between packets, which adds up to one
  beacon interval to idle p95/p99.
- Gate thresholds and the ranking score are **provisional heuristics** from one tablet and one Pi.
- Synthetic multi-client traffic from this machine is not evidence about Wi-Fi clients unless its path is the Avrana subnet.
- The Pi health check cannot observe a wedged firmware directly; it infers it from a `vcgencmd` that does not answer
  or is stuck in D state, plus kernel messages. It does not reboot or restart anything and neither does this tool.
