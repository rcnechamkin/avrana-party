#!/usr/bin/env bash
# ADR 0016 phase 1 (AVR-256): Party Core, the arcade and the LAN Games fork stop running as the
# operator account and each get their own system user. Owner-run, on the appliance, as root, once,
# after a deployment that built the code releases under /opt (ops/deploy.sh):
#
#   sudo bash /opt/avrana-party/current/ops/migrate-service-users.sh --dry-run
#   sudo bash /opt/avrana-party/current/ops/migrate-service-users.sh
#   sudo bash /opt/avrana-party/current/ops/migrate-service-users.sh --reverse <backup directory>
#
# It, in order:
#   1. refuses unless: both code releases exist and are not writable by anyone but root; both carry
#      the key loader that accepts a systemd credential (AVR-253); the Games release carries its
#      phase-1 unit; the arcade's libretro core and the fork's virtualenv are where they are today;
#      no game session is live;
#   2. records the before-state (installed unit files and drop-ins, owners and modes of the key
#      store and the device store) under /var/backups/avrana-party/service-users-<UTC>/;
#   3. creates the groups avrana-front and avrana-games and the users avrana-party, avrana-arcade
#      and avrana-lan-games (system users, no login shell, no home), adds www-data and avrana-party
#      to avrana-front, and gives avrana-arcade the device groups the arcade already uses;
#   4. stops the three services; re-owns the key store and the device store to avrana-party;
#      copies the libretro core and the fork's virtualenv, as they are on this machine, to
#      root-owned locations under /opt (nothing is downloaded) and prints the core's sha256;
#      moves the fork's data/ into its state directory; installs the units and drop-ins from the
#      releases; starts the services;
#   5. runs the boundary checker for phase 1 and prints its verdict.
# Run again, it changes nothing that is already in place. --reverse puts the recorded unit files
# and ownerships back and restarts; the users, groups and /opt copies stay (they grant nothing).
# docs/runbooks/service-users-migration.md is the procedure, including what to check on a phone.
# NEVER run by an agent or in CI against a real host: --dry-run is the only mode the tests use.
set -Eeuo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

main() {

party_release=${AVRANA_PARTY_RELEASES:-/opt/avrana-party}/current
games_release=${AVRANA_GAMES_RELEASES:-/opt/avrana-party-games}/current
party_checkout=${AVRANA_PARTY_CHECKOUT:-/home/cody/avrana-party}
games_checkout=${AVRANA_GAMES_CHECKOUT:-/home/cody/avrana-party-games}
core_source=${AVRANA_ARCADE_CORE_SOURCE:-$party_checkout/arcade/cores/mame2010_libretro.so}
core_target=${AVRANA_ARCADE_CORE_TARGET:-/opt/avrana-arcade/cores/mame2010_libretro.so}
venv_source=${AVRANA_GAMES_VENV_SOURCE:-/home/cody/LAN-Games/.venv}
venv_target=${AVRANA_GAMES_VENV_TARGET:-/opt/avrana-party-games/venv}
key_dir=${AVRANA_PARTY_KEY_DIR:-/etc/avrana-party/game-keys}
device_store=${AVRANA_DEVICE_STORE:-/var/lib/avrana-party-core}
games_state=${AVRANA_GAMES_STATE:-/var/lib/avrana-lan-games}
unit_dir=${AVRANA_UNIT_DIR:-/etc/systemd/system}
backup_root=${AVRANA_BACKUP_ROOT:-/var/backups/avrana-party}
party_core_url=${AVRANA_PARTY_CORE_URL:-http://127.0.0.1:8191}
party_host=${AVRANA_PARTY_HOST:-party.avrana.net}
rom=${AVRANA_ARCADE_ROM:-/srv/avrana/roms/arcade/gaunt2.zip}
units=(avrana-party-core avranaparty-arcade avranaparty-games)
# installed path (relative to $unit_dir) = source in a release
files=(
    "avrana-party-core.service=$party_release/deploy/party-core/avrana-party-core.service"
    "avranaparty-arcade.service=$party_release/arcade/avranaparty-arcade.service"
    "avranaparty-arcade.service.d/avrana-party-session.conf=$party_release/deploy/arcade/avrana-party-session.conf"
    "avranaparty-games.service=$games_release/deploy/avranaparty-games.service"
    "avranaparty-games.service.d/avrana-party-session.conf=$games_release/deploy/avrana-party-session.conf"
)

dry_run=0 reverse='' force_busy=0
die() { echo "migrate-service-users: $*" >&2; exit 1; }
log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }
# Every change goes through `run`, so a dry run prints exactly what a real run would do.
run() { if [[ $dry_run -eq 1 ]]; then echo "would run: $*"; else "$@"; fi; }

while (($#)); do
    case $1 in
        --dry-run) dry_run=1; shift ;;
        --reverse) reverse=${2:-}; [[ -n $reverse ]] || die '--reverse needs the backup directory of the run to undo'; shift 2 ;;
        --force-busy) force_busy=1; shift ;;
        -h|--help) sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown argument $1 (see --help)" ;;
    esac
done
[[ $EUID -eq 0 || $dry_run -eq 1 ]] || die 'run as root (sudo), or with --dry-run'

busy=$(curl -s -m 5 -H "Host: $party_host" "$party_core_url/party/api/state" 2>/dev/null \
    | python3 -c 'import json,sys
try:
    s = json.load(sys.stdin).get("session")
    print("busy" if s and s.get("state") in ("setup", "launching", "active", "ending") else "idle")
except Exception:
    print("unknown")' 2>/dev/null || echo unknown)
if [[ $busy == busy && $force_busy -eq 0 ]]; then die 'a game session is live; wait for the party to return home (or --force-busy)'; fi

# ---- reverse ----------------------------------------------------------------------------------
if [[ -n $reverse ]]; then
    [[ -f $reverse/ownership ]] || die "$reverse is not a backup written by this script"
    for unit in "${units[@]}"; do run systemctl stop "$unit"; done
    for entry in "${files[@]}"; do
        name=${entry%%=*}
        if [[ -f $reverse/units/$name ]]; then run install -D -m 0644 "$reverse/units/$name" "$unit_dir/$name"
        else run rm -f "$unit_dir/$name"; fi                 # it did not exist before the migration
    done
    while read -r owner group path; do run chown -R "$owner:$group" "$path"; done < "$reverse/ownership"
    if [[ -f $reverse/games-data ]]; then
        # put the fork's data/ back where the previous unit expects it
        run cp -a "$games_state/." "$(cat "$reverse/games-data")/"
    fi
    run systemctl daemon-reload
    for unit in avranaparty-games avranaparty-arcade avrana-party-core; do run systemctl start "$unit"; done
    log 'reversed: previous unit files and ownerships restored; users, groups and /opt copies left in place'
    exit 0
fi

# ---- 1. refuse unsafe states ------------------------------------------------------------------
for release in "$party_release" "$games_release"; do
    [[ -d $release/ ]] || die "$release does not exist: deploy first (ops/deploy.sh builds it)"
    loose=$(find -L "$release" \( -perm -020 -o -perm -002 \) ! -type l -print -quit)
    [[ -z $loose ]] || die "$loose is group- or world-writable; a release must be writable by root only"
    if [[ $EUID -eq 0 ]]; then
        other=$(find -L "$release" ! -user root -print -quit)
        [[ -z $other ]] || die "$other is not owned by root"
    fi
done
grep -q 'posix_acl_access' "$party_release/avrana/party/protocol.py" \
    || die 'the Party release predates the credential key loader (AVR-253); deploy a newer commit'
grep -rqs 'posix_acl_access' "$games_release/provider" "$games_release/core" \
    || die 'the Games release predates the credential key loader (AVR-253); deploy a newer commit'
for entry in "${files[@]}"; do
    [[ -f ${entry#*=} ]] || die "${entry#*=} is missing from the release (the Games half of AVR-256 must be deployed too)"
done
[[ -f $core_source ]] || die "the arcade core is not at $core_source; nothing is downloaded, set AVRANA_ARCADE_CORE_SOURCE"
[[ -x $venv_source/bin/python ]] || die "the fork's virtualenv is not at $venv_source; set AVRANA_GAMES_VENV_SOURCE"
[[ -d $key_dir ]] || die "$key_dir does not exist"

# ---- 2. before-state --------------------------------------------------------------------------
backup=$backup_root/service-users-$(date -u +%Y%m%dT%H%M%SZ)
run install -d -m 0750 "$backup" "$backup/units"
for entry in "${files[@]}"; do
    name=${entry%%=*}
    if [[ -f $unit_dir/$name ]]; then run install -D -m 0644 "$unit_dir/$name" "$backup/units/$name"; fi
done
if [[ $dry_run -eq 1 ]]; then echo "would record: owners of $key_dir and $device_store in $backup/ownership"
else
    for path in "$key_dir" "$device_store"; do
        [[ -e $path ]] && stat -c '%U %G %n' "$path" >> "$backup/ownership"
    done
fi
log "before-state: $backup"

# ---- 3. identities ----------------------------------------------------------------------------
for group in avrana-front avrana-games; do
    getent group "$group" >/dev/null || run groupadd --system "$group"
done
for user in avrana-party avrana-arcade avrana-lan-games; do
    getent passwd "$user" >/dev/null \
        || run useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$user"
done
run usermod -a -G avrana-front avrana-party
run usermod -a -G avrana-front www-data
run usermod -a -G input,video,render avrana-arcade

# ---- 4. stop, re-own, install, start ------------------------------------------------------------
for unit in "${units[@]}"; do run systemctl stop "$unit"; done

run chown -R avrana-party:avrana-party "$key_dir"
run chmod 0700 "$key_dir"
run find "$key_dir" -type f -name '*.key' -exec chmod 0600 {} +
if [[ -d $device_store ]]; then run chown -R avrana-party:avrana-party "$device_store"; fi

run install -D -o root -g root -m 0644 "$core_source" "$core_target"
log "arcade core sha256: $(sha256sum "$core_source" | cut -d' ' -f1)  ($core_source -> $core_target)"
[[ -r $rom ]] || log "WARNING: $rom is not there; the arcade's ROM audit will fail at start"
if [[ ! -d $venv_target ]]; then
    run cp -a "$venv_source" "$venv_target"
    run chown -R root:root "$venv_target"
    run chmod -R go-w "$venv_target"
fi
# The fork writes data/ (avatars, chat media, venue.json): from now on in its own state directory,
# which its unit binds over the read-only release.
if [[ -d $games_checkout/data && ! -d $games_state ]]; then
    run install -d -m 0700 -o avrana-lan-games -g avrana-lan-games "$games_state"
    run cp -a "$games_checkout/data/." "$games_state/"
    run chown -R avrana-lan-games:avrana-lan-games "$games_state"
    if [[ $dry_run -eq 0 ]]; then echo "$games_checkout/data" > "$backup/games-data"; fi
fi

for entry in "${files[@]}"; do
    run install -D -o root -g root -m 0644 "${entry#*=}" "$unit_dir/${entry%%=*}"
done
run systemctl daemon-reload
# Providers first, then the party that launches into them (as ops/deploy.sh).
for unit in avranaparty-games avranaparty-arcade avrana-party-core; do run systemctl start "$unit"; done
if [[ $dry_run -eq 1 ]]; then log 'dry run: nothing changed'; exit 0; fi
sleep 2
failed=0
for unit in "${units[@]}"; do
    systemctl is-active --quiet "$unit" || { log "$unit is NOT active: journalctl -u $unit -n 50"; failed=1; }
done

# ---- 5. verdict -------------------------------------------------------------------------------
(cd "$party_release" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.boundary --phase 1) || failed=1
if [[ $failed -eq 1 ]]; then
    log "NOT complete. To go back: sudo bash $0 --reverse $backup"
    exit 2
fi
log "phase 1 complete. Reverse, if a phone check fails: sudo bash $0 --reverse $backup"
}

main "$@"
