#!/usr/bin/env bash
# Create the per-game session key that Party Core and that game's server share (ADR 0006 D5).
# Pi only, run by the owner:
#
#   sudo bash ops/provision-party-game-key.sh bluff
#
# Writes $dir/<slug>.key: 32 random bytes as 64 hex characters and a newline (the format
# avrana.party.protocol.read_key accepts), owner $owner, mode 0600, in a 0700 directory. The owner
# is Party Core's user, avrana-party (ADR 0016): every other holder gets its key from systemd as
# a credential. On a host not yet migrated (AVR-256) pass AVRANA_PARTY_KEY_OWNER explicitly. Refuses
# to overwrite: rotating a key is deliberate (remove the file, re-run, restart both services).
# Never prints, logs or echoes the key.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

slug=${1:-}
[[ $slug =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]] || { echo 'usage: provision-party-game-key.sh <game-slug>' >&2; exit 2; }
dir=${AVRANA_PARTY_KEY_DIR:-/etc/avrana-party/game-keys}
owner=${AVRANA_PARTY_KEY_OWNER:-avrana-party}
id -u "$owner" >/dev/null 2>&1 || { echo "user $owner does not exist: run ops/migrate-service-users.sh first, or set AVRANA_PARTY_KEY_OWNER" >&2; exit 1; }
key=$dir/$slug.key

install -d -m 0700 -o "$owner" -g "$(id -gn "$owner")" "$dir"
if [[ -e $key ]]; then
    echo "$key already exists; not overwriting" >&2
    exit 1
fi
umask 077
tmp=$(mktemp "$dir/.$slug.key.XXXXXX")
trap 'rm -f "$tmp"' EXIT
hex=$(od -An -v -N32 -tx1 /dev/urandom | tr -d ' \n')
[[ $hex =~ ^[0-9a-f]{64}$ ]] || { echo 'could not read 32 random bytes' >&2; exit 1; }
printf '%s\n' "$hex" > "$tmp"
unset hex
chown "$owner:$(id -gn "$owner")" "$tmp"
chmod 0600 "$tmp"
mv -n "$tmp" "$key"
[[ -e $tmp ]] && { echo "$key appeared meanwhile; not overwriting" >&2; exit 1; }
trap - EXIT
echo "created $key (0600, $owner)"
