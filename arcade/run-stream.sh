#!/bin/sh
set -eu
cd /home/cody/avrana-party/arcade
python3 audit-legacy-rom.py
exec sh ./with-audio.sh xvfb-run -a -s '-screen 0 640x480x24 -nolisten tcp' \
  /usr/bin/python3 /home/cody/avrana-party/arcade/stream.py
