#!/usr/bin/env bash
# Non-production proof for ops/prepare-native-games (AVR-304; ADR 0016 sections 4, 8 and 9): the one
# owner-run step that brings an appliance that has ADR 0016 phase 1 to the state `provision-game`
# needs, on a machine with real systemd and root. Linux + systemd + root only.
#
#   sudo AVRANA_PREPARE_PROOF=1 bash experiments/native-game/prepare-proof.sh
#
# Run it in CI or on a disposable Linux machine. NEVER on the Pi: that would be an unauthorized
# change to the appliance (AGENTS.md). It refuses to start when /etc/avrana-party, /opt/avrana-party,
# /var/backups/avrana-party, the user avrana-party or the groups avrana-front / avrana-games already
# exist, so it can never eat a real installation. (A sibling of proof.sh, which proves provision-game
# and is not edited; this script calls provision-game, it never changes it.)
#
# THE STORY. It builds the host the issue describes: ADR 0016 phase 1 applied (the identities), Party
# Core running its EARLIER unit (the repository's unit with its ExecReload= and its Wants= of the
# socket unit taken out), no socket unit, and a party-core.json with no "registry" key. Then:
#   1. on that host provision-game is refused, `systemctl reload` is refused, nothing listens;
#   2. a host without the phase 1 identities is refused and nothing is changed;
#   3. --dry-run prints what would change and changes nothing; the real run says Party Core will be
#      restarted, does it, and leaves the units, the socket (/run/avrana-party/internal.sock,
#      avrana-party:avrana-games 0660) and the one added registry member of party-core.json;
#   4. a second run changes nothing and restarts nothing;
#   5. provision-game now provisions the stand-in and a full session runs over the socket;
#   6. --reverse is refused while the game is provisioned;
#   7. with a session running and the installed socket unit different from the repository's, the
#      command refuses (a restart would end the party), changes nothing, and restarts Party Core
#      only after the session has ended: stop Party Core, restart the socket, start Party Core;
#   8. the game is removed, then --reverse puts the earlier unit and party-core.json back byte for
#      byte, disables the socket, removes its node, and does not restart Party Core: the earlier
#      state is shown again;
#   9. a stopped Party Core is left stopped: it takes the socket and the registry when it starts.
#
# It CREATES (and removes again on exit, whatever happened):
#   users and groups  system user and group avrana-party (nologin, no home); groups avrana-front
#                     (members avrana-party, www-data) and avrana-games; www-data only if absent
#   /etc/avrana-party              party-core.json, game-keys/ (0700 avrana-party), games.d/
#   /opt/avrana-party              releases/ci (a copy of avrana/, contracts/, deploy/games,
#                                  deploy/party-core, ops/provision-game, ops/prepare-native-games,
#                                  one test fixture) and the symlink current
#   /etc/systemd/system            avrana-party-core.{service,socket}, avrana-game@.{socket,service},
#                                  avrana-game@standin.service.d/, the .wants symlinks
#   /var/backups/avrana-party      the before-states the command keeps
#   runtime and state              /run/avrana-games, /run/avrana-party, /run/avrana-prepare-proof,
#                                  /var/lib/avrana-party-core, /var/lib/avrana-games and
#                                  /var/lib/private/avrana-games (the DynamicUser state)
# Services it runs: avrana-party-core (the real unit, User=avrana-party) and avrana-game@standin.
#
# Output: one line per check. CHECK lines are assumptions the design depends on (a FAIL exits 1).
# OBSERVE lines record behaviour worth reading either way, among them everything the command printed.
# On failure the journal of the services is printed (the code never logs a key, ticket or cookie).
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

[[ ${AVRANA_PREPARE_PROOF:-} == 1 ]] || { echo 'set AVRANA_PREPARE_PROOF=1 (CI or a disposable machine only; never the Pi)' >&2; exit 2; }
[[ $(id -u) == 0 ]] || { echo 'run as root (sudo)' >&2; exit 2; }
command -v systemctl >/dev/null && [[ -d /run/systemd/system ]] || { echo 'systemd is not running here' >&2; exit 2; }
command -v curl >/dev/null || { echo 'curl not found' >&2; exit 2; }

repo=$(cd "$(dirname "$0")/../.." && pwd)
here=$repo/experiments/native-game
work=/run/avrana-prepare-proof
marker=/run/avrana-prepare-proof.marker
unit_dir=/etc/systemd/system
rel=/opt/avrana-party/releases/ci
tree=/opt/avrana-party/current
fixture=$rel/tests/fixtures/appliances/ci-standin.json
conf=/etc/avrana-party/party-core.json
keydir=/etc/avrana-party/game-keys
key=$keydir/standin.key
entry=/etc/avrana-party/games.d/standin.json
backups=/var/backups/avrana-party
node=/run/avrana-party/internal.sock
sock=/run/avrana-games/standin.sock
dropin_dir=$unit_dir/avrana-game@standin.service.d
party=avrana-party-core.service
psock=avrana-party-core.socket
game=avrana-game@standin.service
registry=/etc/avrana-party/games.d
fails=0

# ---- refuse to touch anything that is not ours -------------------------------------------------
# Before the trap exists: a refusal must not run the cleanup below. A marker from an earlier run of
# this script (a crash, then a re-run on the same machine) says the leftovers are ours.
if [[ ! -e $marker ]]; then
    for p in /etc/avrana-party /opt/avrana-party /var/backups/avrana-party; do
        [[ ! -e $p ]] || { echo "refusing: $p exists and this script did not create it" >&2; exit 2; }
    done
    for n in avrana-party avrana-front avrana-games; do
        ! getent passwd "$n" >/dev/null && ! getent group "$n" >/dev/null \
            || { echo "refusing: the user or group $n exists and this script did not create it" >&2; exit 2; }
    done
fi

cleanup() {
    set +e
    [[ -s "$marker.opt-mode" ]] && chmod "$(cat "$marker.opt-mode")" /opt && rm -f "$marker.opt-mode"
    systemctl stop avrana-game@standin.socket avrana-party-core.socket 2>/dev/null
    systemctl stop avrana-game@standin.service avrana-party-core.service 2>/dev/null
    systemctl disable avrana-game@standin.socket avrana-party-core.socket 2>/dev/null
    rm -f "$unit_dir"/sockets.target.wants/avrana-game@standin.socket "$unit_dir"/sockets.target.wants/avrana-party-core.socket
    rm -rf "$unit_dir"/avrana-game@.socket "$unit_dir"/avrana-game@.service "$dropin_dir" \
        "$unit_dir"/avrana-party-core.service "$unit_dir"/avrana-party-core.socket
    rm -rf /etc/avrana-party /opt/avrana-party /var/backups/avrana-party /var/lib/avrana-party-core \
        /var/lib/private/avrana-party-core /var/lib/avrana-games /var/lib/private/avrana-games \
        /run/avrana-games /run/avrana-party "$work"
    systemctl daemon-reload 2>/dev/null
    systemctl reset-failed avrana-game@standin.service avrana-party-core.service avrana-party-core.socket 2>/dev/null
    userdel avrana-party 2>/dev/null
    groupdel avrana-party 2>/dev/null
    groupdel avrana-front 2>/dev/null
    groupdel avrana-games 2>/dev/null
    if grep -qx 'www-data' "$marker" 2>/dev/null; then userdel www-data 2>/dev/null; groupdel www-data 2>/dev/null; fi
    rm -f "$marker"
    return 0
}
on_exit() {
    local rc=$?
    trap - EXIT
    set +e
    if (( rc != 0 )); then
        echo '--- journal (avrana-party-core, avrana-game@standin) ---'
        journalctl -u avrana-party-core.service -u avrana-party-core.socket -u avrana-game@standin.service \
            -u avrana-game@standin.socket --no-pager -n 120
        echo '--- end journal ---'
    fi
    cleanup
    exit $rc
}
touch "$marker"
trap on_exit EXIT
cleanup && touch "$marker"          # idempotent: a clean start even after an interrupted run

check() {  # check <name> <expected: 0|nonzero> <actual status>
    if { [[ $2 == 0 && $3 == 0 ]] || [[ $2 != 0 && $3 != 0 ]]; }; then echo "CHECK PASS  $1"
    else echo "CHECK FAIL  $1 (status $3)"; fails=$((fails + 1)); fi
}
t() {      # t <name> <0|nonzero> <command...>: run quietly, check its status
    local name=$1 want=$2; shift 2
    set +e; "$@" >/dev/null 2>&1; local s=$?; set -e
    check "$name" "$want" "$s"
}
status() { set +e; "$@" >&2; local s=$?; set -e; echo "$s"; }
capture() { set +e; out=$("$@" 2>&1); rc=$?; set -e; }      # sets $out and $rc
show() { local line; while IFS= read -r line; do echo "OBSERVE     $1: $line"; done <<<"$2"; }
sha_of() { sha256sum "$1" | cut -d' ' -f1; }                 # compared, never printed
has() { [[ $out == *"$1"* ]]; }                              # the captured output contains this text
prov() { (cd "$tree" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.provision_game "$@"); }
prep() { "$tree/ops/prepare-native-games" "$@"; }            # the wrapper, run from the release tree
driver() { python3 "$here/driver.py" --state "$work/driver.json" "$@"; }
party_status() { curl -fsS --max-time 10 -H 'Host: party.ci.test' http://127.0.0.1:8191/party/api/status; }
pid() { systemctl show -p ExecMainPID --value "$party"; }
entered() { systemctl show -p ActiveEnterTimestampMonotonic --value "$1"; }
holds() {  # Party Core is active, the socket is listening, and Party Core started after it (it was handed it)
    [[ $(systemctl is-active "$party") == active && $(systemctl is-active "$psock") == active ]] \
        && (( $(entered "$party") >= $(entered "$psock") && $(entered "$psock") > 0 ))
}
wait_ready() {  # wait_ready: Party Core active and answering on loopback (up to 30 s); $ready is 0 when it does
    ready=1
    for _ in $(seq 1 60); do
        if systemctl is-active --quiet "$party" && party_status >/dev/null 2>&1; then ready=0; break; fi
        sleep 0.5
    done
}
refused() {  # refused <name> <text the refusal must contain>: $rc is 1 and $out says why (set by `capture`)
    check "$1" 0 "$([[ $rc == 1 && $out == *"$2"* ]] && echo 0 || echo 1)"
}
accepted_line='finished; the party answered 200 (result accepted)'
accepted_count() { journalctl --sync >/dev/null 2>&1 || true; journalctl -u "$game" --no-pager 2>/dev/null | grep -cF -- "$accepted_line" || true; }
journal_has() { journalctl --sync >/dev/null 2>&1 || true; journalctl -u "$1" --no-pager 2>/dev/null | grep -qF -- "$2"; }
backup_count() { find "$backups" -mindepth 1 -maxdepth 1 -name 'native-games-*' 2>/dev/null | wc -l; }
the_backup() { find "$backups" -mindepth 1 -maxdepth 1 -name 'native-games-*' 2>/dev/null | sort | head -n1; }
conf_only_has_registry_added() {  # $1 is the earlier file: the new one is it plus exactly the registry member, byte for byte
    python3 - "$1" "$conf" <<'PY'
import json, sys
old, new = open(sys.argv[1], 'rb').read(), open(sys.argv[2], 'rb').read()
member = b',\n  "registry": "/etc/avrana-party/games.d"'
assert new.count(member) == 1, 'the registry member was not added exactly once, in the layout of the file'
assert new.replace(member, b'', 1) == old, 'something other than that member changed'
doc = json.loads(new)
assert doc['registry'] == '/etc/avrana-party/games.d', doc['registry']
assert doc['origins'] == ['http://party.ci.test'], doc['origins']
PY
}

echo "systemd $(systemctl --version | head -n1 | awk '{print $2}'), kernel $(uname -r), $(uname -m), $(python3 --version)"

# ---- a. the release tree: root-owned, read-only to every service -----------------------------------
# A hosted runner's /opt can be group- or world-writable; an appliance's is not, and the command (like
# provision-game) refuses code under a directory anyone but root can write, because root installs the
# units from it. Tighten /opt for the run, put it back after.
opt_mode=$(stat -c %a /opt); echo "$opt_mode" > "$marker.opt-mode"
echo "OBSERVE     /opt is $(stat -c '%U:%G %a' /opt) on this machine; set to 0755 for the run"
chmod 0755 /opt
install -d -m 0755 /opt/avrana-party /opt/avrana-party/releases "$rel" "$rel/deploy" "$rel/deploy/party-core" \
    "$rel/tests/fixtures/appliances" "$rel/ops"
cp -r "$repo/avrana" "$repo/contracts" "$rel/"
cp -r "$repo/deploy/games" "$rel/deploy/games"
install -m 0644 "$repo/deploy/party-core/avrana-party-core.service" "$repo/deploy/party-core/avrana-party-core.socket" \
    "$rel/deploy/party-core/"
install -m 0755 "$repo/ops/provision-game" "$rel/ops/provision-game"
install -m 0755 "$repo/ops/prepare-native-games" "$rel/ops/prepare-native-games"
cp "$repo/tests/fixtures/appliances/ci-standin.json" "$fixture"
find "$rel" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R root:root /opt/avrana-party
chmod -R u=rwX,go=rX /opt/avrana-party
ln -sfn "$rel" "$tree"
t 'the release tree is root-owned and not group or world writable' 0 \
    test -z "$(find /opt/avrana-party -not -type l \( -not -user root -o -perm /022 \) -print -quit)"
mkdir -p -m 0700 "$work"

# ---- b. a host WITHOUT the phase 1 identities is refused, and nothing is changed ------------------------
t 'this machine has none of the phase 1 identities yet' nonzero \
    bash -c 'getent passwd avrana-party || getent group avrana-front || getent group avrana-games'
capture prep --dry-run
show 'no phase 1, dry run' "$out"
refused 'a dry run without the phase 1 identities is refused (exit 1)' 'ADR 0016 phase 1 has not been applied on this host'
capture prep
show 'no phase 1' "$out"
refused 'a real run without the phase 1 identities is refused (exit 1)' 'ADR 0016 phase 1 has not been applied on this host'
check 'and says what is missing and what to run first' 0 \
    "$([[ $out == *'user avrana-party, group avrana-front, group avrana-games'* && $out == *'ops/migrate-service-users.sh'* ]] && echo 0 || echo 1)"
check 'and says nothing was changed' 0 "$(has 'nothing was changed' && echo 0 || echo 1)"
t 'it created nothing: no /etc/avrana-party, no backups, no unit, no socket node' nonzero \
    test -e /etc/avrana-party -o -e "$backups" -o -e "$unit_dir/avrana-party-core.service" -o -e "$unit_dir/$psock" -o -e "$node"

# ---- c. identities, as ADR 0016 phase 1 (ops/migrate-service-users.sh) ---------------------------------
for g in avrana-front avrana-games; do groupadd --system "$g"; done
useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin avrana-party
if ! getent passwd www-data >/dev/null; then
    useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin www-data
    echo www-data >> "$marker"
fi
usermod -a -G avrana-front avrana-party
usermod -a -G avrana-front www-data
install -d -m 0755 -o root -g root /etc/avrana-party
install -d -m 0700 -o avrana-party -g avrana-party "$keydir"          # phase 1 made the key store

# ---- d. the EARLIER host: Party Core on its earlier unit, no socket unit, no registry key ------------------
# The earlier unit is derived from the repository's, not committed beside it: the same file without the
# ExecReload= line and without the Wants= and After= of the socket unit.
sed -e '/^ExecReload=/d' -e '/^Wants=avrana-party-core\.socket$/d' \
    -e 's/^After=network\.target avrana-party-core\.socket$/After=network.target/' \
    "$repo/deploy/party-core/avrana-party-core.service" > "$work/earlier.service"
t 'the earlier unit has no ExecReload= and does not mention the socket unit in any dependency' nonzero \
    grep -Eq '^(ExecReload|Wants|Requires|BindsTo)=|^After=.*avrana-party-core\.socket' "$work/earlier.service"
t 'the earlier unit differs from the repository unit' nonzero cmp -s "$work/earlier.service" "$repo/deploy/party-core/avrana-party-core.service"
install -m 0644 "$work/earlier.service" "$unit_dir/avrana-party-core.service"
systemctl daemon-reload
# provision-game's own status query sends the first of `hosts` as its Host header; it needs exactly one origin.
cat > "$conf" <<'JSON'
{
  "hosts": ["party.ci.test"],
  "origins": ["http://party.ci.test"],
  "secure_cookie": false,
  "games": {},
  "status": {
    "units": ["avrana-party-core"],
    "optional_units": [],
    "manifest": "/nonexistent/deployment.json",
    "party_checkout": "/nonexistent/party",
    "games_checkout": "/nonexistent/games",
    "web_root": "/nonexistent/web",
    "certificate": "/nonexistent/fullchain.pem"
  }
}
JSON
chown root:avrana-party "$conf"
chmod 0640 "$conf"                                    # a mode and an owner the command has to keep
cp -p "$conf" "$work/party-core.json.earlier"
conf_meta=$(stat -c '%a %U:%G' "$conf")
t 'the earlier party-core.json is 0640 root:avrana-party and has no registry key' 0 \
    bash -c 'test "$(stat -c "%a %U:%G" "$1")" = "640 root:avrana-party" && ! grep -q registry "$1"' _ "$conf"
systemctl start "$party"
wait_ready
t 'Party Core is active and answers /party/api/status on loopback' 0 test "$ready" = 0
pid_earlier=$(pid)
since_earlier=$(entered "$party")
t 'Party Core runs without a socket unit: none is installed, loaded or listening, and there is no node' nonzero \
    test -e "$unit_dir/$psock" -o -e "$node"
t 'the earlier unit has no ExecReload= loaded (CanReload=no)' 0 test "$(systemctl show -p CanReload --value "$party")" = no
t 'systemctl reload avrana-party-core is refused by the earlier unit' nonzero systemctl reload "$party"
t 'Party Core is still active after the refused reload' 0 systemctl is-active --quiet "$party"
capture prov standin --appliance "$fixture"
show 'provision-game on the earlier host' "$out"
refused 'provision-game is refused on the earlier host: party-core.json names no registry' 'does not name the registry directory'
t 'and created nothing (no registry entry, no key, no game units, no games.d)' nonzero \
    test -e "$entry" -o -e "$key" -o -e "$registry" -o -e "$unit_dir/avrana-game@.socket"
sha_unit_earlier=$(sha_of "$unit_dir/$party")
sha_conf_earlier=$(sha_of "$conf")

# ---- e. --dry-run: every file and unit it would change, and nothing changed --------------------------------
capture prep --dry-run
show 'dry run' "$out"
check 'a dry run exits 0' 0 "$rc"
check 'it says Party Core will be restarted, and that a restart ends the party' 0 \
    "$(has 'Party Core: will be restarted (a restart ends the party)' && echo 0 || echo 1)"
check 'it names the service unit, the socket unit and party-core.json it would change' 0 \
    "$(has "$unit_dir/$party" && has "$unit_dir/$psock" && has "$conf" && echo 0 || echo 1)"
check 'it names the systemctl steps: daemon-reload, stop, enable --now the socket, start' 0 \
    "$(has 'systemctl daemon-reload' && has 'systemctl stop avrana-party-core.service' \
        && has 'systemctl enable --now avrana-party-core.socket' && has 'systemctl start avrana-party-core.service' && echo 0 || echo 1)"
check 'it says where the before-state would be kept, and that nothing changed' 0 \
    "$(has "$backups/native-games-" && has 'dry run: nothing changed' && echo 0 || echo 1)"
t 'a dry run changed no file (unit, party-core.json), installed no socket unit, kept no backup' 0 \
    bash -c 'test "$(sha256sum "$1" | cut -d" " -f1)" = "$3" && test "$(sha256sum "$2" | cut -d" " -f1)" = "$4" && ! test -e "$5" && ! test -e "$6"' _ \
    "$unit_dir/$party" "$conf" "$sha_unit_earlier" "$sha_conf_earlier" "$unit_dir/$psock" "$backups"
t 'a dry run enabled nothing and started nothing: no socket node, the socket unit is not enabled' nonzero \
    bash -c 'test -e "$1" || systemctl is-enabled --quiet "$2"' _ "$node" "$psock"
t 'a dry run did not touch Party Core (the same process, never restarted)' 0 test "$(pid)" = "$pid_earlier" -a "$(entered "$party")" = "$since_earlier"

# ---- f. the real run: restart Party Core, install the units, enable the socket, set the registry ------------
capture prep
show 'prepare-native-games' "$out"
check 'the command exits 0' 0 "$rc"
statement=$(grep -n 'Party Core: will be restarted' <<<"$out" | head -n1 | cut -d: -f1 || true)
checked=$(grep -n '^checks:' <<<"$out" | head -n1 | cut -d: -f1 || true)
check 'it said Party Core would be restarted before it reported any change or check' 0 \
    "$([[ -n $statement && -n $checked && $statement -lt $checked ]] && echo 0 || echo 1)"
check 'it says where the before-state is, and how to reverse' 0 "$(has 'Reverse, if a check fails: sudo ops/prepare-native-games --reverse' && echo 0 || echo 1)"
t 'the installed Party Core unit is the repository unit, byte for byte (it has ExecReload=)' 0 \
    cmp -s "$repo/deploy/party-core/avrana-party-core.service" "$unit_dir/$party"
t 'the installed socket unit is the repository unit, byte for byte' 0 cmp -s "$repo/deploy/party-core/avrana-party-core.socket" "$unit_dir/$psock"
t 'the socket unit is enabled' 0 systemctl is-enabled --quiet "$psock"
t 'the socket unit is active (listening)' 0 systemctl is-active --quiet "$psock"
t "$node is a socket, avrana-party:avrana-games 0660" 0 test "$(stat -c '%F %a %U:%G' "$node")" = 'socket 660 avrana-party:avrana-games'
t 'systemd has the new unit loaded: CanReload=yes, and nothing needs a daemon-reload' 0 \
    bash -c 'test "$(systemctl show -p CanReload --value "$1")" = yes && test "$(systemctl show -p NeedDaemonReload --value "$1")" = no && test "$(systemctl show -p NeedDaemonReload --value "$2")" = no' _ "$party" "$psock"
t 'party-core.json is the earlier file plus exactly the registry member (every other byte identical)' 0 conf_only_has_registry_added "$work/party-core.json.earlier"
t 'party-core.json kept its mode and owner' 0 test "$(stat -c '%a %U:%G' "$conf")" = "$conf_meta"
wait_ready
t 'Party Core was restarted (a new process), is active and answers on loopback' 0 \
    bash -c 'test "$1" = 0 && test "$2" != "$3"' _ "$ready" "$(pid)" "$pid_earlier"
t 'Party Core was handed the socket: it started after the socket began listening' 0 holds
pid_prepared=$(pid)
since_prepared=$(entered "$party")
t 'systemctl reload avrana-party-core now succeeds' 0 systemctl reload "$party"
t 'Party Core is the same process after the reload (a SIGHUP, not a restart), still active' 0 \
    bash -c 'systemctl is-active --quiet "$1" && test "$(systemctl show -p ExecMainPID --value "$1")" = "$2"' _ "$party" "$pid_prepared"
bdir=$(the_backup)
check 'one before-state was kept' 0 "$([[ $(backup_count) == 1 && -n $bdir ]] && echo 0 || echo 1)"
t 'it holds the previous unit file, byte for byte' 0 cmp -s "$work/earlier.service" "$bdir/units/$party"
t 'it holds the previous party-core.json, byte for byte' 0 cmp -s "$work/party-core.json.earlier" "$bdir/party-core.json"
t 'it has a state.json, and the directory is private (0750)' 0 bash -c 'test -s "$1/state.json" && test "$(stat -c %a "$1")" = 750' _ "$bdir"
t 'there was no socket unit to keep' nonzero test -e "$bdir/units/$psock"
sha_unit_prepared=$(sha_of "$unit_dir/$party")
sha_sunit_prepared=$(sha_of "$unit_dir/$psock")
sha_conf_prepared=$(sha_of "$conf")

# ---- g. a second run: nothing to change, nothing restarted -----------------------------------------------------
capture prep
show 'second run' "$out"
check 'a second run exits 0 and says there is nothing to change' 0 "$([[ $rc == 0 ]] && has 'nothing to change' && echo 0 || echo 1)"
check 'it says Party Core will not be restarted because it already holds the socket' 0 \
    "$(has 'Party Core: will not be restarted: it already holds the socket' && echo 0 || echo 1)"
t 'it changed no file' 0 bash -c 'test "$(sha256sum "$1" | cut -d" " -f1)" = "$4" && test "$(sha256sum "$2" | cut -d" " -f1)" = "$5" && test "$(sha256sum "$3" | cut -d" " -f1)" = "$6"' _ \
    "$unit_dir/$party" "$unit_dir/$psock" "$conf" "$sha_unit_prepared" "$sha_sunit_prepared" "$sha_conf_prepared"
t 'it restarted nothing: Party Core is the same process, started at the same time' 0 \
    test "$(pid)" = "$pid_prepared" -a "$(entered "$party")" = "$since_prepared"
check 'it kept no new before-state' 0 "$([[ $(backup_count) == 1 ]] && echo 0 || echo 1)"

# ---- h. provision-game works now, and a real session runs over the socket ----------------------------------------
capture prov standin --appliance "$fixture" --dry-run
show 'provision-game --dry-run' "$out"
check 'provision-game --dry-run is not refused and would create the key' 0 "$([[ $rc == 0 && $out == *'would change key'* ]] && echo 0 || echo 1)"
capture prov standin --appliance "$fixture"
show 'provision-game' "$out"
check 'provision-game provisions the stand-in (exit 0): the registry key and the reload are in place' 0 "$rc"
t 'the registry entry exists' 0 test -s "$entry"
t 'Party Core was reloaded, not restarted, by provisioning (the same process)' 0 test "$(pid)" = "$pid_prepared"
c0=$(accepted_count)
s=$(status driver)
check 'a full session over the socket: two phones, launch, redeems, finish with a result, results, home' 0 "$s"
t 'the game received the signed launch (journal)' 0 journal_has "$game" 'launched ('
check 'Party Core accepted the result on the internal socket it was handed (one more accepted line)' 0 \
    "$([[ $(accepted_count) == $((c0 + 1)) ]] && echo 0 || echo 1)"
t 'Party Core was still not restarted' 0 test "$(pid)" = "$pid_prepared"

# ---- i. --reverse is refused while a native game is provisioned ----------------------------------------------------
capture prep --reverse
show 'reverse with a game provisioned' "$out"
refused 'reverse is refused while the stand-in is provisioned (exit 1), naming it' 'native games are provisioned here (standin)'
check 'and says what to do first' 0 "$(has 'provision-game <slug> --remove' && echo 0 || echo 1)"
capture prep --reverse --dry-run
refused 'a dry-run reverse is refused as well' 'native games are provisioned here (standin)'
t 'the refused reverse changed nothing (units, party-core.json, the socket, Party Core)' 0 \
    bash -c 'test "$(sha256sum "$1" | cut -d" " -f1)" = "$4" && test "$(sha256sum "$2" | cut -d" " -f1)" = "$5" && test "$(sha256sum "$3" | cut -d" " -f1)" = "$6" && systemctl is-active --quiet "$7" && test "$(systemctl show -p ExecMainPID --value "$8")" = "$9"' _ \
    "$unit_dir/$party" "$unit_dir/$psock" "$conf" "$sha_unit_prepared" "$sha_sunit_prepared" "$sha_conf_prepared" "$psock" "$party" "$pid_prepared"

# ---- j. a session is running: no restart; after it ends, the restart is done ------------------------------------------
# The installed socket unit is edited so that it differs from the repository's (a directive, not a
# comment): applying the repository's takes a restart of the socket, which hands Party Core a new
# socket, which takes a restart of Party Core, which ends the party. With a session running the
# command must refuse and change nothing. (systemd itself refuses to restart a socket under a
# running service: the command stops Party Core, restarts the socket and starts Party Core.)
s=$(status driver --hold)
check 'a session is launched and held live' 0 "$s"
sed -i 's/^Description=.*/Description=Avrana Party Core internal socket (edited on the host)/' "$unit_dir/$psock"
systemctl daemon-reload
sha_edited=$(sha_of "$unit_dir/$psock")
sleep 7                                   # longer than Party Core's status cache: the launch must be visible to one question
capture prep --dry-run
show 'dry run during a session' "$out"
refused 'a dry run during a session reports the refusal a real run would make (exit 1)' 'a game session is running (standin)'
capture prep
show 'run during a session' "$out"
refused 'a run during a session is refused (exit 1): a game session is running (standin)' 'a game session is running (standin)'
check 'and says nothing was changed' 0 "$(has 'nothing was changed' && echo 0 || echo 1)"
t 'the edited socket unit is still installed: nothing was put back' 0 test "$(sha_of "$unit_dir/$psock")" = "$sha_edited"
t 'Party Core was not restarted: the same process, still active' 0 test "$(pid)" = "$pid_prepared" -a "$(entered "$party")" = "$since_prepared"
t 'the socket was not restarted (the node is still there and the socket is active)' 0 bash -c 'test -S "$1" && systemctl is-active --quiet "$2"' _ "$node" "$psock"
t 'no second before-state was kept by the refused run' 0 test "$(backup_count)" = 1
s=$(status driver --end)
check 'the host ends the held session from Party Home' 0 "$s"
sleep 7                                   # longer than Party Core's status cache: the end must be visible
capture prep
show 'run after the session' "$out"
check 'the run succeeds once the session has ended (exit 0)' 0 "$rc"
check 'it said Party Core would be restarted because the socket unit changes' 0 \
    "$(has 'Party Core: will be restarted (a restart ends the party): the socket unit changes' && echo 0 || echo 1)"
t 'the repository socket unit is installed again, byte for byte' 0 cmp -s "$repo/deploy/party-core/avrana-party-core.socket" "$unit_dir/$psock"
wait_ready
t 'Party Core was restarted (a new process), is active and answers' 0 bash -c 'test "$1" = 0 && test "$2" != "$3"' _ "$ready" "$(pid)" "$pid_prepared"
t 'Party Core was handed the restarted socket' 0 holds
t "$node is a socket, avrana-party:avrana-games 0660 again" 0 test "$(stat -c '%F %a %U:%G' "$node")" = 'socket 660 avrana-party:avrana-games'
check 'the earlier before-state was added to, not replaced: still one directory' 0 "$([[ $(backup_count) == 1 ]] && echo 0 || echo 1)"
t 'and it still holds the first unit file it replaced' 0 cmp -s "$work/earlier.service" "$bdir/units/$party"
pid_prepared=$(pid)
c0=$(accepted_count)
s=$(status driver)
check 'a full session works over the restarted socket' 0 "$s"
check 'Party Core accepted its result (one more accepted line)' 0 "$([[ $(accepted_count) == $((c0 + 1)) ]] && echo 0 || echo 1)"
sleep 7                                   # longer than Party Core's status cache: remove must not see the finished session as live

# ---- k. remove the game, then reverse: the earlier state is back ------------------------------------------------------------
capture prov standin --appliance "$fixture" --remove
show 'remove' "$out"
check 'provision-game --remove exits 0' 0 "$rc"
capture prep --reverse --dry-run
show 'reverse, dry run' "$out"
check 'a dry-run reverse exits 0 and says what it would restore, remove and run' 0 \
    "$([[ $rc == 0 ]] && has "restore $unit_dir/$party" && has "remove $unit_dir/$psock" && has "restore $conf" \
        && has "systemctl disable --now $psock" && has 'dry run: nothing changed' && echo 0 || echo 1)"
t 'the dry-run reverse changed nothing' 0 bash -c 'test "$(sha256sum "$1" | cut -d" " -f1)" = "$3" && test -e "$2" && systemctl is-active --quiet "$4"' _ \
    "$unit_dir/$party" "$unit_dir/$psock" "$sha_unit_prepared" "$psock"
capture prep --reverse
show 'reverse' "$out"
check 'the reverse exits 0' 0 "$rc"
check 'it says Party Core was not restarted' 0 "$(has 'Party Core was not restarted' && echo 0 || echo 1)"
t 'the earlier Party Core unit is back, byte for byte' 0 cmp -s "$work/earlier.service" "$unit_dir/$party"
t 'the earlier party-core.json is back, byte for byte (no registry key)' 0 cmp -s "$work/party-core.json.earlier" "$conf"
t 'party-core.json kept its mode and owner through the reverse' 0 test "$(stat -c '%a %U:%G' "$conf")" = "$conf_meta"
t 'the socket unit file is gone' nonzero test -e "$unit_dir/$psock"
t 'the socket unit is not enabled and not active' nonzero bash -c 'systemctl is-enabled --quiet "$1" || systemctl is-active --quiet "$1"' _ "$psock"
t 'the socket node is gone' nonzero test -e "$node"
t 'systemd has the earlier unit loaded again: CanReload=no' 0 test "$(systemctl show -p CanReload --value "$party")" = no
t 'systemctl reload is refused again, as on the earlier host' nonzero systemctl reload "$party"
t 'Party Core was not restarted by the reverse: the same process, still active' 0 test "$(pid)" = "$pid_prepared"
capture prov standin --appliance "$fixture"
show 'provision-game after the reverse' "$out"
refused 'provision-game is refused again for the missing registry key: the earlier state' 'does not name the registry directory'
t 'the before-state is marked reversed, and the file this reverse replaced was kept' 0 \
    bash -c 'python3 -c "import json,sys; assert json.load(open(sys.argv[1]))[\"reversed\"]" "$1/state.json" && test -s "$1/replaced/units/$2"' _ "$bdir" "$party"
capture prep --reverse
show 'second reverse' "$out"
check 'a second reverse has nothing to reverse (exit 0)' 0 "$([[ $rc == 0 ]] && has 'nothing to reverse' && echo 0 || echo 1)"

# ---- l. a stopped Party Core is left stopped ---------------------------------------------------------------------------------
# Maintenance: Party Core is stopped (it is not a session, and the command does not start it). It takes the
# socket and the registry when it next starts.
systemctl restart "$party"                # the earlier unit is loaded: it runs without a socket, as on the earlier host
wait_ready
systemctl stop "$party"
t 'Party Core is stopped' nonzero systemctl is-active --quiet "$party"
capture prep
show 'prepare, Party Core stopped' "$out"
check 'it exits 0 and says Party Core will not be restarted: it is not running' 0 \
    "$([[ $rc == 0 ]] && has 'Party Core: will not be restarted: it is not running (inactive)' && echo 0 || echo 1)"
t 'it did not start Party Core' nonzero systemctl is-active --quiet "$party"
t 'the socket is enabled and listening, ready for Party Core to take' 0 bash -c 'systemctl is-enabled --quiet "$1" && systemctl is-active --quiet "$1"' _ "$psock"
t "$node is a socket, avrana-party:avrana-games 0660" 0 test "$(stat -c '%F %a %U:%G' "$node")" = 'socket 660 avrana-party:avrana-games'
t 'party-core.json has the registry member and nothing else changed' 0 conf_only_has_registry_added "$work/party-core.json.earlier"
check 'a new before-state was kept for this prepared period (the earlier one was reversed)' 0 "$([[ $(backup_count) == 2 ]] && echo 0 || echo 1)"
systemctl start "$party"                  # a start by hand: it takes the socket from the socket unit
wait_ready
t 'Party Core started by hand answers, and was handed the socket' 0 bash -c 'test "$1" = 0' _ "$ready"
t 'Party Core holds the socket (it started after the socket began listening)' 0 holds
pid_late=$(pid)
capture prep
show 'second run, Party Core started by hand' "$out"
check 'it has nothing to change and restarts nothing' 0 "$([[ $rc == 0 ]] && has 'nothing to change' && echo 0 || echo 1)"
t 'Party Core is the same process' 0 test "$(pid)" = "$pid_late"
capture prep --reverse
show 'reverse of the second period' "$out"
check 'the second before-state is reversed too (exit 0)' 0 "$rc"
t 'the earlier unit and party-core.json are back again' 0 bash -c 'cmp -s "$1" "$2" && cmp -s "$3" "$4"' _ "$work/earlier.service" "$unit_dir/$party" "$work/party-core.json.earlier" "$conf"
t 'Party Core is still running and was not restarted by the reverse' 0 bash -c 'systemctl is-active --quiet "$1" && test "$(systemctl show -p ExecMainPID --value "$1")" = "$2"' _ "$party" "$pid_late"

# ---- m. summary ---------------------------------------------------------------------------------------------------------------------
echo "failed checks: $fails"
[[ $fails == 0 ]]
