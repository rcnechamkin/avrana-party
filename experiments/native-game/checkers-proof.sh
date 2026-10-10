#!/usr/bin/env bash
# Non-production proof for AVR-238 (native Checkers): the Games repository's Checkers, provisioned by
# the REAL `provision-game checkers` against the REAL appliance profile, launched by Party Core over
# its Unix socket, played to a natural end by two "phones", and judged by the boundary checker.
# Linux + systemd + root only.
#
#   sudo AVRANA_CHECKERS_PROOF=1 AVRANA_GAMES_REPO=/path/to/avrana-party-games \
#        bash experiments/native-game/checkers-proof.sh
#
# Run it in CI or on a disposable Linux machine. NEVER on the Pi: that would be an unauthorized
# change to the appliance (AGENTS.md). It refuses to start when /etc/avrana-party, /opt/avrana-party,
# /opt/avrana-party-games, /var/backups/avrana-party, the user avrana-party or the groups avrana-front
# / avrana-games already exist, so it can never eat a real installation. (A sibling of proof.sh and
# prepare-proof.sh, which prove provision-game and prepare-native-games with the generic stand-in
# game and are not edited; this script calls both tools, it never changes them.)
#
# THE STORY, on a clean host, in the order the owner will do it:
#   1. ADR 0016 phase 1 (the identities), Party Core on its EARLIER unit, the Party release installed
#      root-owned at /opt/avrana-party/releases/ci -> current, and the Games checkout installed
#      root-owned at /opt/avrana-party-games/releases/ci -> current (the real grant's working
#      directory is /opt/avrana-party-games/current);
#   2. ops/prepare-native-games brings the host to the state provision-game needs (AVR-304);
#   3. `provision-game checkers --appliance contracts/appliances/avrana-pi4.json` (the real profile
#      of the release tree): dry run changes nothing, the run exits 0, a second run is idempotent;
#   4. avrana-game@checkers is socket-activated, a DynamicUser, holds its key by LoadCredential= and
#      was handed AVRANA_PARTY_ORIGIN; Party Core offers it from its contract;
#   5. session 1 through Party Core's public HTTP API and the game's Unix socket (checkers-driver.py):
#      two phones, launch, tickets, redeems, each seat sees only its own controls, strangers
#      refused, a mid-game reconnect, a COMPLETE game played with legal moves to its natural end,
#      the signed `ended` with an avrana.game-result/v1 accepted by Party Core, the standings shown
#      to the party;
#   6. session 2 that the Host ends from Party (POST /party/api/session/end): over for both phones,
#      the game refuses their tokens and then exits idle (it holds no session);
#   7. `python3 -m avrana.ops.boundary --phase 2` with Checkers provisioned;
#   8. `provision-game checkers --remove` leaves nothing; the cleanup restores the host.
#
# It CREATES (and removes again on exit, whatever happened):
#   users and groups  system user and group avrana-party (nologin, no home); groups avrana-front
#                     (members avrana-party, www-data) and avrana-games; www-data only if absent
#   /etc/avrana-party              party-core.json, games.d/, game-keys/ (0700 avrana-party)
#   /opt/avrana-party              releases/ci (a copy of avrana/, contracts/, deploy/games,
#                                  deploy/party-core, ops/provision-game, ops/prepare-native-games)
#                                  and the symlink current
#   /opt/avrana-party-games        releases/ci (a copy of checkers/, core/, web/ of the Games
#                                  checkout) and the symlink current
#   /etc/systemd/system            avrana-party-core.{service,socket}, avrana-game@.{socket,service},
#                                  avrana-game@checkers.service.d/, the .wants symlinks
#   /var/backups/avrana-party      the before-state prepare-native-games keeps
#   runtime and state              /run/avrana-games, /run/avrana-party, /run/avrana-checkers-proof,
#                                  /var/lib/avrana-party-core, /var/lib/avrana-games and
#                                  /var/lib/private/avrana-games (the DynamicUser state)
# Services it runs: avrana-party-core (the real unit, User=avrana-party) and avrana-game@checkers.
#
# Output: one line per check. CHECK lines are assumptions the design depends on (a FAIL exits 1).
# OBSERVE lines record behaviour worth reading either way. On failure the journal of the two
# services is printed (the code never logs a key, ticket, token or cookie).
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

[[ ${AVRANA_CHECKERS_PROOF:-} == 1 ]] || { echo 'set AVRANA_CHECKERS_PROOF=1 (CI or a disposable machine only; never the Pi)' >&2; exit 2; }
[[ $(id -u) == 0 ]] || { echo 'run as root (sudo)' >&2; exit 2; }
command -v systemctl >/dev/null && [[ -d /run/systemd/system ]] || { echo 'systemd is not running here' >&2; exit 2; }
command -v curl >/dev/null || { echo 'curl not found' >&2; exit 2; }
games_repo=${AVRANA_GAMES_REPO:-}
[[ -n $games_repo && -f $games_repo/checkers/__main__.py && -f $games_repo/core/party_protocol.py && -f $games_repo/web/avrana-party-bridge.js ]] \
    || { echo 'set AVRANA_GAMES_REPO to a checkout of avrana-party-games (checkers/, core/, web/)' >&2; exit 2; }
games_repo=$(cd "$games_repo" && pwd)

repo=$(cd "$(dirname "$0")/../.." && pwd)
here=$repo/experiments/native-game
work=/run/avrana-checkers-proof
marker=/run/avrana-checkers-proof.marker
unit_dir=/etc/systemd/system
rel=/opt/avrana-party/releases/ci
tree=/opt/avrana-party/current
grel=/opt/avrana-party-games/releases/ci
gtree=/opt/avrana-party-games/current
appliance=$tree/contracts/appliances/avrana-pi4.json      # the REAL profile of the release tree
conf=/etc/avrana-party/party-core.json
keydir=/etc/avrana-party/game-keys
key=$keydir/checkers.key
entry=/etc/avrana-party/games.d/checkers.json
backups=/var/backups/avrana-party
node=/run/avrana-party/internal.sock
sock=/run/avrana-games/checkers.sock
dropin_dir=$unit_dir/avrana-game@checkers.service.d
party=avrana-party-core.service
psock=avrana-party-core.socket
game=avrana-game@checkers.service
gsock=avrana-game@checkers.socket
fails=0

# ---- refuse to touch anything that is not ours -------------------------------------------------
# Before the trap exists: a refusal must not run the cleanup below. A marker from an earlier run
# of this script (a crash, then a re-run on the same machine) says the leftovers are ours.
if [[ ! -e $marker ]]; then
    for p in /etc/avrana-party /opt/avrana-party /opt/avrana-party-games /var/backups/avrana-party; do
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
    systemctl stop "$gsock" "$psock" 2>/dev/null
    systemctl stop "$game" "$party" 2>/dev/null
    systemctl disable "$gsock" "$psock" 2>/dev/null
    rm -f "$unit_dir"/sockets.target.wants/"$gsock" "$unit_dir"/sockets.target.wants/"$psock"
    rm -rf "$unit_dir"/avrana-game@.socket "$unit_dir"/avrana-game@.service "$dropin_dir" \
        "$unit_dir/$party" "$unit_dir/$psock"
    rm -rf /etc/avrana-party /opt/avrana-party /opt/avrana-party-games /var/backups/avrana-party \
        /var/lib/avrana-party-core /var/lib/private/avrana-party-core /var/lib/avrana-games \
        /var/lib/private/avrana-games /run/avrana-games /run/avrana-party "$work"
    systemctl daemon-reload 2>/dev/null
    systemctl reset-failed "$game" "$party" "$psock" 2>/dev/null
    userdel avrana-party 2>/dev/null
    groupdel avrana-party 2>/dev/null
    groupdel avrana-front 2>/dev/null
    groupdel avrana-games 2>/dev/null
    if grep -qx 'www-data' "$marker" 2>/dev/null; then userdel www-data 2>/dev/null; groupdel www-data 2>/dev/null; fi
    rm -f "$marker"
    return 0
}
leftovers() {  # what the cleanup should have removed and has not (empty when the host is restored)
    local p
    for p in /etc/avrana-party /opt/avrana-party /opt/avrana-party-games /var/backups/avrana-party /run/avrana-games \
        /run/avrana-party "$work" /var/lib/avrana-games /var/lib/private/avrana-games "$unit_dir/$party" "$unit_dir/$psock" \
        "$unit_dir/avrana-game@.socket" "$unit_dir/avrana-game@.service" "$dropin_dir"; do
        [[ ! -e $p ]] || echo "$p"
    done
    for p in avrana-party; do getent passwd "$p" >/dev/null && echo "user $p"; done
    for p in avrana-party avrana-front avrana-games; do getent group "$p" >/dev/null && echo "group $p"; done
    return 0
}
on_exit() {
    local rc=$?
    trap - EXIT
    set +e
    if (( rc != 0 )); then
        echo '--- journal (avrana-party-core, avrana-game@checkers) ---'
        journalctl -u "$party" -u "$psock" -u "$game" -u "$gsock" --no-pager -n 150
        echo '--- end journal ---'
    fi
    cleanup
    local left
    left=$(leftovers | paste -sd' ')
    if [[ -z $left ]]; then echo 'CHECK PASS  the cleanup restored the host: no user, group, directory or unit of this proof is left'
    else echo "CHECK FAIL  the cleanup left: $left"; (( rc == 0 )) && rc=1; fi
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
driver() { python3 "$here/checkers-driver.py" "$@"; }
party_status() { curl -fsS --max-time 10 -H 'Host: party.ci.test' http://127.0.0.1:8191/party/api/status; }
pid() { systemctl show -p ExecMainPID --value "$party"; }
entered() { systemctl show -p ActiveEnterTimestampMonotonic --value "$1"; }
wait_ready() {  # Party Core active and answering on loopback (up to 30 s); $ready is 0 when it does
    ready=1
    for _ in $(seq 1 60); do
        if systemctl is-active --quiet "$party" && party_status >/dev/null 2>&1; then ready=0; break; fi
        sleep 0.5
    done
}
refused() {  # refused <name> <text the refusal must contain>: $rc is 1 and $out says why (set by `capture`)
    check "$1" 0 "$([[ $rc == 1 && $out == *"$2"* ]] && echo 0 || echo 1)"
}
journal_has() { journalctl --sync >/dev/null 2>&1 || true; journalctl -u "$1" --no-pager 2>/dev/null | grep -qF -- "$2"; }
journal_count() { journalctl --sync >/dev/null 2>&1 || true; journalctl -u "$1" --no-pager 2>/dev/null | grep -cF -- "$2" || true; }
run_driver() {  # run_driver <name> [driver args]: the driver's own lines are the evidence
    local name=$1 s out_file="$work/driver.out"; shift
    set +e; driver "$@" >"$out_file" 2>&1; s=$?; set -e
    show "driver ($name)" "$(cat "$out_file")"
    check "$name" 0 "$s"
}

echo "systemd $(systemctl --version | head -n1 | awk '{print $2}'), kernel $(uname -r), $(uname -m), $(python3 --version)"

# ---- a. the release trees: root-owned, read-only to every service ----------------------------------
# A hosted runner's /opt can be group- or world-writable; an appliance's is not, and provision-game
# refuses code under a directory anyone but root can write. Tighten it for the run, put it back after.
opt_mode=$(stat -c %a /opt); echo "$opt_mode" > "$marker.opt-mode"
echo "OBSERVE     /opt is $(stat -c '%U:%G %a' /opt) on this machine; set to 0755 for the run"
chmod 0755 /opt
install -d -m 0755 /opt/avrana-party /opt/avrana-party/releases "$rel" "$rel/deploy" "$rel/deploy/party-core" "$rel/ops"
cp -r "$repo/avrana" "$repo/contracts" "$rel/"
cp -r "$repo/deploy/games" "$rel/deploy/games"
install -m 0644 "$repo/deploy/party-core/avrana-party-core.service" "$repo/deploy/party-core/avrana-party-core.socket" "$rel/deploy/party-core/"
install -m 0755 "$repo/ops/provision-game" "$rel/ops/provision-game"
install -m 0755 "$repo/ops/prepare-native-games" "$rel/ops/prepare-native-games"
find "$rel" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R root:root /opt/avrana-party
chmod -R u=rwX,go=rX /opt/avrana-party
ln -sfn "$rel" "$tree"
install -d -m 0755 /opt/avrana-party-games /opt/avrana-party-games/releases "$grel"
cp -r "$games_repo/checkers" "$games_repo/core" "$games_repo/web" "$grel/"           # what python3 -m checkers imports and serves
find "$grel" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R root:root /opt/avrana-party-games
chmod -R u=rwX,go=rX /opt/avrana-party-games
ln -sfn "$grel" "$gtree"
t 'the Party release tree is root-owned and not group or world writable' 0 \
    test -z "$(find /opt/avrana-party -not -type l \( -not -user root -o -perm /022 \) -print -quit)"
t 'the Games release tree is root-owned and not group or world writable' 0 \
    test -z "$(find /opt/avrana-party-games -not -type l \( -not -user root -o -perm /022 \) -print -quit)"
t 'the Games tree holds what the real grant runs: checkers/__main__.py, core/ and the vendored bridge shim' 0 \
    test -f "$gtree/checkers/__main__.py" -a -f "$gtree/core/party_protocol.py" -a -f "$gtree/web/avrana-party-bridge.js"
mkdir -p -m 0700 "$work"

# ---- b. the real appliance grant for Checkers --------------------------------------------------------
# No fixture: the real profile of the release tree is used as it is. provision-game reads only the
# grant of the slug it is given, so the other games' grants and the providers are not touched.
s=$(status python3 - "$appliance" <<'PY'
import json, sys
grants = {g['game']: g for g in json.load(open(sys.argv[1]))['installed']}
g = grants['checkers']
assert g['runtime'] == {'command': ['/usr/bin/python3', '-m', 'checkers'],
                        'working_directory': '/opt/avrana-party-games/current'}, g['runtime']
assert g['permissions_granted'] == ['party_roster'], g['permissions_granted']
print('OBSERVE     the real grant: ' + json.dumps({k: g[k] for k in ('game', 'entry', 'tier', 'permissions_granted', 'runtime')}))
PY
)
check 'the real appliance profile grants checkers party_roster and runs /usr/bin/python3 -m checkers from /opt/avrana-party-games/current' 0 "$s"

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
t 'avrana-front has exactly the members avrana-party and www-data' 0 \
    test "$(getent group avrana-front | cut -d: -f4 | tr ',' '\n' | sort | paste -sd,)" = avrana-party,www-data

# ---- d. Party Core on its EARLIER unit, then ops/prepare-native-games ---------------------------------
# The earlier unit is derived from the repository's, not committed beside it: the same file without the
# ExecReload= line and without the Wants= and After= of the socket unit (as prepare-proof.sh does).
sed -e '/^ExecReload=/d' -e '/^Wants=avrana-party-core\.socket$/d' \
    -e 's/^After=network\.target avrana-party-core\.socket$/After=network.target/' \
    "$repo/deploy/party-core/avrana-party-core.service" > "$work/earlier.service"
install -m 0644 "$work/earlier.service" "$unit_dir/$party"
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
chmod 0640 "$conf"
systemctl start "$party"
wait_ready
t 'Party Core (its earlier unit) is active and answers /party/api/status on loopback' 0 test "$ready" = 0
capture prov checkers --appliance "$appliance"
show 'provision-game before preparing' "$out"
refused 'provision-game is refused on the unprepared host: party-core.json names no registry' 'does not name the registry directory'
capture prep
show 'prepare-native-games' "$out"
check 'ops/prepare-native-games exits 0' 0 "$rc"
t "the socket unit is enabled and $node is a socket, avrana-party:avrana-games 0660" 0 \
    bash -c 'systemctl is-enabled --quiet "$1" && test "$(stat -c "%F %a %U:%G" "$2")" = "socket 660 avrana-party:avrana-games"' _ "$psock" "$node"
wait_ready
t 'Party Core was restarted onto the socket, is active and answers on loopback' 0 test "$ready" = 0
doc=$(party_status || true)
t 'the status document has party_core.session (what provision-game asks)' 0 \
    python3 -c 'import json,sys; d=json.loads(sys.argv[1])["party_core"]; assert d["ok"] is True and "session" in d' "$doc"
pid_before=$(pid)
since_before=$(entered "$party")

# ---- e. provision-game checkers against the real appliance profile --------------------------------------
capture prov checkers --appliance "$appliance" --dry-run
show 'dry run' "$out"
check 'provision-game checkers --dry-run exits 0 and says it would create the key' 0 "$([[ $rc == 0 && $out == *'would change key'* ]] && echo 0 || echo 1)"
t 'a dry run changed nothing (no key, no registry entry, no template units, no drop-in)' nonzero \
    test -e "$key" -o -e "$entry" -o -e "$unit_dir/avrana-game@.socket" -o -e "$unit_dir/avrana-game@.service" -o -e "$dropin_dir"
t 'a dry run enabled nothing (the socket unit is not enabled)' nonzero systemctl is-enabled --quiet "$gsock"
capture "$rel/ops/provision-game" checkers --appliance "$appliance" --dry-run          # the wrapper, from the release tree
check 'ops/provision-game (the wrapper) dry run from the release tree: exit 0, and it changes nothing' 0 \
    "$([[ $rc == 0 && $out == *'would change key'* && ! -e $key && ! -e $entry ]] && echo 0 || echo 1)"

capture prov checkers --appliance "$appliance"
show 'provision' "$out"
check 'provision-game checkers exits 0' 0 "$rc"
t 'the key exists, 0600, owned by avrana-party' 0 test "$(stat -c '%a %U:%G' "$key")" = '600 avrana-party:avrana-party'
t 'the registry entry exists and names the game socket and key' 0 \
    python3 -c 'import json,sys; e=json.load(open(sys.argv[1])); assert e["id"]=="checkers" and e["socket"]=="/run/avrana-games/checkers.sock" and e["key_file"]==sys.argv[2], e' "$entry" "$key"
t 'the exec drop-in runs /usr/bin/python3 -m checkers from /opt/avrana-party-games/current' 0 \
    bash -c 'grep -qxF "ExecStart=\"/usr/bin/python3\" \"-m\" \"checkers\"" "$1/exec.conf" && grep -qxF "WorkingDirectory=/opt/avrana-party-games/current" "$1/exec.conf"' _ "$dropin_dir"
t 'the drop-in hands the game the Party origin from party-core.json (AVR-303)' 0 \
    grep -qxF 'Environment=AVRANA_PARTY_ORIGIN=http://party.ci.test' "$dropin_dir/exec.conf"
t 'the socket unit is enabled and active' 0 bash -c 'systemctl is-enabled --quiet "$1" && systemctl is-active --quiet "$1"' _ "$gsock"
t 'the game socket is root:avrana-front 0660' 0 test "$(stat -c '%a %U:%G' "$sock")" = '660 root:avrana-front'
t 'the game is socket-activated: its service is not running before the first connection' nonzero systemctl is-active --quiet "$game"
sha1=$(sha_of "$key")
capture prov checkers --appliance "$appliance"
show 'second run' "$out"
check 'a second run exits 0 and has nothing to change' 0 "$([[ $rc == 0 && $out == *'nothing to change'* ]] && echo 0 || echo 1)"
t 'a second run leaves the key unchanged' 0 test "$(sha_of "$key")" = "$sha1"
t 'provisioning reloaded Party Core and did not restart it (same process, same activation time)' 0 \
    test "$(pid)" = "$pid_before" -a "$(entered "$party")" = "$since_before"

# ---- f. session 1: a complete game through Party Core's public API and the game's Unix socket --------------
run_driver 'session 1: two phones, launch, tickets, redeems, strangers refused, a game played to its end, result accepted, home'
t 'the game (socket-activated) is running' 0 systemctl is-active --quiet "$game"
t 'the game runs as a systemd DynamicUser (DynamicUser=yes) and not as root' 0 \
    bash -c 'test "$(systemctl show -p DynamicUser --value "$1")" = yes && test "$(ps -o uid= -p "$(systemctl show -p MainPID --value "$1")" | tr -d " ")" != 0' _ "$game"
echo "OBSERVE     the game runs as user $(ps -o user= -p "$(systemctl show -p MainPID --value "$game")" | tr -d ' ')"
t 'the game holds its key by LoadCredential= (systemctl show)' 0 \
    bash -c 'systemctl show -p LoadCredential --value "$1" | grep -qF "checkers.key:/etc/avrana-party/game-keys/checkers.key"' _ "$game"
t 'the running game was handed the Party origin in its environment (systemctl show)' 0 \
    bash -c 'systemctl show -p Environment --value "$1" | tr " " "\n" | grep -qxF AVRANA_PARTY_ORIGIN=http://party.ci.test' _ "$game"
t 'the running game answers with the configured Party origin (what the page is told, AVR-303)' 0 \
    bash -c 'test "$(curl -fsS --max-time 10 --unix-socket "$1" http://localhost/games/checkers/api/party | tr -d " ")" = "{\"partyOrigin\":\"http://party.ci.test\"}"' _ "$sock"
t 'the game received the signed launch (journal)' 0 journal_has "$game" 'launched ('
t 'the game finished by the rules and reported its signed ended (journal)' 0 journal_has "$game" 'finished ('
check 'Party Core accepted the result (the game logged: the party accepted the result), once' 0 \
    "$([[ $(journal_count "$game" 'the party accepted the result') == 1 ]] && echo 0 || echo 1)"
t 'the game did not log that the party refused or lost the report' nonzero journal_has "$game" 'the party did not accept the report'
t 'Party Core was not restarted by any of it' 0 test "$(pid)" = "$pid_before"

# ---- g. session 2: the Host ends the game from Party ----------------------------------------------------------
run_driver 'session 2: a launched game the Host ends from Party (POST /party/api/session/end): over for both phones' --end
t 'the game saw the end the Party sent (journal: ended by the party)' 0 journal_has "$game" 'ended by the party'
check 'and no further result was reported or accepted (still exactly one accepted line)' 0 \
    "$([[ $(journal_count "$game" 'the party accepted the result') == 1 ]] && echo 0 || echo 1)"
gone=1
for _ in $(seq 1 100); do                    # the game releases its process after 60 s without a session
    if ! systemctl is-active --quiet "$game"; then gone=0; break; fi
    sleep 1
done
check 'the Checkers process holds no session: it exited on its own (idle stop) after the end, the socket stays' 0 "$gone"
t 'the socket unit still listens, so the next launch starts the game again' 0 systemctl is-active --quiet "$gsock"

# ---- h. the boundary checker with Checkers provisioned ---------------------------------------------------------
(cd "$tree" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.boundary --phase 2 --json) > "$work/phase2.json" || true
s=$(status python3 - "$work/phase2.json" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))
want = {'identity.groups', 'ipc.no_ip', 'hardening.native', 'ipc.socket.game', 'ipc.socket.party_internal', 'groups.front'}
names = [r['rule'] for r in rows]
bad = [f"{r['rule']} ({r['subject']}): {r['detail']}" for r in rows if not r['ok']]
for r in rows:
    print(f"OBSERVE     phase {r['phase']} {'ok  ' if r['ok'] else 'FAIL'} {r['rule']} {r['subject']}")
print(f"OBSERVE     phase 2: {sum(r['ok'] for r in rows)}/{len(rows)} rules met")
assert rows, 'no phase 2 rule was reported'
assert sorted(set(names)) == sorted(want), f'phase 2 rules present {sorted(set(names))}, expected {sorted(want)}'
assert any('checkers' in r['subject'] for r in rows), 'no rule names the checkers game'
assert not bad, 'rules not met: ' + '; '.join(bad)
PY
)
check 'boundary --phase 2 with Checkers provisioned: every rule is present and met, and a rule names the checkers game' 0 "$s"

# ---- i. remove ---------------------------------------------------------------------------------------------------
sleep 7                                   # longer than Party Core's status cache: remove must not see the finished session as live
capture prov checkers --appliance "$appliance" --remove
show 'remove' "$out"
check 'remove exits 0' 0 "$rc"
t 'the socket unit is not enabled' nonzero systemctl is-enabled --quiet "$gsock"
t 'the socket unit is not active' nonzero systemctl is-active --quiet "$gsock"
t 'the game service is not active' nonzero systemctl is-active --quiet "$game"
t 'the key is gone' nonzero test -e "$key"
t 'the registry entry is gone' nonzero test -e "$entry"
t 'the socket file is gone' nonzero test -e "$sock"
t 'the drop-in directory is gone' nonzero test -e "$dropin_dir"
t 'the state directory is gone (/var/lib/avrana-games/checkers)' nonzero test -e /var/lib/avrana-games/checkers
t 'the state directory is gone (/var/lib/private/avrana-games/checkers)' nonzero test -e /var/lib/private/avrana-games/checkers
t 'Party Core is still active and was never restarted since provisioning began' 0 \
    test "$(pid)" = "$pid_before" -a "$(entered "$party")" = "$since_before"
run_driver 'Party Core no longer offers the game (/party/api/state)' --absent
capture prov checkers --appliance "$appliance" --remove
show 'second remove' "$out"
check 'remove is repeatable and has nothing left to remove' 0 "$([[ $rc == 0 && $out == *'nothing to remove'* ]] && echo 0 || echo 1)"

# ---- j. summary (the cleanup trap restores the host and says so) ---------------------------------------------------
echo "failed checks: $fails"
[[ $fails == 0 ]]
