"""`qualify`: controlled non-DFS channel matrix, ranked by what the client actually measured.

Lab / pre-event only: every switch drops all clients. It requires --lab, refuses on an unhealthy Pi,
and the AP helper itself refuses while a Party session is active. The AP is always returned to the
default channel (config default_channel) in a finally block; an interrupted run leaves
results/.ap-dirty.json and `wifilab.py ap-recover` finishes the job.

Ranking never uses the neighbouring-network count (it is recorded as information only): on 2026-10-06
an empty-looking channel (149) performed far worse than another empty one (36).
"""
import datetime as dt, importlib.machinery, importlib.util, json, signal, sys, time

HELPER_PATH = None


def helper_module(wl):
    """Load ops/ap-control/avrana-ap-control for its pure channel_allowed() (no copy, no drift)."""
    path = wl.REPO / "ops" / "ap-control" / "avrana-ap-control"
    loader = importlib.machinery.SourceFileLoader("avrana_ap_control", str(path))
    spec = importlib.util.spec_from_loader("avrana_ap_control", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ pure scoring (unit-tested)
def metrics_from(idle, loaded, up):
    """Summaries (or None) -> the numbers used for ranking. Missing stays None."""
    g = lambda s, *k: None if not s else _dig(s, k)
    losses = [x for x in (g(idle, "ping", "loss_pct"), g(loaded, "ping", "loss_pct"), g(up, "ping", "loss_pct")) if x is not None]
    return {"idle_p99_ms": g(idle, "ping", "p99_ms"), "loaded_p99_ms": g(loaded, "ping", "p99_ms"),
            "max_loss_pct": max(losses) if losses else None,
            "idle_retry_ratio": g(idle, "tablet", "tx_retry_ratio"), "loaded_retry_ratio": g(loaded, "tablet", "tx_retry_ratio"),
            "uplink_mbps": g(up, "traffic", "tablet_tx_mbps"), "down_mbps": g(loaded, "traffic", "tablet_rx_mbps")}


def _dig(d, keys):
    for k in keys:
        if d is None:
            return None
        d = d.get(k)
    return d


def score(m):
    """100 minus capped penalties. A missing metric takes its full penalty (and is flagged by the caller).

    score = 100 - 25*min(1, idle_p99/300) - 25*min(1, loaded_p99/1000) - 15*min(1, max_loss/3)
                - 15*min(1, idle_retry/10) - 10*min(1, loaded_retry/30) - 10*(1 - min(1, uplink_mbps/20))
    A heuristic for ordering candidates on one client at one place, not a universal quality measure."""
    def frac(v, scale):
        return 1.0 if v is None else min(1.0, v / scale)
    up = m.get("uplink_mbps")
    return round(100 - 25 * frac(m.get("idle_p99_ms"), 300) - 25 * frac(m.get("loaded_p99_ms"), 1000)
                 - 15 * frac(m.get("max_loss_pct"), 3) - 15 * frac(m.get("idle_retry_ratio"), 10)
                 - 10 * frac(m.get("loaded_retry_ratio"), 30)
                 - 10 * (1.0 if up is None else 1 - min(1.0, up / 20)), 1)


def rank(records):
    """Gate verdict first (PASS < WARN < FAIL, errors last), then score descending. Returns new list."""
    order = {"PASS": 0, "WARN": 1, "FAIL": 2}
    return sorted(records, key=lambda r: (order.get(r.get("verdict"), 3), -(r.get("score") if r.get("score") is not None else -1)))


def uplink_result(mbps, spec):
    if mbps is None:
        return ("WARN", "uplink throughput unavailable")
    if mbps < spec["fail"]:
        return ("FAIL", f"uplink {mbps} Mbps below fail limit {spec['fail']}")
    if mbps < spec["warn"]:
        return ("WARN", f"uplink {mbps} Mbps below warn limit {spec['warn']}")
    return ("PASS", f"uplink {mbps} Mbps ok")


# ------------------------------------------------------------------ run
def neighbours_on(wl, freq):
    """Informational only: networks the client hears on this exact 5 GHz frequency (-80 dBm or stronger)."""
    wl.adb_shell("cmd wifi start-scan")
    time.sleep(6)
    rows = wl.parse_scan_results(wl.adb_shell("cmd wifi list-scan-results", timeout=30))
    return sum(1 for r in rows if r["freq"] == freq and r["rssi"] >= -80 and r["ssid"] != wl.CFG["ap_ssid"])


def run_qualify(args, wl):
    import gate, loadtest
    if not args.lab:
        sys.exit("qualify disconnects every client at each step. Run it only in the lab or before a party, and pass --lab. "
                 "Never during play (the AP helper also refuses while a Party session is active).")
    wl.pick_device(wl.CFG.get("android_serial"))
    qcfg, gcfg = wl.CFG["qualify"], wl.CFG["gate"]
    default = int(wl.CFG["default_channel"])
    if wl.DIRTY.exists():
        sys.exit(f"{wl.DIRTY} exists: an earlier qualification was interrupted. Run `wifilab.py ap-recover` first.")
    wl.require_only_own_client()
    h0 = wl.pi_health()
    if h0["state"] != "HEALTHY":
        sys.exit(f"Pi health is {h0['state']} ({'; '.join(h0.get('reasons', []))}); refusing to switch channels")

    # regulatory check on the Pi itself, using the helper's own rule
    phy = wl.pi('export PATH=$PATH:/usr/sbin; iw dev %s info | sed -n "s/.*wiphy \\([0-9]*\\)/\\1/p"' % wl.CFG["pi_wifi_iface"]).strip() or "0"
    info = wl.pi(f"export PATH=$PATH:/usr/sbin; iw phy phy{phy} info")
    helper = helper_module(wl)
    wanted = [int(c) for c in (args.channels.split(",") if args.channels else qcfg["candidates"])]
    permitted = [c for c in wanted if c in helper.APPROVED_CHANNELS and helper.channel_allowed(info, c)]
    skipped = {c: "not approved or not permitted by the regulatory domain on this radio" for c in wanted if c not in permitted}
    orig = wl.ap_helper("show")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    serial = wl.CFG["android_serial"]
    parent = wl.RESULTS / f"{stamp}_qualify_{serial[-4:]}"
    parent.mkdir(parents=True)
    wl.DIRTY.write_text(json.dumps({"started": stamp, "serial": serial, "original": orig.get("profile"), "current": None}))
    print(f"qualifying channels {permitted} (skipped: {skipped or 'none'}); original {orig.get('profile')}; default after: {default}")

    prev_term = signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    records = []
    try:
        for ch in permitted:
            rec = {"channel": ch}
            records.append(rec)
            try:
                wl.DIRTY.write_text(json.dumps({**json.loads(wl.DIRTY.read_text()), "current": ch}))
                wl.ap_helper("set-channel", str(ch), "--lab")
                rec["rejoin"] = wl.wait_rejoin()
                wl.CFG["expect_channel"] = ch
                sub = parent / f"ch{ch}"
                sub.mkdir()
                dur = wl.CFG["ping_interval_s"]
                _, idle = wl.run_trial("idle", f"q{ch}", qcfg["idle_count"], dur, parent=sub, quiet=True)
                mode = f"down-{qcfg['loaded_mbps']}M"
                _, loaded = wl.run_trial("loaded-" + mode, f"q{ch}", qcfg["loaded_count"], dur, {"mode": mode},
                                         traffic=loadtest.Traffic(wl, mode, qcfg["loaded_count"] * dur + 12), parent=sub, quiet=True)
                _, up = wl.run_trial("loaded-up-max", f"q{ch}", qcfg["uplink_count"], dur, {"mode": "up-max"},
                                     traffic=loadtest.Traffic(wl, "up-max", qcfg["uplink_count"] * dur + 12), parent=sub, quiet=True)
                h1 = wl.pi_health()
                res = (gate.evaluate_phase("idle", idle, gcfg["idle"], gcfg["min_tx_samples_for_retry_ratio"])
                       + gate.evaluate_phase("loaded", loaded, gcfg["loaded"], gcfg["min_tx_samples_for_retry_ratio"], qcfg["loaded_mbps"])
                       + [uplink_result(_dig(up, ("traffic", "tablet_tx_mbps")), qcfg["uplink_mbps"])]
                       + gate.evaluate_health([("after", h1)]))
                m = metrics_from(idle, loaded, up)
                rec.update(verdict=gate.verdict(res), score=score(m), metrics=m,
                           missing_metrics=[k for k, v in m.items() if v is None],
                           reasons=[{"level": l, "text": t} for l, t in res if l != "PASS"],
                           neighbours_same_channel_info_only=neighbours_on(wl, idle["ap"]["freq_mhz"]),
                           rssi_dbm=idle["tablet"]["rssi_after"], link_mbps=idle["tablet"]["tx_link_mbps_after"], dir=str(sub))
            except KeyboardInterrupt:
                rec.update(verdict="FAIL", error="interrupted")
                raise
            except Exception as e:  # one bad channel must not stop the matrix or skip the restore
                rec.update(verdict="FAIL", error=str(e), score=None)
            finally:
                wl.CFG.pop("expect_channel", None)
                (parent / "qualify.json").write_text(json.dumps({"records": records, "skipped": skipped}, indent=2))
    finally:
        signal.signal(signal.SIGTERM, prev_term)
        print(f"restoring default channel {default} ...")
        try:
            wl.ap_helper("set-channel", str(default), "--lab")
            wl.wait_rejoin()
            wl.DIRTY.unlink()
            restored = True
        except Exception as e:
            restored = False
            print(f"RESTORE FAILED: {e}\n  run `wifilab.py ap-recover` or the owner restores the profile by hand.", file=sys.stderr)
        ranked = rank(records)
        doc = {"schema": "avrana.wifi-qualify/v1", "started": stamp, "client": serial, "original_profile": orig.get("profile"),
               "default_channel": default, "restored_default": restored, "skipped": skipped, "ranked": ranked,
               "scoring": "see qualify.score docstring / docs/runbooks/wifi-qualification.md; heuristic, not universal",
               "thresholds_status": gcfg["_status"]}
        (parent / "qualify.json").write_text(json.dumps(doc, indent=2))
        (parent / "qualify.txt").write_text(render(doc))
        print(render(doc))


def render(doc):
    L = [f"Channel qualification ({doc['started']}, client {doc['client']}); default restored: {doc['restored_default']}",
         "rank  ch   verdict  score  idle p99  loaded p99  loss%  idle retry  up Mbps  RSSI  [neighbours: info only]"]
    for i, r in enumerate(doc["ranked"], 1):
        m = r.get("metrics") or {}
        L.append(f"{i:>4}  {r['channel']:<4} {r.get('verdict', '?'):<8} {r.get('score')!s:<6} {m.get('idle_p99_ms')!s:<9} "
                 f"{m.get('loaded_p99_ms')!s:<11} {m.get('max_loss_pct')!s:<6} {m.get('idle_retry_ratio')!s:<11} "
                 f"{m.get('uplink_mbps')!s:<8} {r.get('rssi_dbm')!s:<5} [{r.get('neighbours_same_channel_info_only')}]"
                 + (f"  ERROR: {r['error']}" if r.get("error") else ""))
    for c, why in doc.get("skipped", {}).items():
        L.append(f"skip  {c}: {why}")
    return "\n".join(L) + "\n"


def register(sub):
    p = sub.add_parser("qualify", help="controlled non-DFS channel matrix with ranking (lab only)")
    p.add_argument("--lab", action="store_true", help="required: acknowledges that every client is disconnected at each step")
    p.add_argument("--channels", help="comma list overriding the configured candidates")
    p.set_defaults(func=run_qualify)
