#!/bin/sh
# Stop the running PS1 game (SIGTERM lets RetroArch flush memory-card saves).
# Signals only a process tools/ps1-pid.sh proves is this PS1 instance: the live
# arcade RetroArch has the same name, so a PID file alone is never enough.
HERE=$(dirname "$(readlink -f "$0")")
pid=$("$HERE/tools/ps1-pid.sh"); rc=$?
case $rc in
  0) ;;
  1) echo "no PS1 game running"; exit 0 ;;
  *) echo "stop-ps1: PS1 RetroArch identity not proven; signalled nothing." \
          "Check 'ps -fp PID' and stop it by hand if it really is PS1." >&2
     exit 1 ;;
esac
kill -TERM "$pid"
for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || exit 0; sleep 0.5; done
echo "retroarch $pid did not exit after 5 s" >&2; exit 1
