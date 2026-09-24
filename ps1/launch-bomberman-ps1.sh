#!/bin/sh
# Bomberman Party Edition (USA), up to 5 players (Multitap on port 2). See ps1/README.md.
exec "$(dirname "$(readlink -f "$0")")/run-ps1.sh" bomberman "$@"
