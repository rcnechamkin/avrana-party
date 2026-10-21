# Appliance preflight

Status: **implemented, NOT RUN on the Pi** (2026-10-21, AVR-696). Unit-tested with fake probes and run
against the dev server; the first appliance run is the owner's.

One command answers "is this appliance ready for tonight, and what is still unproven?". It runs the
checks that already exist (status, smoke, Pi health, topology check, install-game verify) and the
latest Wi-Fi gate result, and classifies every fact PASS, WARN, FAIL or UNKNOWN with a reason.

## Run it

From the laptop (the `party` SSH alias that `tools/wifi-lab` uses; no sudo, no password):

```bash
python tools/preflight.py --ssh party --horizon-days 3
```

On the Pi, in the operator's SSH session:

```bash
cd /opt/avrana-party/current && python3 -m avrana.ops.preflight --horizon-days 3
```

Until a deployment carries this tool, run it from the checkout (`--remote-dir /home/cody/avrana-party`
from the laptop, or `cd /home/cody/avrana-party` on the Pi) at a commit that has it.

| Option | Meaning |
|---|---|
| `--horizon-days N` | the served certificate must stay valid N more days (a trip; renewal needs the Internet) |
| `--wifi-gate PATH` | a `tools/wifi-lab` `gate.json`, its results directory, or `-` (the laptop wrapper streams the newest one) |
| `--wifi-max-age-h H` | gate results older than this are UNKNOWN (default 24) |
| `--waive ID` | accept one blocking UNKNOWN for this run, e.g. `--waive wifi.gate`; recorded in the report; a FAIL is never waivable |
| `--json`, `--out DIR` | the `avrana.preflight/v0` document; `--out` also writes `preflight-<stamp>.json` and `.md` |
| `--local URL` | against the dev server; appliance-only checks are UNKNOWN |

Exit code: **0 READY**, **1 NOT_READY** (a blocking FAIL), **3 UNKNOWN** (a blocking fact could not be
observed), 2 usage. `tools/release_candidate.py prereq` (AVR-699) refuses to clear an installation unless
the preflight said READY.

## What it checks

| Category | Source | Blocking |
|---|---|---|
| revision | `/party/api/status` on loopback (deployed Party/Games SHAs, checkout drift, web build, nginx site, contract) | yes; last-known-good missing is advisory |
| services | the same document (systemd state, crash loops, start limit) | yes; a live session is advisory |
| serving | `avrana.ops.smoke` (captive probe, Party Home over HTTPS, Party Core, Games provider, arcade) | yes; the encoder is advisory |
| tls | the certificate served on 127.0.0.1:443 for every Party Core `hosts` name and game origin, verified like a phone would | yes |
| network | Party DNS answers for each name (dig, else a built-in query), `tools/avrana-topology-check`, the wifi-lab gate | yes |
| pi | `telemetry/pi-health-check.py` (its timer's state file when under 30 min old, else one bounded run), clock, storage | health and storage yes; clock behind the last deploy is a FAIL; reboot pending and volatile journal are advisory |
| packages | `install-game list/verify`, `node_runtime verify` | yes |
| runtime | Python 3.11+, systemctl, openssl, nginx, git, nft, nmcli, iw | yes |

**The clock.** Certificate runway and the gate's age are computed from the Pi's clock. An offline Pi
can be days off. It is trusted when:
- NTP is synchronized; or
- it is within 120 s of the laptop's clock, which `tools/preflight.py` sends as `--reference-time`.

Otherwise `pi.clock` is UNKNOWN. Run it from the laptop, or check `date` and `--waive pi.clock`. More
than 120 s off from the laptop, or earlier than the last deployment, is a FAIL.

**The topology check** asserts the home development layout. Away from home there is no upstream on
`eth0`, which is expected: those lines become notes, never a FAIL. A topology run that stops part-way
is UNKNOWN. Its INFO lines (home-LAN addresses) are not saved.

**Other rules.**
- The gate's channel must match the AP's channel, and both must be readable. If either side is
  unknown, `wifi.gate` is UNKNOWN.
- A status document without the core units is UNKNOWN.
- A check that crashes becomes `<category>.crashed` UNKNOWN.
- `--local` can never be waived to READY.
- Loopback requests ignore `http_proxy`.

Storage thresholds are provisional (`STORAGE` in `avrana/ops/preflight.py`): FAIL under 512 MiB or 5 %
free on `/`, WARN under 2 GiB or 10 %.

## Reading the result

- **NOT_READY**: fix every FAIL listed under "Blocking" before guests arrive, with the runbook its reason
  names. Do not change the access point, DNS or certificates in the middle of a party.
- **UNKNOWN**: something could not be seen. The most common is `wifi.gate`: run
  `python tools/wifi-lab/wifilab.py gate` (2-3 minutes, [wifi-qualification](wifi-qualification.md)) and run
  the preflight again. A gate taken on another channel or more than 24 h ago is UNKNOWN, not its old verdict.
- **READY**: the server side is fit. It is **not** a phone test: the "Needs a real phone" list is printed
  every time and stays the owner's (the field-test gate on PR #174, steps 5-6;
  [friend-ready owner checklist](friend-ready-owner-checklist.md)).

## Boundaries

- No Internet: it contacts only loopback and the Party AP address (a unit test intercepts every
  connection a full run makes and asserts this).
- No new endpoint and no secret: it runs in the operator's SSH session and reads the public status
  document; it never reads keys, tokens, cookies or logs, and never uses sudo.
- It changes nothing: no restart, install, channel change or recovery action.
- It does not measure Wi-Fi; it consumes the AVR-296 gate result.
- Examples: [simulated READY](../findings/preflight/2026-10-21-simulated-ready.txt),
  [simulated field day](../findings/preflight/2026-10-21-simulated-field-day.txt) (fake probes, not the Pi),
  [dev server run](../findings/preflight/2026-10-21-devserver-local.txt).
