#!/bin/bash
# Sample PS1 emulator + host health every INTERVAL s for DURATION s (CSV to stdout).
# Read-only: checks AP/DHCP/DNS/web services, never restarts anything.
# NOTE ra_cpu is ps's lifetime average, not per-interval; the post-power test plan
# uses /proc/<pid>/stat deltas instead.
DUR=${1:-600}; INT=${2:-10}
H=${AVRANA_PS1_HOME:-$HOME/avrana-lab/ps1}
echo "t,ra_pid,ra_cpu,ra_rss_mb,xvfb_cpu,pulse_cpu,load1,mem_avail_mb,temp_c,throttled,wlan1,ap_clients,dnsmasq,nginx_http,lan_games_http,arcade"
prev=
for ((t=0; t<=DUR; t+=INT)); do
  pid=$(cat "$H/runtime/retroarch.pid" 2>/dev/null)
  read -r ra_cpu ra_rss < <(ps -o %cpu=,rss= -p "${pid:-0}" 2>/dev/null || echo "- 0")
  [[ $ra_rss =~ ^[0-9]+$ ]] || ra_rss=0   # emulator gone: keep sampling host health
  disp=$(cat "$H/runtime/display" 2>/dev/null)
  xv=$(ps -eo %cpu=,args= | awk -v d="Xvfb $disp " 'index($0,d){print $1; exit}')
  pu=$(ps -eo %cpu=,args= | awk '/avrana-lab\/ps1\/runtime\/pulse/ && /pulseaudio/ {print $1; exit}')
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$t" "$pid" "$ra_cpu" "$((${ra_rss:-0}/1024))" "${xv:--}" "${pu:--}" \
    "$(cut -d' ' -f1 /proc/loadavg)" "$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)" \
    "$(vcgencmd measure_temp | tr -dc '0-9.')" "$(vcgencmd get_throttled | cut -d= -f2)" \
    "$(cat /sys/class/net/wlan1/operstate)" "$(iw dev wlan1 station dump 2>/dev/null | grep -c ^Station)" \
    "$(pgrep -c dnsmasq)" "$(curl -s -o /dev/null -w '%{http_code}' -m 3 http://127.0.0.1/)" \
    "$(curl -s -o /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:8096/)" "$(systemctl is-active avranaparty-arcade)"
  sleep "$INT"
done
