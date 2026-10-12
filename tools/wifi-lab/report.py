"""`report`: concise tables from stored runs (results/*), as text or Markdown (REPORT.md).

Covers single trials (baseline / loaded), pre-event gate verdicts, channel qualification rankings and
multi-client steps. Nothing is recomputed from raw evidence here: it reads the JSON each command wrote.
"""
import json
from pathlib import Path

TRIAL_COLS = ["run", "client", "radio", "kind", "loss%", "p50", "p95", "p99", "max", "rssi", "link", "retry/ok", "thru", "health", "tempC"]


def trial_row(name, s):
    p, t, a, q, c = s["ping"], s["tablet"], s["ap"], s["pi"], s.get("client") or {}
    tr = s.get("traffic") or {}
    thru = tr.get("tablet_rx_mbps") if "down" in s["kind"] else tr.get("tablet_tx_mbps") if "up" in s["kind"] else None
    return [name, c.get("serial", "?")[-4:], f"{a['band']} ch{a['channel']}", s["kind"], p.get("loss_pct"), p.get("p50_ms"),
            p.get("p95_ms"), p.get("p99_ms"), p.get("max_ms"), t.get("rssi_after"), t.get("tx_link_mbps_after"),
            t.get("tx_retry_ratio"), thru, q.get("health_after"), q.get("temp_c_after")]


def md_table(header, rows):
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
                     + ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows])


def load_all(results):
    trials, gates, quals, multis = [], [], [], []
    for d in sorted(Path(results).iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if (d / "summary.json").exists():
            trials.append((d.name, json.loads((d / "summary.json").read_text())))
        if (d / "gate.json").exists():
            gates.append((d.name, json.loads((d / "gate.json").read_text())))
        if (d / "qualify.json").exists():
            quals.append((d.name, json.loads((d / "qualify.json").read_text())))
        if (d / "multi.json").exists():
            multis.append((d.name, json.loads((d / "multi.json").read_text())))
    return trials, gates, quals, multis


def render_markdown(trials, gates, quals, multis, label=None):
    out = ["# Wi-Fi lab report", "", "Generated from `results/`; raw evidence stays next to each run. "
           "Gate thresholds are provisional; qualification scores are a heuristic (see docs/runbooks/wifi-qualification.md).", ""]
    if gates:
        out += ["## Pre-event gate runs", ""]
        for name, g in gates:
            c, a = g.get("client") or {}, g.get("ap") or {}
            out.append(f"### {name}: **{g['verdict']}**  ({g['duration_s']} s, client {c.get('serial')}, "
                       f"{a.get('band')} ch{a.get('channel')})")
            out += [f"- [{r['level']}] {r['text']}" for r in g["results"] if r["level"] != "PASS"] or ["- all checks passed"]
            out.append("")
    for name, q in quals:
        if "ranked" not in q:
            continue
        out += [f"## Channel qualification {name}", "",
                f"Client {q['client']}; original state restored: {q.get('restored_original', q.get('restored_default'))}; original profile {q.get('original_profile')}", ""]
        rows = []
        for i, r in enumerate(q["ranked"], 1):
            m = r.get("metrics") or {}
            rows.append([i, r["channel"], r.get("verdict"), r.get("score"), m.get("idle_p99_ms"), m.get("loaded_p99_ms"),
                         m.get("max_loss_pct"), m.get("idle_retry_ratio"), m.get("uplink_mbps"), r.get("rssi_dbm"),
                         r.get("neighbours_same_channel_info_only"), r.get("error") or ""])
        out += [md_table(["rank", "ch", "verdict", "score", "idle p99", "loaded p99", "loss%", "idle retry", "up Mbps", "RSSI",
                          "neighbours (info only)", "error"], rows), ""]
        if q.get("skipped"):
            out += ["Skipped: " + "; ".join(f"{c} ({w})" for c, w in q["skipped"].items()), ""]
    for name, m in multis:
        if "steps" not in m:
            continue
        out += [f"## Multi-client {name}", "", f"Synthetic path: **{m.get('synthetic_path')}** ({m.get('warning', '')})", ""]
        rows = [[s["clients_requested"], s["real"], s["synthetic"], s["aggregate"]["worst_p99_ms"], s["aggregate"]["worst_loss_pct"],
                 s["aggregate"]["total_reconnects"], s["pi"]["health_after"], s["pi"]["load"], s["pi"]["temp_c"]] for s in m["steps"]]
        out += [md_table(["clients", "real", "synthetic", "worst p99 ms", "worst loss%", "reconnects", "Pi health", "Pi load", "Pi tempC"], rows), ""]
    rows = [trial_row(n, s) for n, s in trials if not label or label in n]
    if rows:
        out += ["## Trials", "", md_table(TRIAL_COLS, rows), ""]
    return "\n".join(out) + "\n"


def run_report(args, wl):
    trials, gates, quals, multis = load_all(wl.RESULTS)
    text = render_markdown(trials, gates, quals, multis, args.label)
    print(text)
    if args.write:
        (wl.RESULTS / "REPORT.md").write_text(text)
        print(f"wrote {wl.RESULTS / 'REPORT.md'}")


def register(sub):
    p = sub.add_parser("report", help="tables from stored runs (trials, gates, channel rankings, multi-client)")
    p.add_argument("--label", help="only trials whose directory name contains this")
    p.add_argument("--write", action="store_true", help="also write results/REPORT.md")
    p.set_defaults(func=run_report)
