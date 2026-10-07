#!/usr/bin/env python3
"""Avrana Wi-Fi lab: client-side qualification of the Pi access point (AVR-296).

Path under test: Android client --Wi-Fi--> Pi AP (wlan0). USB is control-only (adb).
Standard library only. Commands (see README.md):

  health      Pi hardware-health state (bounded; never hangs on a wedged vcgencmd)
  gate        ~2-3 min pre-event PASS / WARN / FAIL
  baseline    idle latency trial(s)            (alias: idle)
  loaded      latency under controlled load    (alias: load)
  qualify     controlled channel matrix + ranking (lab only, never during a party)
  multi       multi-client latency steps (real devices + labelled synthetic clients)
  report      tables and markdown from stored runs
  ap          show / set / restore the AP channel through the restricted helper
  ap-recover  put the AP back after an interrupted qualification
  preflight   checks only

Rules this tool keeps: every external command has a time limit; the Pi is never touched with
sudo except through the fixed-allow-list helper ops/ap-control/avrana-ap-control; vcgencmd is only
run by the bounded health check; nothing here reboots or restarts anything.
"""
import argparse, csv, datetime as dt, json, math, os, re, shutil, statistics, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RESULTS = HERE / "results"
HEALTH_SCRIPT = REPO / "telemetry" / "pi-health-check.py"
CFG = {}
SCHEMA = "avrana.wifi-lab/v1"


class TrialRefused(Exception):
    """A trial could not or must not run (bad path, wrong channel, ssh down). The gate maps it to FAIL."""


# ---------------------------------------------------------------- plumbing
def load_cfg(overrides):
    CFG.update(json.loads((HERE / "config.json").read_text()))
    for kv in overrides or []:
        k, v = kv.split("=", 1)
        try:
            v = json.loads(v)
        except ValueError:
            pass
        CFG[k] = v


def find_adb():
    cands = [CFG.get("adb_path"), shutil.which("adb")]
    exe = "adb.exe" if os.name == "nt" else "adb"
    cands += [str(Path(os.path.expanduser(d)) / exe) for d in CFG["adb_search"]]
    for c in cands:
        if c and Path(c).exists():
            return c
    sys.exit("adb not found: put it on PATH or set adb_path in config.json")


def run(cmd, timeout, input_text=None):
    """Bounded subprocess. A timeout returns (124, partial stdout, 'timeout after Ns'), never raises."""
    # bytes in/out: text mode would turn the script's \n into \r\n on Windows and break bash
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           input=input_text.encode() if input_text is not None else None)
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or b"").decode(errors="replace"), f"timeout after {timeout}s"
    except OSError as e:
        return 127, "", f"cannot run {cmd[0]}: {e}"
    dec = lambda b: b.decode(errors="replace").replace("\r\n", "\n")
    return p.returncode, dec(p.stdout), dec(p.stderr)


def adb(*args, timeout=30):
    base = [find_adb()] + (["-s", CFG["android_serial"]] if CFG.get("android_serial") else [])
    return run(base + list(args), timeout)


def adb_shell(cmd, timeout=30):
    return adb("exec-out", cmd, timeout=timeout)[1]


def ssh_cmd(remote):
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", CFG["pi_ssh_host"], remote]


def pi(script, timeout=None, remote="bash -s"):
    """Run a script on the Pi through the user's ssh alias (no sudo, no new credentials)."""
    rc, out, err = run(ssh_cmd(remote), timeout or CFG["ssh_timeout_s"], script)
    if rc != 0:
        raise RuntimeError(f"ssh failed rc={rc}: {err.strip()}")
    return out


# ---------------------------------------------------------------- devices
def list_devices():
    """[{serial, state, model}] from `adb devices -l` (bounded)."""
    rc, out, err = run([find_adb(), "devices", "-l"], 15)
    devs = []
    for line in out.splitlines()[1:]:
        m = re.match(r"(\S+)\s+(device|unauthorized|offline)\b(.*)", line)
        if m:
            model = re.search(r"model:(\S+)", m.group(3))
            devs.append({"serial": m.group(1), "state": m.group(2), "model": model.group(1) if model else None})
    return devs


def pick_device(serial=None):
    """Select the adb device for this run. Refuses ambiguity instead of letting adb guess."""
    devs = list_devices()
    ready = [d for d in devs if d["state"] == "device"]
    if serial:
        match = [d for d in devs if d["serial"] == serial]
        if not match:
            sys.exit(f"device {serial} not found; adb sees: {[d['serial'] for d in devs]}")
        if match[0]["state"] != "device":
            sys.exit(f"device {serial} is {match[0]['state']}: unlock it and tap Allow on the USB-debugging prompt")
        CFG["android_serial"] = serial
        return match[0]
    if len(ready) == 1:
        CFG["android_serial"] = ready[0]["serial"]
        return ready[0]
    if not ready:
        sys.exit("no authorized adb device (unauthorized? unplug/replug and tap Allow)")
    sys.exit(f"{len(ready)} devices attached: pass --device SERIAL or --all-devices ({[d['serial'] for d in ready]})")


# ---------------------------------------------------------------- pure parsers (unit-tested)
PING_RE = re.compile(r"icmp_seq=(\d+).*?time=([\d.]+)\s*ms")


def parse_ping(text, sent=None):
    """Per-seq RTTs and summary stats. Missing sequence numbers count as lost."""
    rtts = {}
    for m in PING_RE.finditer(text):
        rtts.setdefault(int(m.group(1)), float(m.group(2)))  # first reply wins (ignore dups)
    if sent is None:
        m = re.search(r"(\d+) packets transmitted", text)
        sent = int(m.group(1)) if m else (max(rtts) if rtts else 0)
    vals = [rtts[s] for s in sorted(rtts)]
    out = {"sent": sent, "received": len(vals),
           "loss_pct": round(100.0 * (sent - len(vals)) / sent, 2) if sent else None}
    if not vals:
        return out, rtts
    sv = sorted(vals)

    def pct(p):
        k = (len(sv) - 1) * p / 100.0
        f, c = math.floor(k), math.ceil(k)
        return sv[f] + (sv[c] - sv[f]) * (k - f)

    seqs = sorted(rtts)
    diffs = [abs(rtts[b] - rtts[a]) for a, b in zip(seqs, seqs[1:]) if b == a + 1]
    longest = cur = 0
    prev = None
    for s in (s for s in range(1, sent + 1) if s not in rtts):
        cur = cur + 1 if prev is not None and s == prev + 1 else 1
        longest, prev = max(longest, cur), s
    out.update(
        min_ms=sv[0], avg_ms=round(statistics.fmean(vals), 2), p50_ms=round(pct(50), 2),
        p95_ms=round(pct(95), 2), p99_ms=round(pct(99), 2), max_ms=sv[-1],
        stdev_ms=round(statistics.pstdev(vals), 2),
        jitter_mean_abs_delta_ms=round(statistics.fmean(diffs), 2) if diffs else None,
        longest_loss_burst=longest,
        spikes={f">{t}ms": sum(1 for v in vals if v > t) for t in CFG.get("spike_thresholds_ms", [50, 100, 250])},
    )
    return out, rtts


def parse_sections(text):
    secs, cur = {}, None
    for line in text.splitlines():
        if line.startswith("@@"):
            cur = line[2:].strip()
            secs[cur] = []
        elif cur is not None:
            secs[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in secs.items()}


STR_KEYS = ("authorized", "authenticated", "associated", "WMM/WME", "TDLS peer")


def parse_station_dump(text):
    stations, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"Station ([0-9a-f:]{17})", line)
        if m:
            cur = stations.setdefault(m.group(1), {})
        elif cur is not None and ":" in line:
            k, v = (x.strip() for x in line.strip().split(":", 1))
            m2 = re.match(r"(-?[\d.]+)", v)
            cur[k] = float(m2.group(1)) if m2 and k not in STR_KEYS else v
    return stations


def parse_cmd_wifi_status(text):
    d = {m.group(1): int(m.group(2)) for m in re.finditer(
        r"^(successfulTxPackets|retriedTxPackets|lostTxPackets|successfulRxPackets): (\d+)$", text, re.M)}
    m = re.search(r"RSSI: (-?\d+), Link speed: (\d+)Mbps, Tx Link speed: (\d+)Mbps.*?Rx Link speed: (\d+)Mbps.*?"
                  r"Frequency: (\d+)MHz", text)
    if m:
        d.update(rssi_dbm=int(m.group(1)), link_mbps=int(m.group(2)), tx_link_mbps=int(m.group(3)),
                 rx_link_mbps=int(m.group(4)), freq_mhz=int(m.group(5)))
    m = re.search(r'connected to "(.*?)"', text)
    if m:
        d["ssid"] = m.group(1)
    return d


def parse_scan_results(text):
    """`cmd wifi list-scan-results` -> [{bssid, freq, rssi, ssid}] (informational neighbour view only)."""
    rows = []
    for line in text.splitlines():
        m = re.match(r"\s*([0-9a-f:]{17})\s+(\d+)\s+(-?\d+)\s+\S+\s*(.*?)\s{2,}", line + "  ")
        if m:
            rows.append({"bssid": m.group(1), "freq": int(m.group(2)), "rssi": int(m.group(3)), "ssid": m.group(4).strip()})
    return rows


def freq_to_chan(f):
    if f is None:
        return None
    return (f - 2407) // 5 if f < 3000 else (f - 5000) // 5


def parse_health_json(text):
    """The health script prints one JSON object per run; tolerate ssh banner lines before it."""
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------- collectors
PI_SNAPSHOT = r"""
export PATH=$PATH:/usr/sbin:/sbin
echo "@@epoch"; date +%s.%N
echo "@@iw_info"; iw dev __IF__ info
echo "@@stations"; iw dev __IF__ station dump
echo "@@survey"; iw dev __IF__ survey dump 2>&1 | head -40
echo "@@power_save"; iw dev __IF__ get power_save 2>&1
echo "@@reg"; iw reg get 2>&1 | head -4
echo "@@nm_profile"; nmcli -t -f 802-11-wireless.ssid,802-11-wireless.band,802-11-wireless.channel,802-11-wireless.mode,802-11-wireless.powersave,ipv4.method,ipv4.addresses connection show "__CONN__" 2>&1
echo "@@mem"; free -m
true
"""


def pi_snapshot():
    return pi(PI_SNAPSHOT.replace("__IF__", CFG["pi_wifi_iface"]).replace("__CONN__", CFG["ap_connection"]))


def pi_health():
    """Run the bounded health check on the Pi (script piped over ssh, nothing installed). Never raises."""
    try:
        out = pi(HEALTH_SCRIPT.read_text(), timeout=CFG["health_timeout_s"], remote="python3 -")
    except Exception as e:
        return {"state": "UNKNOWN", "reasons": [f"health check could not run: {e}"], "evidence": {}, "error": str(e)}
    doc = parse_health_json(out)
    if doc is None:
        return {"state": "UNKNOWN", "reasons": ["health check produced no parsable output"], "evidence": {},
                "error": out[-300:]}
    return doc


def tablet_snapshot():
    route = adb_shell(f"ip route get {CFG['ap_ip']}")
    iface = (re.search(r"dev (\S+)", route) or [None, "wlan0"])[1]
    CFG["tablet_iface"] = iface
    return {
        "epoch": str(time.time()),
        "cmd_wifi_status": adb_shell("cmd wifi status"),
        "ip_addr": adb_shell("ip addr"),
        "ip_route": adb_shell("ip route") + "---\n" + route,
        "iface": iface,
        "mac": adb_shell(f"cat /sys/class/net/{iface}/address").strip(),
        "proc_wireless": adb_shell("cat /proc/net/wireless"),
    }


def write_tablet(path, snap):
    path.write_text("".join(f"@@{k}\n{v}\n" for k, v in snap.items()))


def verify_path(tab):
    """Phase-2 proof: traffic to the AP leaves via the client's Wi-Fi with no competing interface."""
    owned, cur = {}, None
    for m in re.finditer(r"^\d+: (\S+?):|inet (\d+\.\d+\.\d+\.\d+)/", tab["ip_addr"], re.M):
        if m.group(1):
            cur = m.group(1)
        elif cur and cur != "lo":
            owned.setdefault(cur, []).append(m.group(2))
    get = tab["ip_route"].split("---")[-1]
    via = (re.search(r"dev (\S+)", get) or [None, None])[1]
    src = (re.search(r"src (\S+)", get) or [None, None])[1]
    problems = []
    if via is None or not re.match(r"wlan\d", via):
        problems.append(f"route to AP uses {via!r}, not a Wi-Fi interface")
    if [i for i in owned if i != via]:
        problems.append(f"other interfaces hold IPv4 (tethering/USB?): {owned}")
    if not (src or "").startswith(CFG["ap_subnet_prefix"]):
        problems.append(f"client src {src!r} not in {CFG['ap_subnet_prefix']}x")
    return {"route_dev": via, "tablet_ip": src, "ipv4_by_iface": owned, "problems": problems}


def preflight():
    res = {"ok": False}
    devs = list_devices()
    res["adb_devices"] = devs
    if not any(d["state"] == "device" for d in devs):
        res["error"] = "no authorized adb device (unauthorized? unplug/replug and tap Allow)"
        return res
    tab = tablet_snapshot()
    res["tablet"] = parse_cmd_wifi_status(tab["cmd_wifi_status"])
    res["path"] = verify_path(tab)
    res["tablet_ping_ok"] = " 0% packet loss" in adb_shell(f"ping -c 2 -W 2 {CFG['ap_ip']}", timeout=20)
    try:
        res["pi_ssh"] = True
        res["pi_wifi"] = parse_sections(pi_snapshot()).get("iw_info", "")
    except Exception as e:
        res.update(pi_ssh=False, error=str(e))
        return res
    res["ok"] = not res["path"]["problems"] and res["tablet_ping_ok"] and res["tablet"].get("ssid") is not None
    return res


def ap_channel_from(iw_info):
    m = re.search(r"channel (\d+)", iw_info or "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- trials
def run_trial(kind, label, count, interval, extra_meta=None, traffic=None, parent=None, quiet=False):
    """One ping trial (optionally under load). Returns (dir, summary). Refuses to run on a bad path."""
    pf = preflight()
    if not pf["ok"]:
        raise TrialRefused("preflight failed, refusing to benchmark: "
                           + "; ".join(pf.get("path", {}).get("problems", []) or [str(pf.get("error") or "client or Pi not reachable")]))
    want = CFG.get("expect_channel")  # never label a run with a channel the AP isn't on
    got = ap_channel_from(pf.get("pi_wifi"))
    if want is not None and (got is None or int(got) != int(want)):
        raise TrialRefused(f"AP is on channel {got if got else '?'}, expected {want}; refusing to benchmark")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    serial = CFG.get("android_serial") or "device"
    base = parent or RESULTS
    d = base / (f"{kind}_{serial[-4:]}" if parent else f"{stamp}_{label}_{kind}_{serial[-4:]}")
    d.mkdir(parents=True)
    health_before = pi_health()
    pb_raw = pi_snapshot()
    (d / "pi-before.txt").write_text(pb_raw)
    tb = tablet_snapshot()
    write_tablet(d / "tablet-before.txt", tb)
    if not quiet:
        print(f"[{d.name}] ping {CFG['ap_ip']} x{count} @ {interval}s from {serial} (no SSH during run) ...", flush=True)
    handle = traffic.start() if traffic else None
    t0 = time.time()
    raw = adb_shell(f"ping -c {count} -i {interval} -W {CFG['ping_reply_timeout_s']} -s {CFG['ping_payload_bytes']} "
                    f"{CFG['ap_ip']}", timeout=int(count * interval) + 90)
    wall = time.time() - t0
    traffic_res = traffic.stop(handle) if traffic else None
    (d / "ping.raw.txt").write_text(raw)
    ta = tablet_snapshot()
    write_tablet(d / "tablet-after.txt", ta)
    pa_raw = pi_snapshot()
    (d / "pi-after.txt").write_text(pa_raw)
    health_after = pi_health()
    (d / "health.json").write_text(json.dumps({"before": health_before, "after": health_after}, indent=2))

    stats, rtts = parse_ping(raw, sent=count)
    with open(d / "ping.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seq", "rtt_ms"])
        for s in range(1, count + 1):
            w.writerow([s, rtts.get(s, "")])
    sb, sa = parse_sections(pb_raw), parse_sections(pa_raw)
    mac = tb["mac"].lower()
    stb, sta = parse_station_dump(sb.get("stations", "")), parse_station_dump(sa.get("stations", ""))
    wb, wa = parse_cmd_wifi_status(tb["cmd_wifi_status"]), parse_cmd_wifi_status(ta["cmd_wifi_status"])
    iwi = sa.get("iw_info", "")
    m = re.search(r"channel (\d+) \((\d+) MHz\), width: (\d+) MHz", iwi)
    reg = sa.get("reg", "").splitlines()
    ap = {"ssid": (re.search(r"ssid (.*)", iwi) or [None, None])[1],
          "channel": int(m.group(1)) if m else None, "freq_mhz": int(m.group(2)) if m else None,
          "width_mhz": int(m.group(3)) if m else None,
          "band": ("5GHz" if int(m.group(2)) > 3000 else "2.4GHz") if m else None,
          "txpower": (re.search(r"txpower (\S+)", iwi) or [None, None])[1],
          "regdom": reg[1].strip() if len(reg) > 1 else None,
          "power_save": sa.get("power_save"), "nm_profile": sa.get("nm_profile")}
    ok_d = wa.get("successfulTxPackets", 0) - wb.get("successfulTxPackets", 0)
    re_d = wa.get("retriedTxPackets", 0) - wb.get("retriedTxPackets", 0)
    have_counters = "retriedTxPackets" in wa and "retriedTxPackets" in wb
    ev_a, ev_b = health_after.get("evidence", {}), health_before.get("evidence", {})
    summary = {
        "schema": SCHEMA, "kind": kind, "label": label, "started": stamp, "wall_s": round(wall, 1),
        "ping": stats, "ap": ap,
        "client": {"serial": serial, "model": next((x["model"] for x in list_devices() if x["serial"] == serial), None),
                   "mac": mac, "ip": pf["path"]["tablet_ip"], "iface": pf["path"]["route_dev"]},
        "tablet": {"ip": pf["path"]["tablet_ip"], "iface": pf["path"]["route_dev"], "mac": mac,
                   "rssi_before": wb.get("rssi_dbm"), "rssi_after": wa.get("rssi_dbm"),
                   "tx_link_mbps_before": wb.get("tx_link_mbps"), "tx_link_mbps_after": wa.get("tx_link_mbps"),
                   "rx_link_mbps_after": wa.get("rx_link_mbps"), "freq_mhz": wa.get("freq_mhz"),
                   "retry_counters_available": have_counters,
                   "tx_success_delta": ok_d, "tx_retries_delta": re_d,
                   "tx_retry_ratio": round(re_d / max(ok_d, 1), 2) if have_counters else None,
                   "tx_lost_delta": wa.get("lostTxPackets", 0) - wb.get("lostTxPackets", 0),
                   "tx_retries_cumulative": wa.get("retriedTxPackets"),
                   "tx_success_cumulative": wa.get("successfulTxPackets")},
        "pi_view_of_tablet": {"before": stb.get(mac), "after": sta.get(mac),
                              "tx_failed_delta": sta.get(mac, {}).get("tx failed", 0) - stb.get(mac, {}).get("tx failed", 0),
                              "note": "brcmfmac AP mode exposes only 'tx failed', no retry or utilisation counters"},
        "pi": {"identity": {"host": ev_a.get("host"), "model": ev_a.get("model"), "serial_tail": ev_a.get("serial_tail")},
               "health_before": health_before.get("state"), "health_after": health_after.get("state"),
               "health_reasons": sorted(set(health_before.get("reasons", []) + health_after.get("reasons", []))),
               "temp_c_before": ev_b.get("temp_c"), "temp_c_after": ev_a.get("temp_c"),
               "load_before": ev_b.get("load"), "load_after": ev_a.get("load"),
               "mem_available_pct": ev_a.get("mem_available_pct"),
               "throttled": (ev_a.get("throttled") or {}).get("raw"),
               "associated_stations": len(sta), "other_stations": [k for k in sta if k != mac],
               "channel_utilization": sa["survey"][:400] if sa.get("survey") else
               "unavailable (brcmfmac AP-mode survey dump is empty)"},
        "traffic": traffic_res, "meta": extra_meta or {},
    }
    (d / "summary.json").write_text(json.dumps(summary, indent=2))
    (d / "summary.txt").write_text(render_summary(summary))
    if not quiet:
        print((d / "summary.txt").read_text())
    return d, summary


def render_summary(s):
    p, t, a, q, c = s["ping"], s["tablet"], s["ap"], s["pi"], s["client"]
    L = [f"{s['kind']} / {s['label']}  ({s['started']})  client {c['serial']} {c.get('model') or ''}",
         f"AP: {a['ssid']} {a['band']} ch{a['channel']} {a['width_mhz']}MHz txpower {a['txpower']} reg {a['regdom']}",
         f"Client: {t['ip']} on {t['iface']}  RSSI {t['rssi_before']}->{t['rssi_after']} dBm  "
         f"tx {t['tx_link_mbps_after']} / rx {t['rx_link_mbps_after']} Mbps",
         f"Ping: sent {p['sent']} recv {p['received']} loss {p['loss_pct']}%  min/avg/p50/p95/p99/max = "
         f"{p.get('min_ms')}/{p.get('avg_ms')}/{p.get('p50_ms')}/{p.get('p95_ms')}/{p.get('p99_ms')}/{p.get('max_ms')} ms",
         f"  stdev {p.get('stdev_ms')} ms  mean|dRTT| {p.get('jitter_mean_abs_delta_ms')} ms  spikes {p.get('spikes')}"
         f"  longest loss burst {p.get('longest_loss_burst')}",
         f"Client TX: ok {t['tx_success_delta']} retries {t['tx_retries_delta']} (ratio {t['tx_retry_ratio']}) "
         f"lost {t['tx_lost_delta']}; Pi tx_failed delta {s['pi_view_of_tablet']['tx_failed_delta']}",
         f"Pi {q['identity'].get('host')}: health {q['health_before']}->{q['health_after']}  temp {q['temp_c_after']} C  "
         f"load {q['load_after']}  stations {q['associated_stations']}  throttled {q['throttled']}"]
    if q["health_reasons"]:
        L.append("Health reasons: " + "; ".join(q["health_reasons"]))
    if s.get("traffic"):
        L.append(f"Traffic: {s['traffic']}")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- AP control (restricted helper only)
HELPER_HINT = ("the restricted helper is not usable over ssh+sudo. The owner installs it once: "
               "`sudo bash ops/ap-control/install-ap-control.sh --user <ssh user>` on the Pi (AVR-298).")


def ap_helper(*args, timeout=90):
    """Call the fixed-allow-list helper through `sudo -n`. Returns its JSON document; raises on refusal."""
    remote = "sudo -n " + CFG["ap_helper_path"] + " " + " ".join(args)
    rc, out, err = run(ssh_cmd(remote), timeout)
    doc = None
    for line in reversed(out.strip().splitlines()):
        if line.startswith("{"):
            try:
                doc = json.loads(line)
                break
            except ValueError:
                pass
    if doc is None:
        raise RuntimeError(f"AP helper failed (rc={rc}): {err.strip() or out.strip()}. {HELPER_HINT}")
    if not doc.get("ok"):
        raise RuntimeError(f"AP helper refused: {doc.get('error')}")
    return doc


def wait_rejoin(max_wait=180):
    """Wait until the client is back on the Avrana SSID with a valid route. Recovers a client that roamed
    to another saved network by toggling its Wi-Fi (never edits or forgets saved networks)."""
    events, toggled = [], 0
    for i in range(max_wait // 3):
        time.sleep(3)
        try:
            tab = tablet_snapshot()
            w, v = parse_cmd_wifi_status(tab["cmd_wifi_status"]), verify_path(tab)
            if w.get("ssid") == CFG["ap_ssid"] and not v["problems"] \
                    and " 0% packet loss" in adb_shell(f"ping -c 2 -W 2 {CFG['ap_ip']}", timeout=20):
                return {"rejoined_after_s": (i + 1) * 3, "freq_mhz": w.get("freq_mhz"),
                        "channel": freq_to_chan(w.get("freq_mhz")), "ip": v["tablet_ip"], "events": events}
            if w.get("ssid") and w["ssid"] != CFG["ap_ssid"] and i >= 3 and toggled < 3:
                events.append(f"roamed to {w['ssid']!r}; toggling client Wi-Fi to rejoin")
                adb_shell("cmd wifi set-wifi-enabled disabled")
                time.sleep(3)
                adb_shell("cmd wifi set-wifi-enabled enabled")
                toggled += 1
        except Exception as e:
            events.append(f"poll error: {e}")
    raise RuntimeError(f"client did not rejoin {CFG['ap_ssid']!r} within {max_wait}s; events: {events}")


def require_only_own_client():
    """Tool-side guard beside the helper's: the only associated station must be this client.
    `--lab` tells the helper "the associated station is mine"; this check makes that true."""
    mac = tablet_snapshot()["mac"].lower()
    others = [m for m in parse_station_dump(parse_sections(pi_snapshot()).get("stations", "")) if m.lower() != mac]
    if others:
        raise TrialRefused(f"{len(others)} other station(s) are associated; a channel change would disconnect them. "
                           "Never change channels while people are connected.")


def cmd_ap(args):
    if args.action == "show":
        print(json.dumps(ap_helper("show"), indent=2))
        return
    if not args.lab:
        sys.exit("ap set/restore disconnects every client: pass --lab to confirm the only associated device is your own test client")
    require_only_own_client()
    if args.action == "restore":
        print(json.dumps(ap_helper("restore", "--lab"), indent=2))
    else:
        if not args.channel:
            sys.exit("ap set needs --channel N")
        print(json.dumps(ap_helper("set-channel", str(int(args.channel)), "--lab"), indent=2))
    print("waiting for the client to rejoin ...")
    print(json.dumps(wait_rejoin(), indent=2))


DIRTY = RESULTS / ".ap-dirty.json"


def cmd_ap_recover(args):
    if not DIRTY.exists():
        print("no interrupted qualification recorded")
        return
    if not args.lab:
        sys.exit("ap-recover disconnects every client: pass --lab to confirm the only associated device is your own test client")
    require_only_own_client()
    info = json.loads(DIRTY.read_text())
    print(f"recovering: qualification started {info['started']} left the AP at channel {info.get('current')}")
    ap_helper("set-channel", str(CFG["default_channel"]), "--lab")
    print(json.dumps(wait_rejoin(), indent=2))
    DIRTY.unlink()


# ---------------------------------------------------------------- CLI
def for_each_device(args, fn):
    """Run fn once per selected device (--device SERIAL, --all-devices, or the single attached one)."""
    if getattr(args, "all_devices", False):
        ready = [d for d in list_devices() if d["state"] == "device"]
        if not ready:
            sys.exit("no authorized adb device")
        for d in ready:
            CFG["android_serial"] = d["serial"]
            print(f"=== device {d['serial']} {d['model'] or ''}")
            fn()
    else:
        pick_device(CFG.get("android_serial"))
        fn()


def main():
    import gate, health_cmd, loadtest, multi, qualify, report
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", action="append", help="override config key=value (JSON values), e.g. expect_channel=36")
    ap.add_argument("--device", help="adb serial of the Android client to use")
    ap.add_argument("--all-devices", action="store_true", help="run once per authorised attached device, results kept per client")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preflight", help="check adb, Wi-Fi path, SSH; no test")
    for name in ("baseline", "idle"):
        p = sub.add_parser(name, help="idle latency baseline (ping from the client to the AP)")
        p.add_argument("--label", default="baseline")
        p.add_argument("--trials", type=int, default=1)
        p.add_argument("--count", type=int)
        p.add_argument("--interval", type=float)
    p = sub.add_parser("ap", help="show/set/restore the AP channel via the restricted helper")
    p.add_argument("action", choices=["show", "set", "restore"])
    p.add_argument("--channel")
    p.add_argument("--lab", action="store_true", help="required for set/restore: the only associated device is your own")
    p = sub.add_parser("ap-recover", help="restore the default channel after an interrupted qualification")
    p.add_argument("--lab", action="store_true", help="required: the only associated device is your own")
    for mod in (health_cmd, gate, loadtest, qualify, multi, report):
        mod.register(sub)
    args = ap.parse_args()
    load_cfg(args.set)
    if args.device:
        CFG["android_serial"] = args.device
    wl = sys.modules[__name__]
    try:
        dispatch(args, wl)
    except TrialRefused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        sys.exit(2)


def dispatch(args, wl):
    if args.cmd == "preflight":
        pick_device(CFG.get("android_serial"))
        print(json.dumps(preflight(), indent=2))
    elif args.cmd in ("baseline", "idle"):
        def go():
            for i in range(args.trials):
                run_trial("idle", args.label, args.count or CFG["ping_count"], args.interval or CFG["ping_interval_s"], {"trial": i + 1})
                if i + 1 < args.trials:
                    time.sleep(10)
        for_each_device(args, go)
    elif args.cmd == "ap":
        pick_device(CFG.get("android_serial"))
        cmd_ap(args)
    elif args.cmd == "ap-recover":
        pick_device(CFG.get("android_serial"))
        cmd_ap_recover(args)
    else:
        args.func(args, wl)


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
