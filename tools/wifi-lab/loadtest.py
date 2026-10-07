"""Loaded-latency module for wifilab.py: ping RTT/loss/retries while the radio carries controlled traffic.

No iperf3 binary is staged on the tablet (it is 32-bit armv7 Android 11, and there is no first-party
iperf3 Android build). Instead the load is generated with tools both ends already have:
  down-RATE  Pi -> tablet paced UDP (python3 on the Pi), received by toybox `nc -u -l` on the tablet
  down-max   Pi -> tablet TCP  (`dd | nc -l` on the Pi, `nc` client on the tablet)
  up-max     tablet -> Pi TCP  (`dd | nc` on the tablet, `nc -l` on the Pi)
Uplink is only available as max-effort TCP: toybox cannot pace. Throughput is measured from the
tablet's own wlan0 byte counters (/proc/net/dev), so it is what actually crossed the Wi-Fi link.
Limitation: this is a load generator, not a calibrated iperf3; compare runs to each other, not to iperf3.
"""
import re, subprocess, time

SENDER = r"""
import socket, sys, time
ip, rate, dur = sys.argv[1], float(sys.argv[2]) * 1e6 / 8, float(sys.argv[3])
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); b = b"x" * 1400
t0 = time.perf_counter(); sent = 0
while True:
    now = time.perf_counter() - t0
    if now > dur: break
    due = int(rate * now / 1400)
    while sent < due: s.sendto(b, (ip, 5201)); sent += 1
    time.sleep(0.001)
"""

SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]


def wlan_bytes(wl):
    iface = wl.CFG.get("tablet_iface", "wlan0")
    m = re.search(re.escape(iface) + r":\s*(\d+)\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+(\d+)", wl.adb_shell("cat /proc/net/dev"))
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2))  # rx, tx


class Traffic:
    def __init__(self, wl, mode, dur):
        self.wl, self.mode, self.dur = wl, mode, int(dur)

    def _adb_bg(self, cmd):
        serial = self.wl.CFG.get("android_serial")
        return subprocess.Popen([self.wl.find_adb()] + (["-s", serial] if serial else []) + ["exec-out", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def start(self):
        wl, ip, d = self.wl, self.wl.CFG["ap_ip"], self.dur
        host = wl.CFG["pi_ssh_host"]
        tab_ip = None
        procs = []
        if self.mode.startswith("down-") and self.mode != "down-max":
            rate = self.mode.split("-")[1].rstrip("M")
            tab_ip = re.search(r"src (\S+)", wl.adb_shell(f"ip route get {ip}")).group(1)
            procs.append(self._adb_bg(f"timeout {d + 5} nc -u -l -p 5201 > /dev/null"))
            time.sleep(1)
            p = subprocess.Popen(SSH + [host, f"python3 - {tab_ip} {rate} {d}"], stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            p.stdin.write(SENDER.encode()); p.stdin.close()
            procs.append(p)
        elif self.mode == "down-max":
            procs.append(subprocess.Popen(SSH + [host, f"timeout {d + 5} sh -c 'dd if=/dev/zero bs=64k 2>/dev/null | nc -l {ip} 5203'"],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            time.sleep(2)
            procs.append(self._adb_bg(f"timeout {d + 3} nc {ip} 5203 > /dev/null"))
        elif self.mode == "up-max":
            procs.append(subprocess.Popen(SSH + [host, f"timeout {d + 5} nc -l {ip} 5202 > /dev/null"],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            time.sleep(2)
            procs.append(self._adb_bg(f"timeout {d + 3} sh -c 'dd if=/dev/zero bs=64k 2>/dev/null | nc {ip} 5202'"))
        else:
            raise SystemExit(f"unknown load mode {self.mode}")
        time.sleep(4)  # let the flow ramp before the first measured ping
        return {"procs": procs, "t0": time.time(), "bytes0": wlan_bytes(wl)}

    def stop(self, h):
        b1, t1 = wlan_bytes(self.wl), time.time()
        for p in h["procs"]:
            p.terminate()
        # the remote side stops by itself via `timeout`; also clear any listener on the tablet
        self.wl.adb_shell(f"pkill -f 'nc -u -l' ; pkill -f 'nc {self.wl.CFG['ap_ip']}' ; true", timeout=15)
        dt = t1 - h["t0"]
        return {"mode": self.mode, "window_s": round(dt, 1),
                "tablet_rx_mbps": round((b1[0] - h["bytes0"][0]) * 8 / dt / 1e6, 2),
                "tablet_tx_mbps": round((b1[1] - h["bytes0"][1]) * 8 / dt / 1e6, 2),
                "note": "tablet wlan0 byte counters incl. ping/background"}


def register(sub):
    for name in ("loaded", "load"):
        _register_one(sub, name)


def _register_one(sub, name):
    p = sub.add_parser(name, help="loaded latency: ping while Pi<->client traffic runs")
    p.add_argument("--modes", default="down-5M,down-10M,down-20M,down-30M,down-50M,down-max,up-max",
                   help="comma list: down-<N>M (paced UDP), down-max, up-max")
    p.add_argument("--label", default="load")
    p.add_argument("--seconds", type=int, help="duration per level (default config load_duration_s)")
    p.set_defaults(func=run_load)


def run_load(args, wl):
    secs = args.seconds or wl.CFG["load_duration_s"]
    interval = wl.CFG["ping_interval_s"]
    count = int(secs / interval)

    def go():
        for mode in args.modes.split(","):
            wl.run_trial("load-" + mode, args.label, count, interval, {"mode": mode},
                         traffic=Traffic(wl, mode, count * interval + 12))
            time.sleep(8)
    wl.for_each_device(args, go)
