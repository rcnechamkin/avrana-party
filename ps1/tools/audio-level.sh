#!/bin/sh
# Prove the headless PS1 instance produces sound: record N s (default 5) from
# its private null-sink monitor and print peak/RMS (0 = silence).
set -eu
H=${AVRANA_PS1_HOME:-$HOME/avrana-lab/ps1}
export PULSE_SERVER=unix:$H/runtime/pulse/native
timeout "${1:-5}" parec -d avrana_ps1.monitor --raw --format=s16le --rate=48000 --channels=2 \
  | python3 -c 'import sys,array,math
a=array.array("h",sys.stdin.buffer.read())
print("samples=%d peak=%d rms=%.1f" % (len(a), max(map(abs,a)) if a else 0, math.sqrt(sum(x*x for x in a)/len(a)) if a else 0))'
