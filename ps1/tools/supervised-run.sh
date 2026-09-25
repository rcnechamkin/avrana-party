#!/bin/bash
# A bounded, self-guarding PS1 stream run. Runs ON the Pi, detached from SSH, so nobody has to
# poll the Pi while it measures power (SSH bursts have tipped it into under-voltage before).
#
#   tools/supervised-run.sh <title> <max-seconds> [stream_ps1.py args, e.g. --host 10.0.0.142]
#
# Starts stream_ps1.py under a hard `timeout`, logs power once a second, and stops the stream
# early on live under-voltage/throttling, > 80 C, or 2+ new kernel under-voltage lines.
# Stop it yourself with:  touch <run dir>/stop
# Results (read once, at the end): $AVRANA_PS1_HOME/evidence/runs/<timestamp>-<title>/
#   power.jsonl  one line per second      stream.log  the server's output
#   summary.txt  verdict, dips, max temp, min clock, cleanup check
set -u
HERE=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
PS1_HOME=${AVRANA_PS1_HOME:-$HOME/avrana-lab/ps1}
GAME=${1:?usage: supervised-run.sh <title> <max-seconds> [stream args]}
MAX=${2:?usage: supervised-run.sh <title> <max-seconds> [stream args]}
shift 2
case $MAX in ''|*[!0-9]*) echo "max-seconds must be an integer" >&2; exit 2 ;; esac
[ "$MAX" -le 3600 ] || { echo "max-seconds is capped at 3600" >&2; exit 2; }
OUT=$PS1_HOME/evidence/runs/$(date +%Y%m%dT%H%M%S)-$GAME
mkdir -p "$OUT"
echo "$OUT"

dips() { journalctl -k -b 2>/dev/null | grep -icE 'undervoltage|voltage normalis'; }
note() { echo "$(date +%T) $*" >> "$OUT/summary.txt"; }

run() {
  local start_dips thr hex temp arm load now reason= n=0 maxt=0 minarm=9999999999
  start_dips=$(dips)
  note "START $GAME max=${MAX}s dips=$start_dips $(vcgencmd get_throttled) $(vcgencmd measure_temp)"
  cd "$HERE" || exit 1
  timeout --signal=TERM --kill-after=20 "$MAX" python3 -X faulthandler stream_ps1.py "$GAME" "$@" \
    > "$OUT/stream.log" 2>&1 &
  local spid=$!
  while kill -0 "$spid" 2>/dev/null; do
    sleep 1; n=$((n + 1))
    thr=$(vcgencmd get_throttled); hex=${thr#throttled=}
    temp=$(vcgencmd measure_temp | tr -dc 0-9.)
    arm=$(vcgencmd measure_clock arm | cut -d= -f2)
    load=$(cut -d' ' -f1 /proc/loadavg)
    now=$(dips)
    printf '{"t":%d,"ts":"%s","throttled":"%s","temp":%s,"arm_hz":%s,"load1":%s,"dip_lines":%s}\n' \
      "$n" "$(date +%T)" "$hex" "$temp" "$arm" "$load" "$now" >> "$OUT/power.jsonl"
    awk -v t="$temp" -v m="$maxt" 'BEGIN{exit !(t > m)}' && maxt=$temp
    [ "$arm" -lt "$minarm" ] && minarm=$arm
    if [ -z "$reason" ]; then
      if (( hex & 0x5 )); then reason="live under-voltage/throttle $hex"
      elif awk -v t="$temp" 'BEGIN{exit !(t > 80)}'; then reason="temperature $temp C"
      elif [ $((now - start_dips)) -ge 2 ]; then reason="kernel under-voltage lines $start_dips -> $now"
      elif [ -e "$OUT/stop" ]; then reason="operator stop file"
      fi
      if [ -n "$reason" ]; then note "STOPPING: $reason"; kill -TERM "$spid" 2>/dev/null; fi
    fi
  done
  wait "$spid"; local rc=$?
  sleep 2
  local left
  left=$("$HERE/tools/ps1-pid.sh" >/dev/null 2>&1; echo $?)
  note "END rc=$rc seconds=$n reason=${reason:-none} dips=$(dips) (start $start_dips) max_temp=$maxt min_arm=$minarm $(vcgencmd get_throttled)"
  note "cleanup: ps1-pid.sh exit $left (1 = no PS1 RetroArch left), leftover processes: $(pgrep -u "$(id -u)" -fc "$PS1_HOME/runtime" || true)"
  [ "$rc" = 124 ] && note "(rc 124 = reached the time limit)"
  note "VERDICT $([ -z "$reason" ] || [ "$reason" = 'operator stop file' ] && echo clean || echo ABORTED)"
}
setsid -f bash -c "$(declare -f dips note run); HERE='$HERE' PS1_HOME='$PS1_HOME' GAME='$GAME' MAX='$MAX' OUT='$OUT'; run \"\$@\"" \
  supervised "$@" < /dev/null > "$OUT/supervisor.log" 2>&1
