# PS1 shared stream: test plan for after the power fix

Date: 2026-09-23 · Status: **planned. Nothing here has been run.** Do not start until Stage 0 passes.

## Why this exists

The Pi 4 (`party`) reset at about 18:44 PDT on 2026-09-23 while it was streaming PS1. The evidence points to power, not heat:

- `rsts=0x20`, a watchdog-style reset. systemd has `RuntimeWatchdogSec=1m`.
- ext4 cleaned up orphans on the next boot, so the shutdown was unclean.
- Live under-voltage (`0x50005`) was logged 7 times in the hour before the reset. That is the worst rate in the log.
- Under-voltage came back 15 s into the next boot, with no load running.
- Heat is ruled out: the maximum was about 55 °C.
- `config.txt` is stock apart from `arm_boost=1` (1800 MHz). `vcgencmd get_config` shows
  `over_voltage_avs=-20000`, but it is firmware-internal, not set in `config.txt` (corrected 2026-09-23).
- The journal is not persistent, so the reset left no log behind.

This plan brings the load back in small steps. Each stage adds one thing, and every stage has hard abort rules. It also checks the cost model the design depends on: **one emulator and one encoder, whatever the viewer count.** Adding a viewer should add only a small WebRTC cost for that viewer.

Scope: Bomberman Party Edition. `stream_ps1.py` on port 8198. Simulated phones come from `tools/viewers.py`, which runs on the avrana mini-PC and **never on the Pi**.

## Ground rules

- **Owner-only steps.** Anything that needs `sudo` (stopping or starting the arcade, config changes, reboots) is done by the owner, who types the password. The agent reads and records.
- **The arcade must be down.** `avranaparty-arcade` uses about 1.9 cores. It is enabled at boot and hot-plugs uinput pads. Stop it before Stage 1 and keep it down until Restore.
- **One variable per stage.** Keep the Wi-Fi environment the same between stages: same viewer host, same position.
- **Viewer path.** Simulated viewers connect to `http://10.0.0.143:8198/`, which reaches the Pi over **wlan0** (home LAN). Real phones on the Avrana Party AP load **wlan1**. Record both interfaces at every stage. The viewer numbers below measure wlan0 load and do not measure AP airtime.
- **DNS check.** dnsmasq on 10.42.0.1 answers only the captive-portal names. `party.local` comes from mDNS, and `dig @10.42.0.1 party.local` returns NXDOMAIN even when DNS is healthy. Use `dig +short @10.42.0.1 captive.apple.com`, which must return `10.42.0.1`.
- `tools/monitor.sh` `ra_cpu` is a lifetime average from `ps`, so do not use it for CPU. Use the per-interval sampler below. You can still run `monitor.sh` for its service/HTTP columns.

### Global ABORT (applies to every stage, checked continuously)

Stop the stage **immediately** if any of these happens:

1. `vcgencmd get_throttled` has any bit set in the low nibble: `0x1` under-voltage now, `0x2` frequency capped, `0x4` throttled now, `0x8` soft temperature limit.
2. The count from `journalctl -k -b | grep -ci 'undervoltage detected'` goes up. (cody is in `adm` and can read the kernel journal without sudo.)
3. Temperature reaches 75 °C or more.
4. SSH or the AP drops. On reconnect, check whether the Pi rebooted (`uptime`, `cat /proc/sys/kernel/random/boot_id`).

Then:

1. Stop the load in this order: `quit` into the viewers' control file, Ctrl-C `stream_ps1.py` (or `./stop-ps1.sh`), then the samplers.
2. Record the time, the stage, the last 60 s of CSV and `journalctl -k -b | tail -50`.
3. **Stop testing. Do not retry the stage in the same session.** The owner decides what happens next.

## Instruments

Run these in separate SSH sessions on party. Set `D=~/avrana-lab/avrana-party-docs/ps1` and `L=~/avrana-lab/ps1-soak/$(date +%F)`, then `mkdir -p $L`.

**A. 1 s throttle sampler.** From the telemetry README. It runs in the foreground and must be started by the owner as root:

```bash
sudo /opt/avrana-telemetry/pi-throttle-check.sh --interval 1 --count 86400 \
     --label ps1-post-power --append /var/log/avrana/ps1-post-power.jsonl
```

**B. Kernel under-voltage watcher.** Beeps and prints on any new dip:

```bash
journalctl -k -f -n0 | grep --line-buffered -iE 'undervoltage|voltage normalis' | while read -r l; do printf '\a%s ABORT %s\n' "$(date +%T)" "$l" | tee -a $L/uv.log; done
```

**C. Per-interval process and host sampler.** Save the script to `$L/ps1-sample.sh` (it is not installed anywhere) and run it as `bash $L/ps1-sample.sh 5 > $L/stageN.csv`. It computes CPU from `/proc/<pid>/stat` deltas. Process CPU is in % of one core, so 100 = one full core. `sys_busy_pct` is the share of all 4 cores. The v4l2h264enc hardware encode, ximagesrc capture, opusenc and WebRTC fan-out all run as threads of the `stream_ps1.py` process, so the `stream_cpu` column is the encode-plus-fanout cost.

```bash
#!/bin/bash
# ps1-sample.sh [INTERVAL_S]  -> CSV on stdout. Read-only.
INT=${1:-5}; H=${AVRANA_PS1_HOME:-$HOME/avrana-lab/ps1}; RUN=$H/runtime; TCK=$(getconf CLK_TCK)
D=${D:-$HOME/avrana-lab/avrana-party-docs/ps1}   # $D from the SSH shell is not exported to this script
ticks() { [ -n "$1" ] && [ -r /proc/$1/stat ] && sed 's/^.*) //' /proc/$1/stat | awk '{print $12+$13}' || echo 0; }
sysj()  { awk '/^cpu /{i=$5+$6; t=0; for(k=2;k<=NF;k++) t+=$k; print t, i}' /proc/stat; }
calc()  { awk "BEGIN{printf \"%.1f\", $*}"; }   # awk math (bc is not installed on party)
net()   { awk -v i="$1:" '$1==i{print $2, $10}' /proc/net/dev; }
# Only trust runtime/retroarch.pid if it is really the PS1 RetroArch (a crash leaves stale files,
# and the arcade's own Xvfb/RetroArch can reuse the same display number): tools/ps1-pid.sh
# proves boot ID, start time, cmdline and display before printing a PID.
pids()  { RA=$($D/tools/ps1-pid.sh 2>/dev/null) || RA=
          XV=$([ -n "$RA" ] && pgrep -x -P "$(awk '{print $4}' /proc/$RA/stat)" Xvfb | head -1)
          PU=$(pgrep -f "socket=$RUN/pulse/native" | head -1); ST=$(pgrep -f 'stream_ps1.py' | head -1); }
echo "ts,throttled,temp_c,arm_mhz,load1,mem_avail_mb,sys_busy_pct,ra_cpu,stream_cpu,xvfb_cpu,pulse_cpu,ra_rss_mb,stream_rss_mb,wlan0_rx_kbps,wlan0_tx_kbps,wlan1_rx_kbps,wlan1_tx_kbps,ap_stations,dnsmasq,dns_ok,uv_kernel,enc_fps,players,spectators,stats_err"
pids; read T0 I0 < <(sysj); a0=$(ticks $RA); s0=$(ticks $ST); x0=$(ticks $XV); p0=$(ticks $PU)
read w0r w0t < <(net wlan0); read w1r w1t < <(net wlan1); vf0=; tp=$(date +%s.%N)
while sleep "$INT"; do
  pids; now=$(date +%s.%N); dt=$(calc "$now - $tp"); tp=$now
  read T1 I1 < <(sysj); a1=$(ticks $RA); s1=$(ticks $ST); x1=$(ticks $XV); p1=$(ticks $PU)
  read v0r v0t < <(net wlan0); read v1r v1t < <(net wlan1)
  pc() { calc "100*($2-$1)/($TCK*$dt)"; }; kb() { calc "8*($2-$1)/1000/$dt"; }
  st=$(curl -s -m 2 http://127.0.0.1:8198/stats | python3 -c 'import sys,json
try: d=json.load(sys.stdin); print(d["video_frames"], d["players"], d["spectators"], d["error"] or "-")
except Exception: print("- - - nostats")')
  read vf pl sp er <<<"$st"; fps=-; [ "$vf" != - ] && [ -n "$vf0" ] && fps=$(calc "($vf-$vf0)/$dt"); vf0=$([ "$vf" != - ] && echo $vf)
  rss() { [ -n "$1" ] && awk '/VmRSS/{print int($2/1024)}' /proc/$1/status 2>/dev/null || echo -; }
  echo "$(date +%T),$(vcgencmd get_throttled|cut -d= -f2),$(vcgencmd measure_temp|tr -dc 0-9.),$(( $(vcgencmd measure_clock arm|cut -d= -f2)/1000000 )),$(cut -d' ' -f1 /proc/loadavg),$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo),$(calc "100*(1-($I1-$I0)/($T1-$T0))"),$(pc $a0 $a1),$(pc $s0 $s1),$(pc $x0 $x1),$(pc $p0 $p1),$(rss $RA),$(rss $ST),$(kb $w0r $v0r),$(kb $w0t $v0t),$(kb $w1r $v1r),$(kb $w1t $v1t),$(/usr/sbin/iw dev wlan1 station dump 2>/dev/null | grep -c ^Station),$(pgrep -fc nm-dnsmasq-wlan1),$([ "$(dig +short +time=1 +tries=1 @10.42.0.1 captive.apple.com)" = 10.42.0.1 ] && echo 1 || echo 0),$(journalctl -k -b 2>/dev/null | grep -ci 'undervoltage detected'),$fps,$pl,$sp,$er"
  T0=$T1; I0=$I1; a0=$a1; s0=$s1; x0=$x1; p0=$p1; w0r=$v0r; w0t=$v0t; w1r=$v1r; w1t=$v1t
done
```

(A PID that restarts between samples gives one bad CPU value. Ignore that row. The `curl`, `python3` and `journalctl` calls cost about 1–2% of one core every 5 s. That overhead is the same in every stage, so it cancels out of the deltas.)

**D. Service health.** Optional. Run `bash $D/tools/monitor.sh <seconds> 10 > $L/stageN-monitor.csv` for the nginx/LAN Games/arcade columns. Ignore its `ra_cpu`.

**E. Stream stats snapshot**, at the end of each streaming stage: `curl -s http://127.0.0.1:8198/stats | python3 -m json.tool > $L/stageN-stats.json`. This file includes each peer's server-side RTCP RTT and loss plus client fps, kbps, jitter, dropped frames, freezes and ackRtt.

## Stage 0: Clean boot and power check (gate)

**Purpose:** prove the power supply is sound before any load.

**Setup (owner):**

1. Fit a known-good official 5.1 V / 3 A PSU with a short, thick USB-C cable. Record the model.
2. Recommended before testing (owner's decision, one change at a time, noted in the results):
   - Enable a persistent journal so that another reset leaves evidence. Pi OS forces volatile storage in `/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf`, so creating `/var/log/journal` alone does nothing (it already exists). Add a drop-in such as `/etc/systemd/journald.conf.d/50-persistent.conf` containing `[Journal]` and `Storage=persistent`, then `sudo systemctl restart systemd-journald`.
   - (`over_voltage_avs=-20000` needs no action: it is firmware-internal, not a line in `config.txt`. Corrected 2026-09-23.)
3. Reboot. Stop the arcade: `sudo systemctl stop avranaparty-arcade`. Start instruments A and B.

**Duration:** 10 min idle.

**Record:**

- PSU model and cable
- `config.txt` diff against the pre-reset version
- `vcgencmd get_throttled` at boot and at +10 min
- `journalctl -k -b | grep -ci 'undervoltage detected'`
- `boot_id`
- `vcgencmd get_config over_voltage_avs`

**PASS:** `get_throttled` reads `0x0` at boot and at every 1 s sample for 10 min, and the kernel under-voltage count is 0.

**FAIL / ABORT:** any non-zero throttled value, even sticky bits such as `0x50000` (they mean a dip happened after boot), or any kernel line. Do not start Stage 1. Hand back to the owner with the telemetry README's one-variable-at-a-time isolation steps (PSU, cable, USB Wi-Fi adapter on a powered hub).

From here on, `get_throttled` must stay exactly `0x0`. Any sticky bit that appears during a stage counts as an abort, even if nothing was caught live.

## Stage 1: Idle baseline (arcade stopped)

**Purpose:** the reference row every later stage is compared against.

**Setup:** **stale-file preflight.** (Since 2026-09-23, `run-ps1.sh` clears these files as soon as it takes the lock. Since 2026-09-24, every tool goes through `tools/ps1-pid.sh`, which proves boot ID, start time, command line and display before trusting the pid file, and `run-ps1.sh` starts its display search at `:110`, so it can no longer take the arcade's `:99`. Keep the manual check anyway.) An unclean reset leaves `~/avrana-lab/ps1/runtime/{display,xauthority,retroarch.pid}` behind. On 2026-09-23 the stale `display` was `:99`, which is the *arcade's* Xvfb number, so `tools/xkeys.py` and `tools/shot.sh` (both default to that file) would have targeted the arcade. With no PS1 running, run `rm -f ~/avrana-lab/ps1/runtime/{display,xauthority,retroarch.pid}`. Before any xkeys/shot call in later stages, check that `cat runtime/display` matches the Xvfb that is a sibling of the PS1 RetroArch (`pgrep -a -P $(ps -o ppid= $($D/tools/ps1-pid.sh)) Xvfb`; `retroarch.pid` now holds `PID STARTTIME BOOT_ID`, so never `cat` it into `ps`). Then confirm no PS1 is running with `pgrep -a 'retroarch|Xvfb|stream_ps1'` (it should print nothing, or only unrelated lines). Start the sampler: `bash $L/ps1-sample.sh 5 > $L/stage1.csv`.

**Duration:** 5 min.

**Record:** all sampler columns. Also note whether BLUFF dev (port 8196) and Beszel are running, and keep them the same state in every later stage.

**PASS:** throttled `0x0`, `sys_busy_pct` under 10%, `dns_ok=1`, dnsmasq 1, wlan1 UP.

## Stage 2: Bomberman emulation only

**Purpose:** the cost of RetroArch plus Xvfb plus Pulse, with no capture or input.

**Setup:** `cd $D && AVRANA_PS1_VIDEO=xvfb ./run-ps1.sh bomberman` (foreground). Start the sampler in another session. After 30 s, take `tools/shot.sh s2-title` to prove the title screen is showing.

**Duration:** 10 min on the attract/title screen.

**Record:** CSV (focus on `ra_cpu`, `xvfb_cpu`, `pulse_cpu`), the screenshot, and `tools/audio-level.sh 5` (the peak must be above 0).

**PASS:** throttled `0x0`, `ra_cpu` steady (expected about 100–130; software GL has been about 1.2 cores), temperature under 70 °C, services healthy.

**Stop:** `./stop-ps1.sh`.

## Stage 3: Emulation plus input bridge (xkeys, no stream)

**Purpose:** show that the four key banks drive P1–P4 on their own, without the stream in the picture.

**Setup:** start as in Stage 2. Navigate with `tools/xkeys.py`, using P1's bank (Start = `Return`, Cross = `z`, Down = `Down`). **Start does not confirm menus**, and CD loads take several seconds, so allow `sleep:4000` between screens. Presses made during a fade are ignored.

```bash
X=$D/tools/xkeys.py
$X Return:150 sleep:3000 Down:150 sleep:500 z:150 sleep:4000   # title -> BATTLE GAME
$X z:150 sleep:3000 z:150 sleep:3000 z:150 sleep:3000          # Battle Royal -> Beginner -> Single Match
$X z:150 sleep:3000 shot:s3-howmany                            # rules -> "How many players"
# Confirm 5 Human (default), characters and stage "Normal" with z presses, checking shots as you go
$X z:150 sleep:3000 z:150 sleep:3000 z:150 sleep:8000 shot:s3-start
# Each player moves alone (P1 top-left white, P2 bottom-right black, P3 top-right red, P4 bottom-left blue)
$X Right:400 sleep:500 shot:s3-p1  t:400 sleep:500 shot:s3-p2   # P1 right, P2 UP (t)
$X KP_5:400 sleep:500 shot:s3-p3  F2:400 sleep:500 shot:s3-p4
$X Down,g,KP_5,F1:400 sleep:500 shot:s3-all                     # simultaneous
```

Pick moves that are open from each spawn point: P1 right or down, P2 up or left, P3 down or left, P4 up or right.

**Duration:** about 10 min.

**Record:** screenshots and a CSV (compare `ra_cpu` with Stage 2).

**PASS:** each `s3-pN` shot shows only that player's character moved; `s3-all` shows all four moved; throttled `0x0`.

## Stage 4: Emulation plus one encoder (stream server, 0 viewers)

**Purpose:** the fixed cost of capture, encode and Opus.

**Setup:** stop Stage 3 first. `stream_ps1.py` launches `run-ps1.sh` itself, and the flock refuses a second instance. Then:

```bash
cd $D && python3 -X faulthandler stream_ps1.py bomberman --host 127.0.0.1 --host 10.42.0.1 --host 10.0.0.143 2>&1 | tee $L/stream.log
```

**Duration:** 10 min.

**Record:** CSV (`stream_cpu`, `enc_fps`), the `/stats` snapshot, and `ls -l /proc/$(pgrep -f stream_ps1.py)/fd | grep -c video11` (must be 1).

**PASS:** `/stats` `encoders` = `{video: 1, audio: 1}` (counted from the live pipelines, not a constant), `enc_fps` 55–60 and steady, `capture_age_ms` p50 for video under 30 ms, `emulator_running=true`, `error=null`, throttled `0x0`.

**Baseline for the cost model:** `E0 = median(stream_cpu)`, `R0 = median(ra_cpu)`, and `S0 = median(sys_busy_pct)`.

## Stages 5–7: add 1, 2 and 4 viewers

**Purpose:** show that encode cost stays flat as viewers are added, and measure the cost per viewer.

**Setup:** keep the Stage 4 server running, with the game on the title screen or in a battle (note which, and keep the scene the same across stages). On the **avrana mini-PC**:

```bash
python3 viewers.py http://10.0.0.143:8198/ --players 0 --watchers N --seconds 600 --control /tmp/ps1ctl --out ~/ps1-stageK.json
```

Use N = 1 (Stage 5), 2 (Stage 6) and 4 (Stage 7). Wait at least 60 s between stages so the peers get torn down.

**Duration:** 10 min each.

**Record:**

- sampler CSV
- `/stats` snapshot at about minute 8: `spectators` must equal N, plus each peer's RTCP RTT/loss
- the viewers.py summary: `fps_avg`, `kbps_avg`, `jitter_ms_avg`, `lost`, `dropped`, `freezes`, `ack_rtt_p50`
- wlan0 tx kbps (expected about N × the stream bitrate, which is capped at 2.5 Mbit/s)

**Cost-model check:**

- `ΔE(N) = median(stream_cpu) − E0`, and the per-viewer cost is `ΔE(N)/N`.
- `ra_cpu` must stay within ±10% of R0.
- `/stats` `encoders` must stay `{video: 1, audio: 1}` with N viewers connected, and the `video11` fd count must stay 1.
- `enc_fps` must not fall as N rises.

**PASS:**

- throttled `0x0`
- per-viewer `ΔE/N` of 10 or less (10% of one core) and roughly constant from N = 1 to 4
- `sys_busy_pct` at N = 4 no more than `S0 + 15`
- every viewer `fps_avg` of 45 or more
- median per-interval loss 0 (ADR 0001 gates)
- no viewer errors

Client jitter and RTT are reported but not gated (co-located Chromium is pessimistic).

**FAIL** (performance, not power): `ΔE/N` growing with N, `ra_cpu` falling (the emulator is starved), or `enc_fps` under 55. Finish the stage, record it, and do not move on to 8–10 until it is understood.

## Stage 8: Four distinct players (independent slots via the web path)

**Purpose:** show that the phone path assigns four separate controller slots, and that each one drives only its own character.

**Setup:** restart the server so the slot table is clean (the grace period holds slots for 30 s). On the mini-PC:

```bash
python3 viewers.py http://10.0.0.143:8198/ --players 4 --watchers 1 --seconds 900 --control /tmp/ps1ctl --out ~/ps1-stage8.json
```

The printout must list phones 0–3 as `Player 1..4` and phone 4 as spectator. `shot` captures the **last** connected page, which is the spectator's decoded video, so it proves what the stream shows. Drive the menus by appending lines to `/tmp/ps1ctl`, pausing between them to let screens load:

```
1 start 150
sleep 3000
1 down 150
1 cross 150
sleep 4000
1 cross 150
sleep 3000
1 cross 150
sleep 3000
1 cross 150
sleep 3000
1 cross 150
sleep 3000
shot /tmp/s8-howmany.png
debug
```

Continue through players (5 Human is the default), characters and stage "Normal", then `shot /tmp/s8-start.png`. Then:

```
1 right 400
sleep 600
shot /tmp/s8-p1.png
2 up 400
sleep 600
shot /tmp/s8-p2.png
3 down 400
sleep 600
shot /tmp/s8-p3.png
4 up 400
sleep 600
shot /tmp/s8-p4.png
1+2+3+4 up 400
sleep 600
shot /tmp/s8-all.png
```

(For the simultaneous press, "up" is blocked for P1 and P3 at the top edge. Use per-player open directions in quick succession if the shot is ambiguous.) Take `/stats` during play.

**Record:**

- the 6 spectator screenshots
- `/stats` `slots` (4 entries, all `connected:true`), `players=4`, `spectators=1`, and each peer's `slot` 1–4
- viewers.py role printout, `debug` output and CSV

**PASS:** each `s8-pN` shows exactly player N moved from its spawn (P1 white top-left, P2 black bottom-right, P3 red top-right, P4 blue bottom-left) and no other; `s8-all` shows all four moved; the slot table is correct; throttled `0x0`.

**Optional extra check:** in a separate run, close player 2's context and reopen it within 30 s. It should get back slot 2 (token reclaim).

## Stage 9: Four players plus spectator, sustained load

**Purpose:** the full party load in real gameplay.

**Setup:** carry on from Stage 8, in battle. Feed a looping control file with steady movement from all four players, for example a shell loop on the mini-PC:

```bash
while :; do for d in up left down right; do echo "1+2+3+4 $d 300" >> /tmp/ps1ctl; sleep 0.5; done; done
```

Drop some bombs too, with occasional `cross`. Restart the match when it ends.

**Duration:** 15 min.

**Record:** everything listed under "Every stage records" below, plus `/stats` at 5, 10 and 15 min.

**PASS:**

- throttled `0x0`
- `enc_fps` of 55 or more
- all 5 clients with `fps_avg` of 45 or more and freezes not increasing
- `stream_cpu` within the Stage 7 envelope, plus the input cost
- temperature under 70 °C, `dns_ok=1`, AP stations stable

## Stage 10: Sustained soak

**Purpose:** long-run stability: heat soak, memory growth, audio capture-age drift (ADR 0001 notes a known audio ratchet in the arcade) and power under continuous load.

**Setup:** the Stage 9 load. Run 30 min first. Continue to **2 h** only if the 30 min run passes and the owner agrees.

**Record:** CSV throughout, `/stats` every 10 min (look at `capture_age_ms.audio` and `.video`), RSS of `retroarch` and `stream_ps1` at the start and end, and the viewers.py summary.

**PASS:**

- throttled `0x0` for the whole run, and no kernel under-voltage lines
- temperature plateaus below 70 °C
- `stream_rss_mb` and `ra_rss_mb` grow by less than 10%
- `enc_fps` stays at 55 or more
- audio capture-age p50 does not ratchet upward (record the trend even if it is not gated)
- no client disconnects

## Restore (always, including after an abort)

1. `echo quit >> /tmp/ps1ctl` on the mini-PC. Ctrl-C `stream_ps1.py` and wait up to 10 s. Its cleanup stops `run-ps1.sh`, RetroArch, Xvfb and Pulse. If only `run-ps1.sh` is running, use `$D/stop-ps1.sh`.
2. Check for orphans:
   ```bash
   pgrep -a retroarch; pgrep -af stream_ps1; pgrep -af 'Xvfb'; pgrep -af 'socket=.*avrana-lab/ps1/runtime/pulse'; ss -ltn | grep 8198; fuser /dev/video11
   ```
   Each must print nothing apart from arcade-owned processes, which should not exist yet. Kill any leftovers by PID, TERM first.
3. Stop samplers A–D and record the final `get_throttled` and kernel under-voltage count.
4. Owner: `sudo systemctl start avranaparty-arcade`. Wait about 20 s, then:
   ```bash
   systemctl is-active avranaparty-arcade avranaparty-games nginx
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/arcade/   # 200
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/          # LAN Games 200
   curl -s http://127.0.0.1/arcade/stats | head -c 300
   ss -ltn | grep 8196                                                  # BLUFF dev, only if it was running before
   ```
5. Copy `$L`, the viewers JSON and the screenshots to `~/avrana-lab/ps1/evidence/post-power-<date>/`, which is **untracked**. Screenshots are copyrighted game frames and must never go into git. Commit only the filled-in results table and text findings.

## Every stage records

Take medians over the stage and the maximum or minimum where noted.

- `get_throttled`: **must be `0x0`**
- temperature (median / max)
- ARM MHz (min)
- load1 and `sys_busy_pct`
- MemAvailable (min)
- `ra_cpu`, `stream_cpu`, `xvfb_cpu`, `pulse_cpu`, and RSS
- wlan0 and wlan1 rx/tx kbps
- `enc_fps`, `capture_age_ms`
- per-viewer fps, kbps, jitter, loss, dropped, freezes, RTT
- AP stations, dnsmasq, `dns_ok`
- kernel under-voltage count delta
- the cost-model delta against Stage 4

## Results table (fill in)

| Stage | Start (PDT) | Dur | throttled end | UV Δ | temp med/max °C | ARM min MHz | sys busy % | load1 | mem avail min MB | ra_cpu | stream_cpu | xvfb/pulse | ΔE/N | enc fps | viewer fps min | loss / dropped / freezes | wlan0 tx kbps | wlan1 tx kbps | AP sta / dns_ok | PASS/FAIL/ABORT | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 clean boot | | 10m | | | | | | | | – | – | – | – | – | – | – | | | | | PSU: |
| 1 idle | | 5m | | | | | | | | – | – | – | – | – | – | – | | | | | |
| 2 emu | | 10m | | | | | | | | | – | | – | – | – | – | | | | | |
| 3 emu+xkeys | | 10m | | | | | | | | | – | | – | – | – | – | | | | | shots: |
| 4 +encoder, 0 v | | 10m | | | | | | | | | E0= | | – | | – | – | | | | | |
| 5 +1 viewer | | 10m | | | | | | | | | | | | | | | | | | | |
| 6 +2 viewers | | 10m | | | | | | | | | | | | | | | | | | | |
| 7 +4 viewers | | 10m | | | | | | | | | | | | | | | | | | | |
| 8 4 players (slots) | | ~15m | | | | | | | | | | | | | | | | | | | slots: |
| 9 4P + spectator | | 15m | | | | | | | | | | | | | | | | | | | |
| 10 soak 30m / 2h | | | | | | | | | | | | | | | | | | | | | RSS Δ: |
| Restore | | – | | | | | | | | – | – | – | – | – | – | – | – | – | | | arcade/LAN/8196: |
