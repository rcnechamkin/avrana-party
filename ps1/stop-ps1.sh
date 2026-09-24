#!/bin/sh
# Stop the running PS1 game (SIGTERM lets RetroArch flush memory-card saves).
RUN=${AVRANA_PS1_HOME:-$HOME/avrana-lab/ps1}/runtime
pid=$(cat "$RUN/retroarch.pid" 2>/dev/null) || { echo "no PS1 game running"; exit 0; }
[ "$(cat /proc/"$pid"/comm 2>/dev/null)" = retroarch ] || { echo "stale pid file"; exit 0; }
kill -TERM "$pid"
for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || exit 0; sleep 0.5; done
echo "retroarch $pid did not exit after 5 s" >&2; exit 1
