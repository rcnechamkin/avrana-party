#!/bin/sh
# Grab one PNG of the running headless PS1 display: shot.sh NAME -> screenshots/NAME.png
set -eu
H=${AVRANA_PS1_HOME:-$HOME/avrana-lab/ps1}
pid=$(cat "$H/runtime/retroarch.pid" 2>/dev/null) || true
[ "$(cat /proc/"${pid:-0}"/comm 2>/dev/null)" = retroarch ] \
  || { echo "no running PS1 RetroArch; refusing to guess a display" >&2; exit 1; }
D=$(cat "$H/runtime/display")
XAUTHORITY=$(cat "$H/runtime/xauthority"); export XAUTHORITY
gst-launch-1.0 -q ximagesrc display-name="$D" use-damage=false show-pointer=false num-buffers=1 \
  ! videoconvert ! pngenc ! filesink location="$H/screenshots/$1.png"
echo "$H/screenshots/$1.png"
