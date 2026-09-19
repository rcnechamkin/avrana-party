#!/bin/sh
# Distribution packages only; does not install ROMs or change network/services.
set -eu
apt-get update
apt-get install --no-install-recommends \
  mame ffmpeg xvfb xauth python3-gi python3-aiohttp python3-evdev \
  gir1.2-gst-plugins-bad-1.0 gstreamer1.0-tools \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-nice
