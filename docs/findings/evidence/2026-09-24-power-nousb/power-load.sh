#!/usr/bin/env bash
# Bounded, reversible load phases for the no-USB power test. Runs ON the Pi; writes only under
# ~/avrana-lab/power-watch. Phases: B light activity (15 min), C all-core CPU bursts (15 min),
# D Wi-Fi traffic to associated phones (10 min). Stops escalating on new dips or > 75 C.
set -u
OUT=$1                       # path prefix for logs
LOG=$OUT.phases.log
TMP=$HOME/avrana-lab/power-watch/.loadtmp
mkdir -p "$TMP"
dips() { journalctl -k -b | grep -icE 'undervoltage|voltage normalis'; }
temp() { vcgencmd measure_temp | tr -dc 0-9.; }
mark() { echo "$(date +%T.%3N) $*" >> "$LOG"; }
START_DIPS=$(dips)
guard() {  # returns 1 (stop escalating) on >= 2 new dips or temperature > 75 C
  local d t; d=$(dips); t=$(temp)
  if [ $((d - START_DIPS)) -ge 4 ]; then mark "GUARD stop: dip_lines $START_DIPS -> $d"; return 1; fi
  if awk -v t="$t" 'BEGIN{exit !(t > 75)}'; then mark "GUARD stop: temp $t"; return 1; fi
  return 0
}
burst() {  # $1 = cores, $2 = seconds: pure-Python busy loops, hard-bounded by timeout
  local i
  for i in $(seq 1 "$1"); do
    timeout "$(( $2 + 2 ))" python3 -c "import time; e=time.time()+$2
while time.time()<e: pass" &
  done
  wait
}
mark "START dip_lines=$START_DIPS temp=$(temp) thr=$(vcgencmd get_throttled)"

mark "PHASE B light activity (15 min)"
end=$(( $(date +%s) + 900 )); n=0
while [ "$(date +%s)" -lt "$end" ]; do
  n=$((n + 1))
  curl -s -o /dev/null -m 5 http://127.0.0.1/                                    # nginx -> LAN Games hub
  curl -s -o /dev/null -m 5 -H 'Host: captive.apple.com' http://127.0.0.1/hotspot-detect.html
  curl -s -o /dev/null -m 5 http://127.0.0.1:8096/api/games                      # LAN Games direct
  curl -s -o /dev/null -m 5 http://127.0.0.1/arcade/                             # arcade page via nginx
  if [ $((n % 3)) = 0 ]; then                                                    # filesystem work
    find /usr/share -type f -name '*.txt' > /dev/null 2>&1
    dd if=/dev/zero of="$TMP/f" bs=1M count=20 conv=fsync status=none; rm -f "$TMP/f"
  fi
  if [ $((n % 3)) = 1 ]; then mark "B burst 1 core 5 s"; burst 1 5; fi
  sleep 20
done
mark "PHASE B end dip_lines=$(dips) temp=$(temp)"

mark "PHASE C all-core CPU bursts (15 min)"
end=$(( $(date +%s) + 900 ))
while [ "$(date +%s)" -lt "$end" ]; do
  guard || break
  mark "C burst 4 cores 20 s (temp $(temp))"; burst 4 20
  mark "C burst end (temp $(temp))"
  sleep 70
done
mark "PHASE C end dip_lines=$(dips) temp=$(temp)"

mark "PHASE D Wi-Fi traffic to associated phones (10 min)"
peers=$(ip -4 neigh show dev wlan0 | awk '/REACHABLE|STALE|DELAY/{print $1}' | tr '\n' ' ')
mark "D peers: $(echo "$peers" | wc -w) (addresses not logged)"
end=$(( $(date +%s) + 600 ))
while [ "$(date +%s)" -lt "$end" ]; do
  guard || break
  for p in $peers; do
    timeout 65 ping -q -i 0.02 -s 1200 -w 60 "$p" > "$TMP/ping.txt" 2>&1
    mark "D ping 60 s @50/s 1200 B: $(grep -oE '[0-9]+ packets transmitted, [0-9]+ received' "$TMP/ping.txt")"
  done
  [ -z "$peers" ] && { mark "D no peers"; break; }
done
mark "PHASE D end dip_lines=$(dips) temp=$(temp)"
rm -rf "$TMP"
mark "END dip_lines=$(dips) thr=$(vcgencmd get_throttled) temp=$(temp)"
