"""`multi`: Avrana-like multi-client latency steps (1, 2, 4, 6, 8, 10 clients).

Not a throughput benchmark. Each client sends small frequent messages and records RTT, loss, reconnects.
Two client kinds, never mixed up in the reports:

  real       an attached Android device pinging the AP over its own Wi-Fi (ICMP) with its retry counters;
             the only kind that exercises a real Wi-Fi client.
  synthetic  a TCP echo client run on THIS machine (20 Hz, 64 B), closer to Party/game traffic (head-of-line
             blocking, reconnects) but carried by whatever interface this machine uses. It is labelled with
             its path: `avrana-subnet` (this machine is itself a client of the AP) or `other-path` (it
             does NOT exercise the AP's radio; it only loads the Pi CPU/RAM and the application side).
             A synthetic client is never evidence about Wi-Fi clients.

At each step K the first min(K, #real devices) real devices run, the rest are synthetic. Pi health,
temperature, load and memory are recorded before and after each step.
"""
import datetime as dt, json, math, socket, statistics, subprocess, sys, threading, time

ECHO_SERVER = r"""
import socket, sys, threading, time
port, dur = int(sys.argv[1]), float(sys.argv[2])
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", port)); srv.listen(64); srv.settimeout(1.0)
end = time.time() + dur
def h(c):
    c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        while True:
            d = c.recv(4096)
            if not d: break
            c.sendall(d)
    except OSError: pass
    finally: c.close()
while time.time() < end:
    try: c, _ = srv.accept()
    except socket.timeout: continue
    threading.Thread(target=h, args=(c,), daemon=True).start()
"""


# ------------------------------------------------------------------ pure helpers (unit-tested)
def rtt_stats(rtts, sent, reconnects=0):
    """rtts: list of ms for answered messages; sent: messages sent. Loss = unanswered."""
    out = {"sent": sent, "received": len(rtts), "loss_pct": round(100.0 * (sent - len(rtts)) / sent, 2) if sent else None,
           "reconnects": reconnects}
    if rtts:
        s = sorted(rtts)

        def pct(p):
            k = (len(s) - 1) * p / 100.0
            f, c = math.floor(k), math.ceil(k)
            return s[f] + (s[c] - s[f]) * (k - f)
        out.update(min_ms=round(s[0], 2), p50_ms=round(pct(50), 2), p95_ms=round(pct(95), 2), p99_ms=round(pct(99), 2),
                   max_ms=round(s[-1], 2), stdev_ms=round(statistics.pstdev(s), 2))
    return out


def path_kind(local_ip, subnet_prefix):
    return "avrana-subnet" if (local_ip or "").startswith(subnet_prefix) else "other-path"


def aggregate(client_stats):
    """Per-step aggregate across clients (of any kind), keeping kinds separate in the counts."""
    real = [c for c in client_stats if c["kind"] == "real"]
    syn = [c for c in client_stats if c["kind"] == "synthetic"]
    worst = lambda key: max((c["stats"].get(key) for c in client_stats if c["stats"].get(key) is not None), default=None)
    return {"clients": len(client_stats), "real": len(real), "synthetic": len(syn),
            "worst_p99_ms": worst("p99_ms"), "worst_loss_pct": worst("loss_pct"),
            "total_reconnects": sum(c["stats"].get("reconnects", 0) for c in client_stats),
            "real_only_worst_p99_ms": max((c["stats"].get("p99_ms") for c in real if c["stats"].get("p99_ms") is not None), default=None)}


# ------------------------------------------------------------------ clients
def local_ip_for(host, port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((host, port))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def synthetic_client(idx, host, port, seconds, hz, reply_timeout, out):
    rtts, sent, reconnects, errors = [], 0, 0, []
    end = time.time() + seconds
    sock = None
    buf = b""
    while time.time() < end:
        t0 = time.perf_counter()
        try:
            if sock is None:
                sock = socket.create_connection((host, port), timeout=3)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(reply_timeout)
                buf = b""
            sent += 1
            msg = (f"{idx}:{sent}:".encode()).ljust(63, b"x") + b"\n"
            t_send = time.perf_counter()
            sock.sendall(msg)
            while b"\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("closed by peer")
                buf += chunk
            line, _, buf = buf.partition(b"\n")
            if line.startswith(f"{idx}:{sent}:".encode()):
                rtts.append((time.perf_counter() - t_send) * 1000.0)
        except socket.timeout:
            buf = b""  # an unanswered message counts as lost; keep the connection
        except OSError as e:
            errors.append(repr(e))
            reconnects += 1 if sock is not None else 0
            try:
                if sock:
                    sock.close()
            except OSError:
                pass
            sock = None
            time.sleep(0.5)
        time.sleep(max(0.0, 1.0 / hz - (time.perf_counter() - t0)))
    if sock is not None:
        try:
            sock.close()
        except OSError:
            pass
    out.append({"kind": "synthetic", "id": f"syn{idx}", "stats": rtt_stats(rtts, sent, reconnects), "errors": errors[:5]})


def real_client(wl, dev, seconds, interval, out):
    serial = dev["serial"]
    base = [wl.find_adb(), "-s", serial]
    st0 = wl.parse_cmd_wifi_status(wl.run(base + ["exec-out", "cmd wifi status"], 20)[1])
    count = int(seconds / interval)
    rc, raw, err = wl.run(base + ["exec-out", f"ping -c {count} -i {interval} -W 2 -s 56 {wl.CFG['ap_ip']}"], seconds + 60)
    st1 = wl.parse_cmd_wifi_status(wl.run(base + ["exec-out", "cmd wifi status"], 20)[1])
    stats, rtts = wl.parse_ping(raw, sent=count)
    ok_d = st1.get("successfulTxPackets", 0) - st0.get("successfulTxPackets", 0)
    re_d = st1.get("retriedTxPackets", 0) - st0.get("retriedTxPackets", 0)
    stats["reconnects"] = 0 if st1.get("ssid") == st0.get("ssid") else 1
    out.append({"kind": "real", "id": serial, "model": dev.get("model"), "stats": stats,
                "rssi_dbm": st1.get("rssi_dbm"), "tx_link_mbps": st1.get("tx_link_mbps"),
                "tx_retry_ratio": round(re_d / max(ok_d, 1), 2) if "retriedTxPackets" in st1 else None,
                "tx_success_delta": ok_d, "tx_retries_delta": re_d, "error": err if rc != 0 else None})


# ------------------------------------------------------------------ command
def run_multi(args, wl):
    mcfg = wl.CFG["multi"]
    counts = [int(c) for c in (args.counts.split(",") if args.counts else mcfg["counts"])]
    seconds = args.seconds or mcfg["step_seconds"]
    ready = [d for d in wl.list_devices() if d["state"] == "device"]
    if args.devices:
        want = args.devices.split(",")
        ready = [d for d in ready if d["serial"] in want]
    if args.synthetic_only:
        ready = []
    target = args.target or wl.CFG["ap_ip"]
    port = mcfg["echo_port"]
    local_ip = local_ip_for(target, port)
    kind_of_path = path_kind(local_ip, wl.CFG["ap_subnet_prefix"])
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    parent = wl.RESULTS / f"{stamp}_multi_{args.label}"
    parent.mkdir(parents=True)
    print(f"real devices: {[d['serial'] for d in ready] or 'none'}; synthetic path from this machine: {kind_of_path} "
          f"(local {local_ip} -> {target}). Synthetic clients are NOT Wi-Fi clients unless the path is avrana-subnet.")
    h0 = wl.pi_health()
    steps = []
    need_synth = any(k > len(ready) for k in counts)
    echo = None
    if need_synth:
        total = int(max(counts) and sum(seconds + 20 for _ in counts) + 30)
        echo = subprocess.Popen(wl.ssh_cmd(f"python3 - {port} {total}"), stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        echo.stdin.write(ECHO_SERVER.encode())
        echo.stdin.close()
        time.sleep(3)
    try:
        for k in counts:
            real, nsyn = ready[:k], max(0, k - len(ready))
            before = wl.pi_health()
            out, threads = [], []
            for dev in real:
                threads.append(threading.Thread(target=real_client, args=(wl, dev, seconds, wl.CFG["ping_interval_s"], out)))
            for i in range(nsyn):
                threads.append(threading.Thread(target=synthetic_client,
                                                args=(i + 1, target, port, seconds, mcfg["send_hz"], mcfg["reply_timeout_s"], out)))
            t0 = time.time()
            for t in threads:
                t.start()
            for t in threads:
                t.join(seconds + 90)
            after = wl.pi_health()
            ev = after.get("evidence", {})
            step = {"clients_requested": k, "real": len(real), "synthetic": nsyn, "seconds": round(time.time() - t0, 1),
                    "clients": out, "aggregate": aggregate(out),
                    "pi": {"health_before": before.get("state"), "health_after": after.get("state"),
                           "reasons": sorted(set(before.get("reasons", []) + after.get("reasons", []))),
                           "temp_c": ev.get("temp_c"), "load": ev.get("load"), "mem_available_pct": ev.get("mem_available_pct")}}
            steps.append(step)
            a = step["aggregate"]
            print(f"K={k}: real {a['real']} synthetic {a['synthetic']}  worst p99 {a['worst_p99_ms']} ms  "
                  f"worst loss {a['worst_loss_pct']}%  reconnects {a['total_reconnects']}  Pi {step['pi']['health_after']} "
                  f"load {step['pi']['load']} temp {step['pi']['temp_c']}")
            (parent / "multi.json").write_text(json.dumps({"steps": steps}, indent=2))
            time.sleep(5)
    finally:
        if echo:
            echo.terminate()
    doc = {"schema": "avrana.wifi-multi/v1", "started": stamp, "label": args.label, "synthetic_path": kind_of_path,
           "synthetic_local_ip": local_ip, "target": target, "pi_health_start": h0.get("state"), "steps": steps,
           "warning": "synthetic clients are not Wi-Fi clients unless synthetic_path == 'avrana-subnet'; "
                      "capacity claims must come from real-device steps only"}
    (parent / "multi.json").write_text(json.dumps(doc, indent=2))
    print(f"saved {parent}")


def register(sub):
    p = sub.add_parser("multi", help="multi-client latency steps: real Android devices + labelled synthetic TCP clients")
    p.add_argument("--counts", help="comma list of client counts (default config multi.counts)")
    p.add_argument("--seconds", type=int)
    p.add_argument("--devices", help="comma list of adb serials to use as real clients (default: all attached)")
    p.add_argument("--synthetic-only", action="store_true")
    p.add_argument("--target", help="echo/ping target (default the AP address)")
    p.add_argument("--label", default="multi")
    p.set_defaults(func=run_multi)
