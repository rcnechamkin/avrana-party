#!/bin/bash
# Launch one PS1 game with RetroArch + PCSX-ReARMed.
#   run-ps1.sh <worms|bomberman> [extra retroarch args, e.g. --max-frames=600]
# Env: AVRANA_PS1_HOME (state: core, BIOS link, saves, logs; default ~/avrana-lab/ps1)
#      AVRANA_PS1_ROMS (read-only game/BIOS files; default /srv/avrana/roms/psx)
#      AVRANA_PS1_VIDEO=xvfb|kms|auto (auto: kms if an HDMI connector is connected)
set -euo pipefail

HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
PS1_HOME=${AVRANA_PS1_HOME:-$HOME/avrana-lab/ps1}
ROMS=${AVRANA_PS1_ROMS:-/srv/avrana/roms/psx}
CORE=$PS1_HOME/cores/pcsx_rearmed_libretro.so
BIOS_SRC=$ROMS/SCPH1001.BIN
BIOS_LINK=$PS1_HOME/system/scph1001.bin
RUN=$PS1_HOME/runtime

die() { echo "run-ps1: $*" >&2; exit 1; }

[ "$(id -u)" != 0 ] || die "refusing to run as root"
[ $# -ge 1 ] || die "usage: run-ps1.sh <worms|bomberman> [retroarch args]"
GAME=$1; shift
case $GAME in
  worms)     CUE="$ROMS/Worms Armageddon (USA)/Worms Armageddon (USA)/Worms Armageddon (USA).cue" ;;
  bomberman) CUE="$ROMS/Bomberman - Party Edition (USA)/Bomberman - Party Edition (USA)/Bomberman - Party Edition (USA).cue" ;;
  *) die "unknown game '$GAME' (expected worms or bomberman)" ;;
esac

# --- preflight: fail clearly before anything starts -------------------------
command -v retroarch >/dev/null || die "retroarch not installed (apt install retroarch)"
[ -f "$CORE" ] || die "core missing: $CORE (fetch per ps1/evidence/selected-core.json)"
want=$(awk '/"so_sha256"/ {gsub(/[",]/, "", $2); print $2}' "$HERE/evidence/selected-core.json")
have=$(sha256sum "$CORE" | cut -d' ' -f1)
[ "$want" = "$have" ] || die "core checksum $have does not match pinned $want"
[ -f "$BIOS_SRC" ] || die "BIOS missing: $BIOS_SRC"
[ "$(stat -c%s "$BIOS_SRC")" = 524288 ] || die "BIOS $BIOS_SRC is not a 512 KiB PS1 BIOS"
[ -f "$CUE" ] || die "cue sheet missing: $CUE"
bin=$(sed -n 's/^FILE "\(.*\)" BINARY.*/\1/p' "$CUE" | tr -d '\r' | head -1)
[ -n "$bin" ] && [ -f "$(dirname "$CUE")/$bin" ] || die "cue references missing bin: '$bin'"

mkdir -p "$PS1_HOME"/{system,saves,states,screenshots} "$RUN"/{logs,pulse,config,remaps,autoconfig,playlists,history,cache}
chmod 700 "$PS1_HOME/saves" "$PS1_HOME/states" "$PS1_HOME/system" "$RUN/pulse"
ln -sfn "$BIOS_SRC" "$BIOS_LINK"

# --- single instance --------------------------------------------------------
exec 9>"$RUN/ps1.lock"
flock -n 9 || die "a PS1 game is already running (see $RUN/retroarch.pid; stop with stop-ps1.sh)"
# Anything left here predates this lock: a crash or power loss. The display number in
# particular may now belong to another X server (e.g. the arcade's :99), so drop it.
rm -f "$RUN/retroarch.pid" "$RUN/retroarch.pid.new" "$RUN/display" "$RUN/xauthority"
PS1PID=$HERE/tools/ps1-pid.sh
export AVRANA_PS1_HOME=$PS1_HOME   # ps1-pid.sh must check the same runtime dir

MODE=${AVRANA_PS1_VIDEO:-auto}
if [ "$MODE" = auto ]; then
  MODE=xvfb
  grep -qx connected /sys/class/drm/card*-HDMI-A-*/status 2>/dev/null && MODE=kms
fi
case $MODE in xvfb|kms) ;; *) die "AVRANA_PS1_VIDEO must be xvfb, kms or auto" ;; esac

sed "s|@PS1_HOME@|$PS1_HOME|g" "$HERE/retroarch.cfg" > "$RUN/retroarch.cfg"
cp "$HERE/games/$GAME.opt" "$RUN/core-options.opt"   # fresh copy each launch
LOG=$RUN/logs/$GAME-$(date +%Y%m%dT%H%M%S).log
ln -sfn "$LOG" "$RUN/logs/$GAME-latest.log"
export XDG_CONFIG_HOME=$RUN/xdg   # keep RetroArch out of ~/.config/retroarch
mkdir -p "$XDG_CONFIG_HOME"
echo "run-ps1: $GAME mode=$MODE log=$LOG"

RA=(retroarch --verbose --log-file="$LOG" -c "$RUN/retroarch.cfg"
    --appendconfig="$HERE/mode-$MODE.cfg|$HERE/games/$GAME.cfg"
    -L "$CORE" "$@" "$CUE")

pulse_pid= ra_pid= wait_pid=
# True while ps1-pid.sh still proves $ra_pid is this instance's RetroArch. In xvfb
# mode it is a grandchild, so once it exits its PID may be reused (e.g. by the
# arcade's RetroArch): never signal it on the strength of the number alone.
ours() { [ -n "$ra_pid" ] && [ "$("$PS1PID" 2>/dev/null)" = "$ra_pid" ]; }
cleanup() {
  set +e   # never abort half-way: every step below must run
  # The pid file is written just before the inner shell exec's retroarch: allow for that.
  [ -n "$ra_pid" ] && for _ in $(seq 10); do ours && break; sleep 0.1; done
  if ours; then   # in xvfb mode RetroArch is a grandchild: poll, don't wait
    kill -TERM "$ra_pid" 2>/dev/null
    for _ in $(seq 100); do ours || break; sleep 0.1; done
    ours && kill -KILL "$ra_pid" 2>/dev/null
  fi
  [ -n "$wait_pid" ] && wait "$wait_pid" 2>/dev/null   # xvfb-run removes its Xvfb
  if [ -n "$pulse_pid" ]; then kill "$pulse_pid" 2>/dev/null; wait "$pulse_pid" 2>/dev/null; fi
  rm -f "$RUN/retroarch.pid" "$RUN/retroarch.pid.new" "$RUN/display" "$RUN/xauthority"
}
trap cleanup EXIT
trap 'exit 143' TERM INT HUP

if [ "$MODE" = xvfb ]; then
  export PULSE_SERVER=unix:$RUN/pulse/native
  # We hold the lock, so any daemon still on our socket is a leftover: remove it.
  pkill -u "$(id -u)" -f "socket=$RUN/pulse/native" 2>/dev/null && sleep 0.5
  # No session bus for the private daemon: an SSH/desktop session already owns
  # org.PulseAudio1 there, and the private instance needs no D-Bus at all.
  DBUS_SESSION_BUS_ADDRESS=unix:path=/nonexistent pulseaudio -n --daemonize=no --use-pid-file=no --exit-idle-time=-1 \
    --load="module-native-protocol-unix socket=$RUN/pulse/native auth-anonymous=1" \
    --load="module-null-sink sink_name=avrana_ps1 rate=48000 channels=2" \
    > "$RUN/logs/pulse.log" 2>&1 9>&- &
  pulse_pid=$!
  for _ in $(seq 25); do pactl info >/dev/null 2>&1 && break; sleep 0.2; done
  pactl info >/dev/null 2>&1 || die "private PulseAudio did not start (see $RUN/logs/pulse.log)"
  # Inner shell records the display and its Xauthority file so tools/ can reach this
  # private display, then (last, atomically) its identity "PID STARTTIME BOOT_ID"
  # (tools/ps1-pid.sh), then exec's into retroarch, which keeps that PID and start time.
  xvfb-run -a -s '-screen 0 640x480x24 -nolisten tcp' \
    sh -c 'echo "$DISPLAY" > "$0/display"; echo "$XAUTHORITY" > "$0/xauthority"
      "$1" --record $$ > "$0/retroarch.pid.new" && mv -f "$0/retroarch.pid.new" "$0/retroarch.pid"
      shift; exec "$@"' "$RUN" "$PS1PID" "${RA[@]}" &
  wait_pid=$!
  for _ in $(seq 50); do [ -s "$RUN/retroarch.pid" ] && break; sleep 0.1; done
  ra_pid=$(cut -d' ' -f1 "$RUN/retroarch.pid" 2>/dev/null || true)
  rc=0; wait "$wait_pid" || rc=$?
else
  "${RA[@]}" &
  ra_pid=$!   # our unreaped child, so this PID cannot be reused before we wait
  "$PS1PID" --record "$ra_pid" > "$RUN/retroarch.pid.new" && mv -f "$RUN/retroarch.pid.new" "$RUN/retroarch.pid"
  rc=0; wait "$ra_pid" || rc=$?
fi
ra_pid= wait_pid=
echo "run-ps1: $GAME exited rc=$rc"
exit "$rc"
