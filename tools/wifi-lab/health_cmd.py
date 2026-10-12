"""`health`: run the bounded Pi health check over ssh and print state, reasons and key evidence."""
import json


def register(sub):
    p = sub.add_parser("health", help="Pi hardware-health state (HEALTHY/DEGRADED/FIRMWARE_MAILBOX_SUSPECT/POWER_THROTTLE_DETECTED/UNKNOWN)")
    p.add_argument("--json", action="store_true", help="print the full JSON document")
    p.set_defaults(func=run_health)


def run_health(args, wl):
    doc = wl.pi_health()
    if args.json:
        print(json.dumps(doc, indent=2))
    else:
        ev = doc.get("evidence", {})
        print(doc["state"])
        for r in doc.get("reasons", []) or ["nothing abnormal observed"]:
            print(f"  - {r}")
        print(f"  host {ev.get('host')}  uptime {ev.get('uptime_s')}s  temp {ev.get('temp_c')} C  load {ev.get('load')}  "
              f"throttled {(ev.get('throttled') or {}).get('raw') or (ev.get('throttled') or {}).get('error')}  "
              f"stuck vcgencmd {ev.get('stuck_vcgencmd')}")
    raise SystemExit(0 if doc["state"] == "HEALTHY" else 1)
