#!/usr/bin/env python3
"""Avrana Party - bounded Raspberry Pi network-hardware health check (observe only).

Prints one JSON object: {"state": ..., "reasons": [...], "notes": [...], "evidence": {...}}.
It never reboots, restarts or changes anything. Every external command has a hard time limit and a
command that exceeds it is abandoned (a process stuck in uninterruptible sleep cannot be killed, so
we never wait on one). It does not start another `vcgencmd` while an earlier one is still stuck.

States, highest priority first (see docs/runbooks/wifi-qualification.md for the exact table):
  FIRMWARE_MAILBOX_SUSPECT  `vcgencmd get_throttled` timed out, or a vcgencmd process is stuck in D state
  POWER_THROTTLE_DETECTED   get_throttled shows under-voltage / throttling / freq cap / soft temp limit NOW
  UNKNOWN                   the throttle state could not be read for a reason other than a hang
  DEGRADED                  something worth attention, none of the above (see reasons)
  HEALTHY                   everything observable is normal

Context: on 2026-10-06 the VideoCore mailbox wedged (kernel: "Firmware transaction ... timeout",
"hwmon: Failed to get throttled (-110)"), vcgencmd hung in D state and Wi-Fi throughput collapsed.
High load alone is NOT that failure: load is only attributed to it when D-state vcgencmd processes exist.
"""
import argparse, json, os, re, shutil, signal, socket, subprocess, sys, time

VCGENCMD_TIMEOUT = 5.0
JOURNAL_TIMEOUT = 10.0
TEMP_DEGRADED_C = 75.0
LOAD_PER_CORE_DEGRADED = 2.0
MEM_AVAILABLE_PCT_DEGRADED = 10.0

# kernel-log signatures (current boot)
MAILBOX_PATTERNS = [
    r"Firmware transaction .*timeout",
    r"Failed to get throttled",
    r"vchi message timeout",
    r"raspberrypi-clk .*Failed to set clock",
]
UNDERVOLT_PATTERN = r"[Uu]nder-?voltage detected"
# brcmfmac lines that are known-benign noise and must not degrade the state
BRCM_BENIGN = (r"txcap_blob", r"vndr ie set error")
BRCM_PATTERN = r"brcmf.*(error|fail|timeout|assert|halted)"


def run_bounded(cmd, timeout):
    """Return (returncode|None, stdout, error). On timeout kill the group and do NOT wait for it."""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True)
    except OSError as e:
        return None, "", f"cannot start: {e}"
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, "" if p.returncode == 0 else (err.strip() or f"rc={p.returncode}")
    except subprocess.TimeoutExpired:
        try:
            if hasattr(os, "killpg"):
                os.killpg(p.pid, signal.SIGKILL)
            else:  # not on the Pi; keeps the unit tests runnable on other platforms
                p.kill()
        except OSError:
            pass
        return None, "", f"timeout after {timeout:g}s"


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def dstate_processes():
    """Processes in uninterruptible sleep: [{"pid", "comm"}]. Pure /proc reads, no external command."""
    found = []
    try:
        pids = [x for x in os.listdir("/proc") if x.isdigit()]
    except OSError:
        return found
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat") as f:
                data = f.read()
        except OSError:
            continue
        m = re.match(r"\d+ \((.*)\) (\S)", data)
        if m and m.group(2) == "D":
            found.append({"pid": int(pid), "comm": m.group(1)})
    return found


def scan_kernel_log(text):
    """Pure: count signature lines in kernel-log text."""
    mailbox, undervolt, brcm = [], [], []
    for line in text.splitlines():
        if any(re.search(p, line) for p in MAILBOX_PATTERNS):
            mailbox.append(line.strip()[:200])
        elif re.search(UNDERVOLT_PATTERN, line):
            undervolt.append(line.strip()[:200])
        elif re.search(BRCM_PATTERN, line) and not any(re.search(b, line) for b in BRCM_BENIGN):
            brcm.append(line.strip()[:200])
    return {"mailbox_count": len(mailbox), "mailbox_samples": mailbox[:5],
            "undervoltage_count": len(undervolt), "undervoltage_samples": undervolt[:3],
            "brcmfmac_warning_count": len(brcm), "brcmfmac_samples": brcm[:5]}


def parse_throttled(raw):
    m = re.search(r"0x[0-9a-fA-F]+", raw or "")
    return int(m.group(0), 16) if m else None


def collect():
    ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "host": socket.gethostname()}
    ev["model"] = (read("/proc/device-tree/model") or "").strip("\x00")
    serial = re.search(r"Serial\s*:\s*(\w+)", read("/proc/cpuinfo") or "")
    ev["serial_tail"] = serial.group(1)[-4:] if serial else None
    ev["uptime_s"] = float((read("/proc/uptime") or "0").split()[0])
    load = (read("/proc/loadavg") or "0 0 0").split()[:3]
    ev["load"] = [float(x) for x in load]
    ev["cores"] = os.cpu_count() or 1
    t = read("/sys/class/thermal/thermal_zone0/temp")
    ev["temp_c"] = int(t) / 1000.0 if t and t.lstrip("-").isdigit() else None
    mem = {k: int(v) for k, v in re.findall(r"(\w+):\s+(\d+) kB", read("/proc/meminfo") or "")}
    ev["mem_available_pct"] = round(100.0 * mem.get("MemAvailable", 0) / mem["MemTotal"], 1) if mem.get("MemTotal") else None
    ev["swap_used_mb"] = round((mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) / 1024.0, 1)

    d = dstate_processes()
    ev["dstate"] = d
    stuck_vcg = [p for p in d if p["comm"] == "vcgencmd"]
    ev["stuck_vcgencmd"] = len(stuck_vcg)

    vcg = shutil.which("vcgencmd") or "/usr/bin/vcgencmd"
    if stuck_vcg:  # do not stack another one behind the stuck ones
        ev["throttled"] = {"error": f"skipped: {len(stuck_vcg)} vcgencmd already stuck in D state"}
    else:
        rc, out, err = run_bounded([vcg, "get_throttled"], VCGENCMD_TIMEOUT)
        bits = parse_throttled(out) if rc == 0 else None
        if bits is not None:
            ev["throttled"] = {"raw": f"0x{bits:x}", "bits": bits}
        else:
            ev["throttled"] = {"error": err or "unparseable output", "timeout": err.startswith("timeout")}
        # a vcgencmd that timed out may now be in D state; count it in this very run
        time.sleep(0.2)
        ev["stuck_vcgencmd"] = len([p for p in dstate_processes() if p["comm"] == "vcgencmd"])

    hw = None
    for h in sorted(os.listdir("/sys/class/hwmon")) if os.path.isdir("/sys/class/hwmon") else []:
        if read(f"/sys/class/hwmon/{h}/name") == "rpi_volt":
            hw = read(f"/sys/class/hwmon/{h}/in0_lcrit_alarm")
    ev["hwmon_undervolt_alarm"] = hw

    rc, out, err = run_bounded(["journalctl", "-k", "-b", "--no-pager", "-n", "4000"], JOURNAL_TIMEOUT)
    if rc != 0:
        rc, out, err = run_bounded(["dmesg"], JOURNAL_TIMEOUT)
    if rc == 0:
        ev["kernel"] = scan_kernel_log(out)
    else:
        ev["kernel"] = {"error": err}
    rc, out, err = run_bounded(["ps", "-eo", "pcpu,comm", "--sort=-pcpu"], 3)
    ev["top_cpu"] = out.splitlines()[1:5] if rc == 0 else []
    return ev


def classify(ev):
    """Pure: evidence dict -> {"state", "reasons", "notes"}. Documented in the runbook."""
    reasons, notes = [], []
    thr = ev.get("throttled", {})
    stuck = ev.get("stuck_vcgencmd", 0)
    kernel = ev.get("kernel", {})
    mailbox_logged = kernel.get("mailbox_count", 0)

    if thr.get("timeout"):
        reasons.append(f"vcgencmd get_throttled did not answer ({thr['error']})")
    if stuck:
        reasons.append(f"{stuck} vcgencmd process(es) stuck in uninterruptible sleep")
    if reasons:
        if mailbox_logged:
            reasons.append(f"kernel logged {mailbox_logged} firmware-mailbox error line(s) this boot")
        return {"state": "FIRMWARE_MAILBOX_SUSPECT", "reasons": reasons, "notes": notes}

    bits = thr.get("bits")
    if bits is not None:
        now = []
        if bits & 0x1: now.append("under-voltage right now")
        if bits & 0x2: now.append("ARM frequency capped right now")
        if bits & 0x4: now.append("throttled right now")
        if bits & 0x8: now.append("soft temperature limit active right now")
        if now:
            return {"state": "POWER_THROTTLE_DETECTED", "reasons": now + [f"get_throttled={thr['raw']}"], "notes": notes}
    else:
        reasons.append(f"throttle state unavailable: {thr.get('error', 'not read')}")
        return {"state": "UNKNOWN", "reasons": reasons, "notes": notes}

    if bits & 0x10000: reasons.append("under-voltage has occurred since boot (sticky bit)")
    if bits & 0x20000: reasons.append("ARM frequency capping has occurred since boot (sticky bit)")
    if bits & 0x40000: reasons.append("throttling has occurred since boot (sticky bit)")
    if bits & 0x80000: reasons.append("soft temperature limit has occurred since boot (sticky bit)")
    if kernel.get("undervoltage_count"):
        reasons.append(f"kernel logged {kernel['undervoltage_count']} under-voltage line(s) this boot")
    if mailbox_logged:
        reasons.append(f"kernel logged {mailbox_logged} firmware-mailbox error line(s) earlier this boot; "
                       "vcgencmd answers now (intermittent or recovered)")
    if kernel.get("brcmfmac_warning_count"):
        reasons.append(f"{kernel['brcmfmac_warning_count']} brcmfmac warning line(s) this boot")
    if "error" in kernel:
        reasons.append(f"kernel log unreadable: {kernel['error']}")
    temp = ev.get("temp_c")
    if temp is not None and temp >= TEMP_DEGRADED_C:
        reasons.append(f"CPU temperature {temp:.1f} C (>= {TEMP_DEGRADED_C:g})")
    d = [p for p in ev.get("dstate", []) if p["comm"] != "vcgencmd"]
    if d:
        reasons.append("process(es) in uninterruptible sleep, not vcgencmd (I/O, not attributed to the mailbox): "
                       + ", ".join(sorted({p["comm"] for p in d})))
    load1, cores = (ev.get("load") or [0])[0], ev.get("cores", 1)
    if load1 > LOAD_PER_CORE_DEGRADED * cores:
        if ev.get("dstate"):
            reasons.append(f"load {load1:.2f} on {cores} cores with processes in D state")
        else:
            reasons.append(f"load {load1:.2f} on {cores} cores, CPU-bound (no D-state processes: not the mailbox signature)")
    mem = ev.get("mem_available_pct")
    if mem is not None and mem < MEM_AVAILABLE_PCT_DEGRADED:
        reasons.append(f"only {mem}% memory available")
    return {"state": "DEGRADED" if reasons else "HEALTHY", "reasons": reasons, "notes": notes}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state-file", help="also write the JSON here atomically (e.g. /run/avrana/pi-health.json)")
    ap.add_argument("--journal", action="store_true", help="print one summary line (for journald) instead of JSON")
    ap.add_argument("--exit-code", action="store_true", help="exit 0 healthy, 1 degraded, 2 suspect/power, 3 unknown")
    args = ap.parse_args()
    ev = collect()
    res = classify(ev)
    doc = {"schema": "avrana.pi-health/v0", **res, "evidence": ev}
    text = json.dumps(doc, sort_keys=True)
    if args.state_file:
        tmp = args.state_file + ".tmp"
        with open(tmp, "w") as f:
            f.write(text + "\n")
        os.replace(tmp, args.state_file)
    if args.journal:
        print(f"avrana-pi-health state={res['state']} reasons={'; '.join(res['reasons']) or '-'}", flush=True)
    else:
        print(text, flush=True)
    if args.exit_code:
        sys.exit({"HEALTHY": 0, "DEGRADED": 1, "FIRMWARE_MAILBOX_SUSPECT": 2, "POWER_THROTTLE_DETECTED": 2}.get(res["state"], 3))


if __name__ == "__main__":
    main()
