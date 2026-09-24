#!/bin/sh
# Worms Armageddon (USA), 1-4 players hot-seat. See ps1/README.md.
exec "$(dirname "$(readlink -f "$0")")/run-ps1.sh" worms "$@"
