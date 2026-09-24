#!/bin/sh
# Print the PID of this PS1 instance's RetroArch, or refuse. The live arcade
# RetroArch is also named "retroarch", and after a crash or reboot a stale PID file
# can name it (or anything else), so a PID is printed only when EVERY check below
# passes. Anything that cannot be proven counts as not proven: fail closed.
#
#   exit 0  identity proven; the PID is on stdout
#   exit 1  no live PS1 instance: no PID file, or the recorded process is gone
#           (other boot, exited, or its PID now belongs to a newer process)
#   exit 2  something is at the recorded PID but it cannot be proven to be ours;
#           callers must not signal it or trust runtime/display
#
# runtime/retroarch.pid is "PID STARTTIME BOOT_ID", written by run-ps1.sh:
# STARTTIME is field 22 of /proc/PID/stat (clock ticks since boot, unchanged by
# exec), BOOT_ID is /proc/sys/kernel/random/boot_id.
#
#   ps1-pid.sh --record PID   prints that line for PID (run-ps1.sh stores it)
set -f   # the pid file is split into words below; never glob its contents
RUN=${AVRANA_PS1_HOME:-$HOME/avrana-lab/ps1}/runtime
gone()   { echo "ps1-pid: $*" >&2; exit 1; }
refuse() { echo "ps1-pid: $*; refusing" >&2; exit 2; }
# Field 22 of /proc/PID/stat, counted after the last ") ": comm may contain spaces and ")".
starttime() { sed 's/^.*) //' "/proc/$1/stat" 2>/dev/null | cut -d' ' -f20; }

if [ "${1:-}" = --record ]; then
  st=$(starttime "$2"); boot=$(cat /proc/sys/kernel/random/boot_id)
  [ -n "$st" ] && [ -n "$boot" ] || { echo "ps1-pid: cannot record PID $2" >&2; exit 1; }
  echo "$2 $st $boot"; exit 0
fi

[ -e "$RUN/retroarch.pid" ] || gone "no PS1 instance recorded in $RUN"
line=$(cat "$RUN/retroarch.pid" 2>/dev/null) || refuse "cannot read $RUN/retroarch.pid"
set -- $line
[ $# -eq 3 ] || refuse "pid file is not 'PID STARTTIME BOOT_ID' (written by an older run-ps1.sh?)"
pid=$1 start=$2 boot=$3
case $pid$start in ''|*[!0-9]*) refuse "malformed pid file";; esac

[ "$boot" = "$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)" ] \
  || gone "pid file is from another boot (stale; PID $pid is not ours)"
[ -e "/proc/$pid/stat" ] || gone "recorded PS1 RetroArch $pid has exited (stale pid file)"
[ "$(starttime "$pid")" = "$start" ] || gone "PID $pid now belongs to a newer process (stale pid file)"

# Same process that run-ps1.sh recorded. Now prove it is still the PS1 RetroArch.
[ "$(cat "/proc/$pid/comm" 2>/dev/null)" = retroarch ] || refuse "PID $pid is not retroarch"
[ "$(stat -c %u "/proc/$pid" 2>/dev/null)" = "$(id -u)" ] || refuse "PID $pid belongs to another user"
tr '\0' '\n' 2>/dev/null < "/proc/$pid/cmdline" | grep -qxF "$RUN/retroarch.cfg" \
  || refuse "PID $pid was not started with $RUN/retroarch.cfg (another RetroArch, e.g. the arcade)"

# In xvfb mode the tools reach the private display through runtime/display and
# runtime/xauthority, so they must be the ones this process actually runs on.
for pair in display:DISPLAY xauthority:XAUTHORITY; do
  f=${pair%%:*} var=${pair#*:}
  [ -e "$RUN/$f" ] || continue
  want=$(cat "$RUN/$f" 2>/dev/null)
  [ -n "$want" ] || refuse "$RUN/$f is empty"
  env=$(tr '\0' '\n' 2>/dev/null < "/proc/$pid/environ") || refuse "cannot read the environment of PID $pid"
  printf '%s\n' "$env" | grep -qxF "$var=$want" || refuse "$RUN/$f does not match $var of PID $pid"
done
echo "$pid"
