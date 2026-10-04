#!/bin/sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
# Where this service writes: the unit's runtime directory, or ./runtime for a hand-run prototype.
runtime=${AVRANA_ARCADE_RUNTIME:-$here/runtime}
export AVRANA_ARCADE_RUNTIME="$runtime"
export PULSE_SERVER=unix:$runtime/pulse/native
mkdir -p "$runtime/pulse"
chmod 700 "$runtime/pulse"
pulseaudio -n --daemonize=no --use-pid-file=no --exit-idle-time=-1   --load="module-native-protocol-unix socket=$runtime/pulse/native auth-anonymous=1"   --load='module-null-sink sink_name=avrana_arcade rate=48000 channels=2'   > "$runtime/pulse.log" 2>&1 &
audio_pid=$!
trap 'kill "$audio_pid" 2>/dev/null || true' EXIT
trap 'exit 143' TERM INT
ready=0
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if pactl info >/dev/null 2>&1; then ready=1; break; fi
  sleep 0.2
done
test "$ready" = 1
"$@"
