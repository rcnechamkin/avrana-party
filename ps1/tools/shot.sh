#!/bin/sh
# Grab one PNG of the running headless PS1 display: shot.sh NAME -> screenshots/NAME.png
set -eu
H=${AVRANA_PS1_HOME:-$HOME/avrana-lab/ps1}
# ps1-pid.sh proves runtime/display and runtime/xauthority belong to the live PS1 RetroArch.
"$(dirname "$(readlink -f "$0")")/ps1-pid.sh" >/dev/null \
  || { echo "no proven PS1 RetroArch; refusing to guess a display" >&2; exit 1; }
D=$(cat "$H/runtime/display")
XAUTHORITY=$(cat "$H/runtime/xauthority"); export XAUTHORITY
gst-launch-1.0 -q ximagesrc display-name="$D" use-damage=false show-pointer=false num-buffers=1 \
  ! videoconvert ! pngenc ! filesink location="$H/screenshots/$1.png"
echo "$H/screenshots/$1.png"
