#!/bin/sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
python3 audit-legacy-rom.py
exec sh ./with-audio.sh xvfb-run -a -s '-screen 0 640x480x24 -nolisten tcp'   /usr/bin/python3 "$here/stream.py"
