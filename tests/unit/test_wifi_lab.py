"""Wi-Fi lab (AVR-296): parsers, Pi health classification, gate, ranking, AP helper validation.

Tier 1 only: nothing here touches a device, the network or the Pi. The Pi health script and the AP
helper are imported from their files and exercised through their pure functions; the one test that
shells out runs `bash` against the installer's `--print-sudoers` (skipped where bash is absent).
"""
import importlib.machinery
import importlib.util
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
LAB = REPO / "tools" / "wifi-lab"
sys.path.insert(0, str(LAB))

import gate  # noqa: E402
import multi  # noqa: E402
import qualify  # noqa: E402
import report  # noqa: E402
import wifilab  # noqa: E402


def load_script(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


health = load_script("pi_health_check", REPO / "telemetry" / "pi-health-check.py")
helper = load_script("avrana_ap_control", REPO / "ops" / "ap-control" / "avrana-ap-control")
wifilab.CFG.update(json.loads((LAB / "config.json").read_text()))


def ping_text(rows):
    return "\n".join(f"64 bytes from 10.42.0.1: icmp_seq={s} ttl=64 time={v} ms" for s, v in rows)


class Parsers(unittest.TestCase):
    def test_ping_loss_and_percentiles(self):
        s, _ = wifilab.parse_ping(ping_text([(1, 10.0), (2, 20.0), (4, 120.0), (5, 10.0)]), sent=5)
        self.assertEqual((s["sent"], s["received"], s["loss_pct"], s["longest_loss_burst"]), (5, 4, 20.0, 1))
        self.assertEqual((s["min_ms"], s["max_ms"], s["p50_ms"]), (10.0, 120.0, 15.0))

    def test_ping_no_replies(self):
        s, _ = wifilab.parse_ping("", sent=10)
        self.assertEqual((s["received"], s["loss_pct"]), (0, 100.0))

    def test_station_and_status(self):
        d = wifilab.parse_station_dump("Station aa:bb:cc:dd:ee:ff (on wlan0)\n\ttx failed:\t6\n\ttx bitrate:\t78.0 MBit/s\n")
        self.assertEqual(d["aa:bb:cc:dd:ee:ff"]["tx failed"], 6)
        t = ('Wifi is connected to "X"\nWifiInfo: RSSI: -54, Link speed: 72Mbps, Tx Link speed: 72Mbps, '
             'Max Supported Tx Link speed: 72Mbps, Rx Link speed: 6Mbps, Max Supported Rx Link speed: 72Mbps, '
             'Frequency: 5745MHz\nretriedTxPackets: 12\n')
        w = wifilab.parse_cmd_wifi_status(t)
        self.assertEqual((w["rssi_dbm"], w["retriedTxPackets"], w["freq_mhz"], w["ssid"]), (-54, 12, 5745, "X"))

    def test_scan_results(self):
        t = ("    BSSID              Frequency      RSSI           Age(sec)     SSID                                 Flags\n"
             "  aa:bb:cc:00:11:22       5180        -41              7.407    Avrana Party                      [WPA2][ESS]\n")
        rows = wifilab.parse_scan_results(t)
        self.assertEqual((rows[0]["freq"], rows[0]["rssi"], rows[0]["ssid"]), (5180, -41, "Avrana Party"))

    def test_health_json_tolerates_banner(self):
        doc = wifilab.parse_health_json('Warning: Permanently added host\n{"state": "HEALTHY", "reasons": []}\n')
        self.assertEqual(doc["state"], "HEALTHY")
        self.assertIsNone(wifilab.parse_health_json("garbage"))

    def test_path_verification_rejects_usb_tethering(self):
        tab = {"ip_addr": "2: wlan0: <UP>\n    inet 10.42.0.51/24 scope global wlan0\n3: rndis0: <UP>\n    inet 192.168.42.129/24\n",
               "ip_route": "---\n10.42.0.1 dev wlan0 table 1002 src 10.42.0.51 uid 2000\n"}
        r = wifilab.verify_path(tab)
        self.assertTrue(any("other interfaces" in p for p in r["problems"]))
        tab["ip_route"] = "---\n10.42.0.1 dev rndis0 src 192.168.42.129\n"
        self.assertTrue(any("not a Wi-Fi interface" in p for p in wifilab.verify_path(tab)["problems"]))

    def test_run_is_bounded(self):
        t0 = time.time()
        rc, out, err = wifilab.run([sys.executable, "-c", "import time; time.sleep(20)"], 1)
        self.assertEqual(rc, 124)
        self.assertIn("timeout", err)
        self.assertLess(time.time() - t0, 10)

    def test_ambiguous_device_is_refused(self):
        devs = [{"serial": "A", "state": "device", "model": "x"}, {"serial": "B", "state": "device", "model": "y"}]
        with mock.patch.object(wifilab, "list_devices", return_value=devs):
            with self.assertRaises(SystemExit):
                wifilab.pick_device(None)
            self.assertEqual(wifilab.pick_device("B")["serial"], "B")
        with mock.patch.object(wifilab, "list_devices", return_value=[{"serial": "A", "state": "unauthorized", "model": None}]):
            with self.assertRaises(SystemExit):
                wifilab.pick_device("A")


class PiHealth(unittest.TestCase):
    base = {"throttled": {"raw": "0x0", "bits": 0}, "stuck_vcgencmd": 0, "dstate": [], "load": [0.1, 0.1, 0.1], "cores": 4,
            "temp_c": 40.0, "mem_available_pct": 80.0, "kernel": {"mailbox_count": 0, "undervoltage_count": 0, "brcmfmac_warning_count": 0}}

    def ev(self, **kw):
        e = json.loads(json.dumps(self.base))
        e.update(kw)
        return e

    def test_healthy(self):
        self.assertEqual(health.classify(self.ev())["state"], "HEALTHY")

    def test_vcgencmd_timeout_is_mailbox_suspect(self):
        r = health.classify(self.ev(throttled={"error": "timeout after 5s", "timeout": True}))
        self.assertEqual(r["state"], "FIRMWARE_MAILBOX_SUSPECT")

    def test_stuck_vcgencmd_is_mailbox_suspect(self):
        r = health.classify(self.ev(stuck_vcgencmd=2, dstate=[{"pid": 1, "comm": "vcgencmd"}] * 2,
                                    kernel={"mailbox_count": 3, "undervoltage_count": 0, "brcmfmac_warning_count": 0}))
        self.assertEqual(r["state"], "FIRMWARE_MAILBOX_SUSPECT")
        self.assertTrue(any("kernel logged 3" in x for x in r["reasons"]))

    def test_mailbox_errors_logged_but_responsive_is_only_degraded(self):
        r = health.classify(self.ev(kernel={"mailbox_count": 2, "undervoltage_count": 0, "brcmfmac_warning_count": 0}))
        self.assertEqual(r["state"], "DEGRADED")
        self.assertTrue(any("earlier this boot" in x for x in r["reasons"]))

    def test_power_now_vs_sticky(self):
        now = health.classify(self.ev(throttled={"raw": "0x50005", "bits": 0x50005}))
        self.assertEqual(now["state"], "POWER_THROTTLE_DETECTED")
        sticky = health.classify(self.ev(throttled={"raw": "0x50000", "bits": 0x50000}))
        self.assertEqual(sticky["state"], "DEGRADED")

    def test_high_load_alone_is_not_the_mailbox_failure(self):
        r = health.classify(self.ev(load=[9.0, 8.0, 7.0]))
        self.assertEqual(r["state"], "DEGRADED")
        self.assertTrue(any("not the mailbox signature" in x for x in r["reasons"]))

    def test_other_d_state_processes_are_not_attributed_to_the_mailbox(self):
        r = health.classify(self.ev(dstate=[{"pid": 9, "comm": "jbd2/mmcblk0p2"}]))
        self.assertEqual(r["state"], "DEGRADED")
        self.assertTrue(any("not vcgencmd" in x for x in r["reasons"]))

    def test_unreadable_throttle_without_hang_is_unknown(self):
        r = health.classify(self.ev(throttled={"error": "rc=255", "timeout": False}))
        self.assertEqual(r["state"], "UNKNOWN")

    def test_kernel_log_scan(self):
        text = "\n".join([
            "Oct 06 20:06:23 pi kernel: Firmware transaction 0x00030046 timeout",
            "Oct 06 20:06:24 pi kernel: hwmon hwmon1: Failed to get throttled (-110)",
            "Oct 06 20:06:33 pi kernel: bcm2835-audio bcm2835-audio: vchi message timeout, msg=5",
            "Oct 06 20:06:06 pi kernel: brcmfmac: brcmf_c_process_txcap_blob: no txcap_blob available (err=-2)",
            "Oct 06 21:20:13 pi kernel: ieee80211 phy0: brcmf_vif_set_mgmt_ie: vndr ie set error : -52",
            "Oct 06 21:21:00 pi kernel: brcmfmac: brcmf_sdio_bus_rxctl: resumed on timeout",
            "Oct 06 21:22:00 pi kernel: hwmon: Under-voltage detected!",
        ])
        k = health.scan_kernel_log(text)
        self.assertEqual((k["mailbox_count"], k["undervoltage_count"], k["brcmfmac_warning_count"]), (3, 1, 1))

    def test_run_bounded_abandons_a_hang_quickly(self):
        t0 = time.time()
        rc, out, err = health.run_bounded([sys.executable, "-c", "import time; time.sleep(30)"], 1.0)
        self.assertIsNone(rc)
        self.assertTrue(err.startswith("timeout"))
        self.assertLess(time.time() - t0, 10)
        self.assertEqual(health.run_bounded(["/nonexistent/vcgencmd"], 1)[2][:6], "cannot")

    def test_throttled_parse(self):
        self.assertEqual(health.parse_throttled("throttled=0x50005"), 0x50005)
        self.assertIsNone(health.parse_throttled("error"))


def summary(p95, p99, loss, retry, ok=500, rx=None, tx=None, counters=True):
    return {"kind": "idle", "ping": {"received": 100, "sent": 100, "loss_pct": loss, "p95_ms": p95, "p99_ms": p99},
            "tablet": {"tx_retry_ratio": retry, "tx_success_delta": ok, "tx_retries_delta": 10, "retry_counters_available": counters},
            "traffic": {"tablet_rx_mbps": rx, "tablet_tx_mbps": tx}}


class Gate(unittest.TestCase):
    cfg = json.loads((LAB / "config.json").read_text())["gate"]

    def levels(self, results):
        return {l for l, _ in results}

    def test_healthy_channel_36_numbers_pass(self):
        r = gate.evaluate_phase("idle", summary(38.7, 99.0, 0.0, 0.6), self.cfg["idle"], 20)
        self.assertEqual(gate.verdict(r), "PASS")
        r = gate.evaluate_phase("loaded", summary(120.0, 150.0, 0.0, 5.0, rx=20.4), self.cfg["loaded"], 20, 20)
        self.assertEqual(gate.verdict(r), "PASS")

    def test_channel_149_numbers_fail_on_retries(self):
        r = gate.evaluate_phase("idle", summary(65.0, 176.0, 0.0, 33.5), self.cfg["idle"], 20)
        self.assertEqual(gate.verdict(r), "FAIL")
        self.assertTrue(any("retry ratio" in t and l == "FAIL" for l, t in r))

    def test_retry_ratio_alone_is_only_a_warning(self):
        # observed 2026-10-07 on a clean channel 36: ratio 129 with perfect latency, loss and throughput
        r = gate.evaluate_phase("loaded", summary(61.8, 146.1, 0.0, 129.4, rx=20.45), self.cfg["loaded"], 20, 20)
        self.assertEqual(gate.verdict(r), "WARN")
        self.assertTrue(any("noisy client counter" in t for _, t in r))

    def test_retry_ratio_fails_when_corroborated(self):
        r = gate.evaluate_phase("idle", summary(65.0, 220.0, 0.0, 33.5), self.cfg["idle"], 20)  # p99 over warn too
        self.assertEqual(gate.verdict(r), "FAIL")
        r = gate.evaluate_phase("loaded", summary(100.0, 150.0, 0.0, 41.0, rx=1.7), self.cfg["loaded"], 20, 20)  # starved
        self.assertEqual(gate.verdict(r), "FAIL")

    def test_unavailable_metrics_never_pass_silently(self):
        r = gate.evaluate_phase("idle", summary(None, None, None, None, counters=False), self.cfg["idle"], 20)
        self.assertEqual(gate.verdict(r), "WARN")
        self.assertGreaterEqual(sum(1 for l, _ in r if l == "WARN"), 3)
        r = gate.evaluate_phase("loaded", summary(100.0, 100.0, 0.0, 1.0, rx=None), self.cfg["loaded"], 20, 20)
        self.assertTrue(any("throughput unavailable" in t for _, t in r))

    def test_no_replies_fails(self):
        s = summary(1, 1, 100.0, 1.0)
        s["ping"]["received"] = 0
        self.assertEqual(gate.verdict(gate.evaluate_phase("idle", s, self.cfg["idle"], 20)), "FAIL")

    def test_starved_delivery_fails(self):
        r = gate.evaluate_phase("loaded", summary(100.0, 100.0, 0.0, 1.0, rx=1.7), self.cfg["loaded"], 20, 20)
        self.assertTrue(any(l == "FAIL" and "delivered" in t for l, t in r))

    def test_health_mapping(self):
        docs = [("before", {"state": "HEALTHY"}), ("after", {"state": "DEGRADED", "reasons": ["x"]})]
        self.assertEqual(gate.verdict(gate.evaluate_health(docs)), "WARN")
        for bad in ("FIRMWARE_MAILBOX_SUSPECT", "POWER_THROTTLE_DETECTED", "UNKNOWN"):
            self.assertEqual(gate.verdict(gate.evaluate_health([("before", {"state": bad, "reasons": []})])), "FAIL")
        self.assertEqual(gate.verdict(gate.evaluate_health([("before", {})])), "FAIL")

    def test_render_lists_failures_first(self):
        text = gate.render("FAIL", [("PASS", "a ok"), ("FAIL", "b bad"), ("WARN", "c meh")])
        self.assertEqual(text.splitlines()[0], "FAIL")
        self.assertLess(text.index("b bad"), text.index("c meh"))
        self.assertLess(text.index("c meh"), text.index("a ok"))

    def test_thresholds_are_configuration_and_marked_provisional(self):
        self.assertIn("PROVISIONAL", self.cfg["_status"])
        for phase in ("idle", "loaded"):
            for k in ("p95_ms", "p99_ms", "loss_pct", "retry_ratio"):
                self.assertLess(self.cfg[phase][k]["warn"], self.cfg[phase][k]["fail"])


class Qualify(unittest.TestCase):
    def test_score_and_missing_metrics(self):
        best = {"idle_p99_ms": 0, "loaded_p99_ms": 0, "max_loss_pct": 0, "idle_retry_ratio": 0, "loaded_retry_ratio": 0, "uplink_mbps": 20}
        self.assertEqual(qualify.score(best), 100.0)
        self.assertEqual(qualify.score({}), 0.0)  # every missing metric takes its full penalty
        worse = dict(best, idle_p99_ms=300)
        self.assertEqual(qualify.score(worse), 75.0)

    def test_rank_orders_by_verdict_then_score_and_never_by_neighbours(self):
        recs = [{"channel": 149, "verdict": "FAIL", "score": 90.0, "neighbours_same_channel_info_only": 0},
                {"channel": 44, "verdict": "PASS", "score": 80.0, "neighbours_same_channel_info_only": 30},
                {"channel": 36, "verdict": "PASS", "score": 95.0, "neighbours_same_channel_info_only": 5},
                {"channel": 40, "verdict": "FAIL", "error": "boom", "score": None}]
        self.assertEqual([r["channel"] for r in qualify.rank(recs)], [36, 44, 149, 40])

    def test_metrics_from_summaries(self):
        idle = {"ping": {"p99_ms": 90.0, "loss_pct": 0.0}, "tablet": {"tx_retry_ratio": 0.6}}
        loaded = {"ping": {"p99_ms": 150.0, "loss_pct": 0.5}, "tablet": {"tx_retry_ratio": 5.0}, "traffic": {"tablet_rx_mbps": 20.0}}
        up = {"ping": {"loss_pct": 0.0}, "traffic": {"tablet_tx_mbps": 49.0}}
        m = qualify.metrics_from(idle, loaded, up)
        self.assertEqual((m["idle_p99_ms"], m["max_loss_pct"], m["uplink_mbps"]), (90.0, 0.5, 49.0))
        self.assertIsNone(qualify.metrics_from(None, None, None)["idle_p99_ms"])

    def test_uplink_thresholds(self):
        spec = {"warn": 15, "fail": 5}
        self.assertEqual(qualify.uplink_result(1.75, spec)[0], "FAIL")
        self.assertEqual(qualify.uplink_result(10, spec)[0], "WARN")
        self.assertEqual(qualify.uplink_result(49, spec)[0], "PASS")
        self.assertEqual(qualify.uplink_result(None, spec)[0], "WARN")


# format as printed by `iw phy phy0 info` on the Pi (frequencies carry a decimal)
PHY = """Band 2:
		Frequencies:
			* 5180.0 MHz [36] (20.0 dBm)
			* 5200.0 MHz [40] (20.0 dBm)
			* 5260.0 MHz [52] (20.0 dBm) (no IR, radar detection)
			* 5280.0 MHz [56] (20.0 dBm) (radar detection)
			* 5700.0 MHz [140] (disabled)
			* 5745.0 MHz [149] (20.0 dBm)
			* 5865.0 MHz [173] (no IR)
"""


class ApHelper(unittest.TestCase):
    def test_accepts_only_the_fixed_vectors(self):
        self.assertEqual(helper.parse_args(["show"]), ("show", None, False))
        self.assertEqual(helper.parse_args(["restore"]), ("restore", None, False))
        self.assertEqual(helper.parse_args(["set-channel", "36"]), ("set-channel", 36, False))
        self.assertEqual(helper.parse_args(["set-channel", "149", "--lab"]), ("set-channel", 149, True))

    def test_refuses_everything_else(self):
        bad = [[], ["show", "extra"], ["restore", "now"], ["set-channel"], ["set-channel", "13"], ["set-channel", "52"],
               ["set-channel", "36;reboot"], ["set-channel", "$(id)"], ["set-channel", "36", "--force"], ["set-channel", "36", "--lab", "x"],
               ["set-channel", "036"], ["set-channel", "-1"], ["set-channel", " 36"], ["nmcli", "connection", "down", "x"],
               ["--help"], ["set-channel", "36\n"], ["SHOW"], ["set-channel", "165"]]
        for argv in bad:
            with self.assertRaises(helper.Refused, msg=argv):
                helper.parse_args(argv)

    def test_regulatory_filter(self):
        self.assertTrue(helper.channel_allowed(PHY, 36))
        self.assertTrue(helper.channel_allowed(PHY, 149))
        for ch in (52, 56, 140, 173, 100):
            self.assertFalse(helper.channel_allowed(PHY, ch), ch)

    def test_approved_channels_are_non_dfs_5ghz(self):
        self.assertEqual(helper.APPROVED_CHANNELS, (36, 40, 44, 48, 149, 153, 157, 161))
        self.assertEqual(helper.PROFILE, "Avrana Party Internal")

    def test_party_session_refusal(self):
        with mock.patch.object(helper, "party_session_active", return_value=True):
            for call in (lambda: helper.cmd_set(40, True), helper.cmd_restore):
                with self.assertRaises(helper.Refused) as cm:
                    call()
                self.assertIn("Party session is active", str(cm.exception))

    def test_stations_block_unless_lab(self):
        with mock.patch.object(helper, "party_session_active", return_value=False), mock.patch.object(helper, "stations", return_value=2):
            with self.assertRaises(helper.Refused):
                helper.cmd_set(40, False)

    def test_helper_never_uses_a_shell(self):
        src = (REPO / "ops" / "ap-control" / "avrana-ap-control").read_text()
        self.assertNotIn("shell=True", src)
        self.assertNotIn("os.system", src)

    @unittest.skipUnless(shutil.which("bash"), "needs bash")
    def test_sudoers_rule_is_exact_and_has_no_wildcards(self):
        script = REPO / "ops" / "ap-control" / "install-ap-control.sh"
        p = subprocess.run(["bash", str(script).replace("\\", "/"), "--print-sudoers", "cody"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = p.stdout
        self.assertNotIn("*", out.replace("# Managed by", ""))
        self.assertIn("/usr/local/sbin/avrana-ap-control show", out)
        self.assertIn("/usr/local/sbin/avrana-ap-control restore", out)
        self.assertEqual(out.count("set-channel"), 16)
        self.assertNotIn("ALL=(ALL)", out)
        self.assertIn("cody ALL=(root) NOPASSWD: AVRANA_AP_CONTROL", out)
        bad = subprocess.run(["bash", str(script).replace("\\", "/"), "--print-sudoers", "x; rm -rf /"], capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)


class Multi(unittest.TestCase):
    def test_stats_and_labels(self):
        s = multi.rtt_stats([10.0, 20.0, 30.0], 4, reconnects=1)
        self.assertEqual((s["sent"], s["received"], s["loss_pct"], s["reconnects"], s["p50_ms"]), (4, 3, 25.0, 1, 20.0))
        self.assertEqual(multi.path_kind("10.42.0.46", "10.42.0.1".rsplit(".", 1)[0] + "."), "avrana-subnet")
        self.assertEqual(multi.path_kind("10.0.0.5", "10.42.0.1".rsplit(".", 1)[0] + "."), "other-path")
        agg = multi.aggregate([{"kind": "real", "stats": {"p99_ms": 50.0, "loss_pct": 0.0, "reconnects": 0}},
                               {"kind": "synthetic", "stats": {"p99_ms": 400.0, "loss_pct": 2.0, "reconnects": 3}}])
        self.assertEqual((agg["real"], agg["synthetic"], agg["worst_p99_ms"], agg["real_only_worst_p99_ms"], agg["total_reconnects"]),
                         (1, 1, 400.0, 50.0, 3))

    def test_synthetic_client_against_a_local_echo_server(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)
        port = srv.getsockname()[1]
        stop = threading.Event()

        def serve():
            srv.settimeout(0.5)
            while not stop.is_set():
                try:
                    c, _ = srv.accept()
                except socket.timeout:
                    continue
                c.settimeout(0.5)
                try:
                    while not stop.is_set():
                        d = c.recv(4096)
                        if not d:
                            break
                        c.sendall(d)
                except OSError:
                    pass
                c.close()
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        out = []
        multi.synthetic_client(1, "127.0.0.1", port, 1.5, 20, 1.0, out)
        stop.set()
        srv.close()
        st = out[0]["stats"]
        self.assertEqual(out[0]["kind"], "synthetic")
        self.assertGreaterEqual(st["received"], 15)
        self.assertEqual(st["loss_pct"], 0.0)

    def test_synthetic_client_counts_reconnects_when_server_vanishes(self):
        out = []
        multi.synthetic_client(2, "127.0.0.1", 9, 1.2, 20, 0.3, out)  # port 9: nothing listens
        st = out[0]["stats"]
        self.assertEqual(st["received"], 0)
        self.assertTrue(out[0]["errors"])


class Report(unittest.TestCase):
    def test_markdown_smoke(self):
        trial = {"kind": "idle", "label": "x", "started": "s", "ping": {"loss_pct": 0.0, "p50_ms": 5, "p95_ms": 30, "p99_ms": 60, "max_ms": 99},
                 "tablet": {"rssi_after": -45, "tx_link_mbps_after": 86, "tx_retry_ratio": 0.6},
                 "ap": {"band": "5GHz", "channel": 36}, "pi": {"health_after": "HEALTHY", "temp_c_after": 35.0},
                 "client": {"serial": "SERIAL0001"}, "traffic": None}
        gate_doc = {"verdict": "PASS", "duration_s": 150, "client": {"serial": "SERIAL0001"}, "ap": {"band": "5GHz", "channel": 36},
                    "results": [{"level": "PASS", "text": "ok"}]}
        qual = {"started": "s", "client": "SERIAL0001", "restored_default": True, "original_profile": {"channel": "36"},
                "ranked": [{"channel": 36, "verdict": "PASS", "score": 95.0, "metrics": {}, "rssi_dbm": -45}], "skipped": {52: "dfs"}}
        md = report.render_markdown([("run1", trial)], [("g1", gate_doc)], [("q1", qual)], [])
        for needle in ("Pre-event gate runs", "**PASS**", "Channel qualification q1", "| 1 | 36 | PASS | 95.0", "run1", "Skipped"):
            self.assertIn(needle, md)


if __name__ == "__main__":
    unittest.main()
