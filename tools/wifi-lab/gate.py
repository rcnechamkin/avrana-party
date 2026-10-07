"""`gate`: the ~2-3 minute pre-event network qualification (PASS / WARN / FAIL with reasons).

Steps: Pi health, client route verification, idle latency sample, ~20 Mbps downlink load sample,
then thresholds from config.json ("gate", provisional). Unknown important metrics never pass silently.
The evaluation is a pure function (evaluate) so it is unit-tested without devices.
"""
import datetime as dt, json, sys
from pathlib import Path

RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}


def _check(level_name, value, spec, unit, higher_is_worse=True):
    """-> (level, text) or None when value missing (caller handles unavailability)."""
    if value is None:
        return None
    if higher_is_worse:
        if value > spec["fail"]:
            return "FAIL", f"{level_name} {value}{unit} exceeds fail limit {spec['fail']}{unit}"
        if value > spec["warn"]:
            return "WARN", f"{level_name} {value}{unit} exceeds warn limit {spec['warn']}{unit}"
    else:
        if value < spec["fail"]:
            return "FAIL", f"{level_name} {value}{unit} below fail limit {spec['fail']}{unit}"
        if value < spec["warn"]:
            return "WARN", f"{level_name} {value}{unit} below warn limit {spec['warn']}{unit}"
    return "PASS", f"{level_name} {value}{unit} ok"


def evaluate_phase(name, summary, spec, min_tx, offered_mbps=None):
    """Judge one trial summary (idle or loaded) against thresholds. Returns list of (level, text)."""
    out = []
    p, t = summary["ping"], summary["tablet"]
    if p.get("received", 0) == 0:
        return [("FAIL", f"{name}: no ping replies at all")]
    for key, label, unit in (("p95_ms", "p95 latency", " ms"), ("p99_ms", "p99 latency", " ms")):
        r = _check(f"{name} {label}", p.get(key), spec[key], unit)
        out.append(r or ("WARN", f"{name} {label} unavailable"))
    r = _check(f"{name} packet loss", p.get("loss_pct"), spec["loss_pct"], "%")
    out.append(r or ("WARN", f"{name} packet loss unavailable"))
    samples = (t.get("tx_success_delta") or 0) + (t.get("tx_retries_delta") or 0)
    if not t.get("retry_counters_available"):
        out.append(("WARN", f"{name} retry counters unavailable from the client"))
    elif samples < min_tx:
        out.append(("WARN", f"{name} too few client TX samples ({samples} < {min_tx}) to judge the retry ratio"))
    else:
        out.append(_check(f"{name} client TX retry ratio", t["tx_retry_ratio"], spec["retry_ratio"], ""))
    if offered_mbps:
        tr = summary.get("traffic") or {}
        got = tr.get("tablet_rx_mbps")
        if got is None:
            out.append(("WARN", f"{name} delivered throughput unavailable"))
        else:
            frac = round(got / offered_mbps, 2)
            r = _check(f"{name} delivered/offered", frac, spec["delivered_fraction"], "", higher_is_worse=False)
            out.append((r[0], r[1] + f" ({got} of {offered_mbps} Mbps)"))
    return corroborate_retries(name, out)


def corroborate_retries(name, results):
    """The client's retry counter is noisy: on a clean channel 36 run (2026-10-07) it read 129 retries per
    success while latency, loss and throughput were all perfect. So a retry-ratio FAIL stands only when
    another metric of the same phase is also degraded; otherwise it is reported as a WARN that says why."""
    others_degraded = any(l != "PASS" for l, t in results if "retry ratio" not in t)
    fixed = []
    for l, t in results:
        if l == "FAIL" and "retry ratio" in t and not others_degraded:
            fixed.append(("WARN", t + "; latency, loss and throughput are within limits, so this noisy client counter alone is not a FAIL"))
        else:
            fixed.append((l, t))
    return fixed


def evaluate_health(health_docs):
    """List of health documents (before/after) -> [(level, text)]."""
    out = []
    for when, doc in health_docs:
        st = doc.get("state", "UNKNOWN")
        rs = "; ".join(doc.get("reasons", [])) or "nothing abnormal"
        if st == "HEALTHY":
            out.append(("PASS", f"Pi health {when}: HEALTHY"))
        elif st == "DEGRADED":
            out.append(("WARN", f"Pi health {when}: DEGRADED ({rs})"))
        elif st in ("FIRMWARE_MAILBOX_SUSPECT", "POWER_THROTTLE_DETECTED"):
            out.append(("FAIL", f"Pi health {when}: {st} ({rs})"))
        else:
            out.append(("FAIL", f"Pi health {when}: {st}, important metric unavailable ({rs})"))
    return out


def verdict(results):
    worst = max((RANK[l] for l, _ in results), default=2)
    name = {0: "PASS", 1: "WARN", 2: "FAIL"}[worst]
    return name


def render(name, results, extra=""):
    order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    lines = [name] + [f"  - [{l}] {t}" for l, t in sorted(results, key=lambda r: order[r[0]])]
    return "\n".join(lines) + ("\n" + extra if extra else "") + "\n"


def run_gate(args, wl):
    import loadtest
    cfg = wl.CFG["gate"]

    def one():
        t0 = dt.datetime.now()
        parent = wl.RESULTS / f"{t0.strftime('%Y%m%d-%H%M%S')}_gate_{(wl.CFG.get('android_serial') or 'dev')[-4:]}"
        parent.mkdir(parents=True)
        results, health_docs = [], []
        h0 = wl.pi_health()
        health_docs.append(("before", h0))
        (parent / "health-start.json").write_text(json.dumps(h0, indent=2))
        pf = wl.preflight()
        results.append(("PASS", f"client route verified: {pf['path']['route_dev']} {pf['path']['tablet_ip']}")
                       if pf["ok"] else ("FAIL", "client route/Wi-Fi/SSH preflight failed: "
                                         + "; ".join(pf.get("path", {}).get("problems", []) or [pf.get("error", "unknown")])))
        idle = loaded = None
        if pf["ok"] and h0.get("state") not in ("FIRMWARE_MAILBOX_SUSPECT", "POWER_THROTTLE_DETECTED"):
            try:
                _, idle = wl.run_trial("idle", "gate", cfg["idle_count"], wl.CFG["ping_interval_s"], parent=parent, quiet=True)
                mode = f"down-{cfg['loaded_mbps']}M"
                _, loaded = wl.run_trial("loaded-" + mode, "gate", cfg["loaded_count"], wl.CFG["ping_interval_s"],
                                         {"mode": mode}, traffic=loadtest.Traffic(wl, mode, cfg["loaded_count"] * wl.CFG["ping_interval_s"] + 12),
                                         parent=parent, quiet=True)
                results += evaluate_phase("idle", idle, cfg["idle"], cfg["min_tx_samples_for_retry_ratio"])
                results += evaluate_phase("loaded", loaded, cfg["loaded"], cfg["min_tx_samples_for_retry_ratio"], cfg["loaded_mbps"])
                ap = idle["ap"]
                results.append(("PASS", f"AP band/channel recorded: {ap['band']} ch{ap['channel']} {ap['width_mhz']} MHz"))
            except Exception as e:  # a link that drops mid-gate is a FAIL with a reason, never a traceback
                results.append(("FAIL", f"test aborted: {type(e).__name__}: {e}"))
            health_docs.append(("after", wl.pi_health()))
        else:
            results.append(("FAIL", "load/latency tests skipped because the Pi health or the client path is not fit to test"))
        results += evaluate_health(health_docs)
        v = verdict(results)
        doc = {"schema": "avrana.wifi-gate/v1", "verdict": v, "started": t0.isoformat(timespec="seconds"),
               "duration_s": round((dt.datetime.now() - t0).total_seconds()),
               "thresholds": cfg, "thresholds_status": cfg["_status"],
               "client": (idle or {}).get("client"), "ap": (idle or {}).get("ap"),
               "results": [{"level": l, "text": t} for l, t in results],
               "idle": idle, "loaded": loaded, "health": {w: d for w, d in health_docs}}
        (parent / "gate.json").write_text(json.dumps(doc, indent=2))
        text = render(v, results, f"(thresholds are provisional; {doc['duration_s']} s; evidence in {parent})")
        (parent / "gate.txt").write_text(text)
        print(text)
        wl.GATE_VERDICTS.append(v)

    wl.GATE_VERDICTS = []
    wl.for_each_device(args, one)
    code = {"PASS": 0, "WARN": 1, "FAIL": 2}[max(wl.GATE_VERDICTS, key=lambda x: RANK[x])] if wl.GATE_VERDICTS else 2
    sys.exit(code)


def register(sub):
    p = sub.add_parser("gate", help="2-3 minute pre-event PASS/WARN/FAIL (health, route, idle, 20 Mbps load, retries, loss, percentiles)")
    p.set_defaults(func=run_gate)
