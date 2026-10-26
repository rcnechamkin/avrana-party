# Avrana Health and the support bundle (AVR-74)

- **Status:** proposal, 2026-10-26. Nothing is implemented. **Owner decisions required** (section 7).
- **There is no owner page yet.** No owner route or Admin PIN session exists in code today (`PARTY-PLATFORM.md` requires one). Until one does, every surface below is reachable only over SSH.
- **Reads with:**
  - [STATUS-ENDPOINT.md](../STATUS-ENDPOINT.md) and `avrana/ops/status.py` (`avrana.status/v0`, public, counts only);
  - `avrana/ops/preflight.py` (`avrana.preflight/v0`) and Party Ready (AVR-86, draft #232);
  - [field-session runbook](../../runbooks/field-session.md), `avrana/ops/fieldsession.py` and `avrana/ops/redact.py`;
  - `telemetry/pi-health-check.py` (`/run/avrana/pi-health.json`) and `telemetry/pi-throttle-check.sh`;
  - physical signals (AVR-87, draft #240), the activity model (AVR-84, draft #241) and owner onboarding (AVR-44).

## 1. Most of the parts exist; what is missing is one model and one export

| AVR-74 asks for | What already exists | Gap |
|---|---|---|
| core service health, boot and restart state | `status.py`: unit states, systemd's own recovery (AVR-33), failed game units | none in the facts |
| storage, temperature, power, throttling | preflight `storage.*`, `pi.health`, `pi.clock`, `pi.reboot_required`; `pi-health-check.py`; the throttle log | not in one owner-readable place |
| Party WLAN and local DNS | preflight `network.topology`, `wifi.gate` (the latest wifi-lab result) and `serving.*` (`smoke.py`) | runs only when someone runs the preflight |
| certificate validity and renewal | `status.py` certificate runway; AVR-31 (draft #224) degrades on a failed renewal | none |
| installed games and providers | `status.py` provider checks; preflight `packages` (`install_game verify`) | none |
| update state | the deployment manifest, last known good, the deploy lock | no "update ready / pending reboot" line for the owner |
| recent bounded errors | the field session's journal excerpt (Avrana units, redacted, capped) | only inside a recorded test night |
| safe diagnostics export | the field package: bounded, deterministic, validated, redacted (`avrana.redaction/v3` in draft #234) | needs a `start` before the problem happens |
| healthy / degraded / action required | status: `ok`/`degraded`/`unknown`; preflight: `PASS`/`WARN`/`FAIL`/`UNKNOWN` and `READY`/`NOT_READY`/`UNKNOWN` | two vocabularies, neither in the owner's words |

So the proposal is small:
- **one derived health document** that reads the facts above and re-implements none of them;
- **one on-demand support bundle** that reuses the field-package writer and validator.

## 2. The health model: `avrana.health/v0`

```json
{"schema": "avrana.health/v0", "at": "…", "state": "action_required",
 "items": [
   {"id": "storage", "state": "action_required", "words": "Storage is almost full (3% free). Games may fail to update.",
    "action": {"kind": "runbook", "ref": "a storage runbook (none exists yet)"}, "source": "preflight:storage./"},
   {"id": "certificate", "state": "healthy", "words": "Secure connection good for 61 more days.", "source": "status:certificate"},
   {"id": "wifi", "state": "unknown", "words": "Wi-Fi was not checked today.", "source": "preflight:wifi.gate"}
 ],
 "ready": {"verdict": "NOT_READY", "horizon_days": 10}}
```

**Four states:** `healthy`, `degraded`, `action_required` and `unknown`.

| From | healthy | degraded | action_required | unknown |
|---|---|---|---|---|
| status `summary` and reasons | `ok` | `degraded`, a reason that does not stop a party (a restart after failures, an nginx drift, a dirty checkout) | `degraded`, a reason that stops a party (Party Core failed, a unit hit its start limit, a certificate expired, a failed game unit in the live session) | `unknown` |
| a preflight check | PASS | WARN, or a non-blocking FAIL | a blocking FAIL | UNKNOWN |
| `pi-health.json` | `ok` | a warning (under-voltage seen, a Wi-Fi driver error) | the firmware mailbox wedged (the 2026-10-06 failure) | stale or missing |

- **The overall state is the worst item.** `unknown` never rolls up as `healthy`, which is the same rule as AVR-31 and the preflight.
- **`words` are Party Ready's** (draft #232): one plain sentence, with no unit names.
- **`source` keeps the engineering id**, so support can trace any line to its check.
- **Every `action_required` item names an action:** a runbook today, and a button later, when the owner page can act (restart a service, retry a renewal).
- **`ready`** is the AVR-86 verdict, carried along when a preflight result is fresh (default: less than 15 minutes old). Party Ready stays the separate pre-travel feature that the issue asks for, and health only feeds it.
- **Where it runs:** `python3 -m avrana.ops.health` over SSH, as the operator, without sudo, just as the preflight runs. It never changes, restarts or installs anything.
- **The owner route comes later** and needs the AVR-44 owner session. It is never public: unlike `avrana.status/v0`, it names storage, power and logs. Guests keep the public status (counts only) and the AVR-87 light.

## 3. The support bundle: a field package without a test night

The field-session tool already writes exactly the right kind of package:
- bounded (2 MiB) and deterministic;
- every string redacted;
- validated before it is written, and refused on any hit.

It only lacks a mode for "something went wrong and nobody pressed `start`". So:

```bash
python3 -m avrana.ops.fieldsession bundle --out ~/ [--hours 6] [--forbid-terms names.txt]
```

- **The same writer and validator, a different window.** It records one snapshot (status, Pi health, a fresh preflight and the health document) and takes the journal and throttle excerpts for the last `--hours` (default 6, at most 24). It writes `avrana-support-<stamp>.tar.gz` with `kind: "support"` in `manifest.json`.
- **The same exclusions, by construction:**
  - no keys, tokens, cookies, `devices.json`, member or device ids, addresses, chat or names;
  - NetworkManager and dnsmasq are not collected;
  - the validator runs on the finished package and refuses to write one with a hit.
- **The same bounds:** 1500 journal lines, warnings first, capped per line; 2 MiB per export.
- **Reproducible:** the same window on the same box gives the same bytes (sorted members, fixed timestamps, zeroed ownership). The manifest records the redaction rules version and the collector SHA.
- **It is never sent anywhere.** The owner hands the file over themselves. The appliance has no upload path, and none is proposed (D4).

## 4. Offline

Everything above reads local facts only:
- loopback status;
- systemd and journald;
- `/run` state files;
- the Party AP address.

No Internet is used. The only time-dependent pieces are the certificate runway and "fresh preflight". When the clock is unknown (AVR-79, draft #228), both are reported as `unknown` with the reason "the date is not trusted", never as healthy.

## 5. Exit criteria

| Criterion | Section |
|---|---|
| Healthy, degraded and action-required states | 2 (plus `unknown`, never rolled up as healthy) |
| The owner inspects health without a shell | 2: a later owner route; until AVR-44 lands, a single SSH command with plain words |
| Bundle contents and redaction rules defined | 3: the field-package members and `avrana/ops/redact.py` |
| Bounded and reproducible export | 3 |
| Keys, tokens, Party secrets and other players' private state excluded | 3: the existing rules, validated after writing |
| Works offline | 4 |
| Machine-readable readiness for Party Ready | 2 (`ready`, the per-item `source`) |

## 6. Tests, if built

- A table test maps each status reason, preflight result and pi-health state to one health state.
- `unknown` never rolls up as `healthy`.
- An untrusted clock makes the certificate and freshness items `unknown`.
- A support bundle built from a fixture journal that contains every redaction rule's sample is refused, and one built from a clean journal is byte-identical across two runs.
- `--hours` above 24 is refused.
- The health route, when it exists, answers 401 without an owner session.

## 7. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | Build the SSH health command before the owner page exists? | now; with the owner page | **now**: it is a reader over existing checks, and support uses it immediately |
| D2 | Support bundle as a mode of the field-session tool, or a new tool? | a mode; a new tool | **a mode** (one writer, one validator, one set of rules) |
| D3 | Default journal window | 6 h; 24 h | **6 h**, up to 24 on request |
| D4 | Any upload path for bundles? | never; opt-in later | **never** on the appliance; the owner shares the file |
| D5 | Should health raise owner activity items (AVR-84) and the light (AVR-87)? | yes; no | **yes**: both read this document's state rather than deriving their own |
