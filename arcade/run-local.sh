#!/bin/sh
# One Gauntlet II instance on a private headless display. No network changes.
set -eu
cd /home/cody/avrana-party/arcade
python3 audit-legacy-rom.py
export SDL_RENDER_DRIVER=software
exec xvfb-run -a -s '-screen 0 640x480x24 -nolisten tcp' \
  retroarch -v -c /home/cody/avrana-party/arcade/retroarch.cfg \
  -L /home/cody/avrana-party/arcade/cores/mame2010_libretro.so \
  "$@" /srv/avrana/roms/arcade/gaunt2.zip
