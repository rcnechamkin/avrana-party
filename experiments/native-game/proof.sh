#!/usr/bin/env bash
# Non-production proof for ADR 0016 sections 3 to 5 and 8 (AVR-236): `provision-game standin` on a
# machine with real systemd and root, then Party Core launches and ends a session with the
# provisioned stand-in game over real socket activation and a real LoadCredential= key, and
# accepts its signed `ended` with a result. Linux + systemd + root only.
#
#   sudo AVRANA_NATIVE_GAME_PROOF=1 bash experiments/native-game/proof.sh
#
# Run it in CI or on a disposable Linux machine. NEVER on the Pi: that would be an unauthorized
# change to the appliance (AGENTS.md). It refuses to start when /etc/avrana-party, /opt/avrana-party,
# the user avrana-party or the groups avrana-front / avrana-games already exist, so it can never
# eat a real installation.
#
# It CREATES (and removes again on exit, whatever happened):
#   users and groups  system user and group avrana-party (nologin, no home); groups avrana-front
#                     (members avrana-party, www-data) and avrana-games; www-data only if absent
#   /etc/avrana-party              party-core.json, games.d/, game-keys/ (0700 avrana-party)
#   /opt/avrana-party              releases/ci (a copy of avrana/, contracts/, deploy/games/, one
#                                  test fixture) and the symlink current
#   /etc/systemd/system            avrana-party-core.{service,socket}, avrana-game@.{socket,service},
#                                  avrana-game@standin.service.d/, the .wants symlinks
#   runtime and state              /run/avrana-games, /run/avrana-party, /run/avrana-native-game-proof,
#                                  /var/lib/avrana-party-core, /var/lib/avrana-games and
#                                  /var/lib/private/avrana-games (the DynamicUser state)
# Services it runs: avrana-party-core (the real unit, User=avrana-party) and avrana-game@standin.
#
# Output: one line per check. CHECK lines are assumptions the design depends on (a FAIL exits 1).
# OBSERVE lines record behaviour worth reading either way. On failure the journal of the two
# services is printed (the code never logs a key, ticket, token or cookie).
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

[[ ${AVRANA_NATIVE_GAME_PROOF:-} == 1 ]] || { echo 'set AVRANA_NATIVE_GAME_PROOF=1 (CI or a disposable machine only; never the Pi)' >&2; exit 2; }
[[ $(id -u) == 0 ]] || { echo 'run as root (sudo)' >&2; exit 2; }
command -v systemctl >/dev/null && [[ -d /run/systemd/system ]] || { echo 'systemd is not running here' >&2; exit 2; }
command -v curl >/dev/null || { echo 'curl not found' >&2; exit 2; }

repo=$(cd "$(dirname "$0")/../.." && pwd)
here=$repo/experiments/native-game
work=/run/avrana-native-game-proof
marker=/run/avrana-native-game-proof.marker
unit_dir=/etc/systemd/system
rel=/opt/avrana-party/releases/ci
tree=/opt/avrana-party/current
fixture=$rel/tests/fixtures/appliances/ci-standin.json
keydir=/etc/avrana-party/game-keys
key=$keydir/standin.key
entry=/etc/avrana-party/games.d/standin.json
sock=/run/avrana-games/standin.sock
dropin_dir=$unit_dir/avrana-game@standin.service.d
party=avrana-party-core.service
game=avrana-game@standin.service
fails=0

# ---- refuse to touch anything that is not ours -------------------------------------------------
# Before the trap exists: a refusal must not run the cleanup below. A marker from an earlier run
# of this script (a crash, then a re-run on the same machine) says the leftovers are ours.
if [[ ! -e $marker ]]; then
    for p in /etc/avrana-party /opt/avrana-party; do
        [[ ! -e $p ]] || { echo "refusing: $p exists and this script did not create it" >&2; exit 2; }
    done
    for n in avrana-party avrana-front avrana-games; do
        ! getent passwd "$n" >/dev/null && ! getent group "$n" >/dev/null \
            || { echo "refusing: the user or group $n exists and this script did not create it" >&2; exit 2; }
    done
fi

cleanup() {
    set +e
    systemctl stop avrana-game@standin.socket avrana-party-core.socket 2>/dev/null
    systemctl stop avrana-game@standin.service avrana-party-core.service 2>/dev/null
    systemctl disable avrana-game@standin.socket avrana-party-core.socket 2>/dev/null
    rm -f "$unit_dir"/sockets.target.wants/avrana-game@standin.socket "$unit_dir"/sockets.target.wants/avrana-party-core.socket
    rm -rf "$unit_dir"/avrana-game@.socket "$unit_dir"/avrana-game@.service "$dropin_dir" \
        "$unit_dir"/avrana-party-core.service "$unit_dir"/avrana-party-core.socket
    rm -rf /etc/avrana-party /opt/avrana-party /var/lib/avrana-party-core /var/lib/private/avrana-party-core \
        /var/lib/avrana-games /var/lib/private/avrana-games /run/avrana-games /run/avrana-party "$work"
    systemctl daemon-reload 2>/dev/null
    systemctl reset-failed avrana-game@standin.service avrana-party-core.service 2>/dev/null
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
        journalctl -u avrana-party-core.service -u avrana-game@standin.service -u avrana-game@standin.socket --no-pager -n 80
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
prov() { (cd "$tree" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.provision_game "$@"); }
driver() { python3 "$here/driver.py" --state "$work/driver.json" "$@"; }
party_status() { curl -fsS --max-time 10 -H 'Host: party.ci.test' http://127.0.0.1:8191/party/api/status; }
journal_has() { journalctl --sync >/dev/null 2>&1 || true; journalctl -u "$1" --no-pager 2>/dev/null | grep -qF -- "$2"; }

echo "systemd $(systemctl --version | head -n1 | awk '{print $2}'), kernel $(uname -r), $(uname -m), $(python3 --version)"

# ---- b. identities, as ADR 0016 phase 1 (ops/migrate-service-users.sh) ---------------------------
for g in avrana-front avrana-games; do groupadd --system "$g"; done
useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin avrana-party
if ! getent passwd www-data >/dev/null; then
    useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin www-data
    echo www-data >> "$marker"
fi
usermod -a -G avrana-front avrana-party
usermod -a -G avrana-front www-data
t 'avrana-party is a system user with a nologin shell' 0 test "$(getent passwd avrana-party | cut -d: -f7)" = /usr/sbin/nologin
t 'avrana-front has exactly the members avrana-party and www-data' 0 \
    test "$(getent group avrana-front | cut -d: -f4 | tr ',' '\n' | sort | paste -sd,)" = avrana-party,www-data

# ---- c. directories --------------------------------------------------------------------------------
install -d -m 0755 -o root -g root /etc/avrana-party /etc/avrana-party/games.d
install -d -m 0700 -o avrana-party -g avrana-party "$keydir"
t '/etc/avrana-party and games.d are 0755 root' 0 \
    test "$(stat -c '%a %U:%G' /etc/avrana-party /etc/avrana-party/games.d | paste -sd,)" = '755 root:root,755 root:root'
t 'game-keys is 0700 avrana-party:avrana-party' 0 test "$(stat -c '%a %U:%G' "$keydir")" = '700 avrana-party:avrana-party'

# ---- d. the release tree: root-owned, read-only to every service -----------------------------------
install -d -m 0755 /opt/avrana-party /opt/avrana-party/releases "$rel" "$rel/deploy" "$rel/tests/fixtures/appliances"
cp -r "$repo/avrana" "$repo/contracts" "$rel/"
cp -r "$repo/deploy/games" "$rel/deploy/games"
cp "$repo/tests/fixtures/appliances/ci-standin.json" "$fixture"
find "$rel" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R root:root /opt/avrana-party
chmod -R u=rwX,go=rX /opt/avrana-party
ln -sfn "$rel" "$tree"
t 'the release tree is root-owned and not group or world writable' 0 \
    test -z "$(find /opt/avrana-party -not -type l \( -not -user root -o -perm /022 \) -print -quit)"

# ---- e. Party Core as its real unit ------------------------------------------------------------------
# provision-game's own status query sends the first of `hosts` as its Host header.
cat > /etc/avrana-party/party-core.json <<'JSON'
{
  "hosts": ["party.ci.test"],
  "origins": ["http://party.ci.test"],
  "secure_cookie": false,
  "registry": "/etc/avrana-party/games.d",
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
chmod 0644 /etc/avrana-party/party-core.json
install -m 0644 "$repo/deploy/party-core/avrana-party-core.service" "$repo/deploy/party-core/avrana-party-core.socket" "$unit_dir/"
systemctl daemon-reload
systemctl enable --now avrana-party-core.socket
systemctl start "$party"
mkdir -p -m 0700 "$work"
ready=1
for _ in $(seq 1 40); do
    if systemctl is-active --quiet "$party" && party_status >/dev/null 2>&1; then ready=0; break; fi
    sleep 0.5
done
t 'Party Core is active and answers /party/api/status on loopback' 0 test "$ready" = 0
doc=$(party_status || true)
t 'the status document has party_core.session (what provision-game rotate asks)' 0 \
    python3 -c 'import json,sys; d=json.loads(sys.argv[1])["party_core"]; assert d["ok"] is True and "session" in d' "$doc"
t 'Party Core inherited its internal socket from the socket unit (avrana-party:avrana-games 0660)' 0 \
    test "$(stat -c '%a %U:%G' /run/avrana-party/internal.sock)" = '660 avrana-party:avrana-games'
pid_before=$(systemctl show -p ExecMainPID --value "$party")
since_before=$(systemctl show -p ActiveEnterTimestampMonotonic --value "$party")

# ---- f. provision ------------------------------------------------------------------------------------
capture prov standin --appliance "$fixture" --dry-run
show 'dry run' "$out"
check 'provision --dry-run exits 0 and says it would create the key' 0 "$([[ $rc == 0 && $out == *'would change key'* ]] && echo 0 || echo 1)"
t 'a dry run changed nothing (no key, no registry entry)' nonzero test -e "$key" -o -e "$entry"

capture prov standin --appliance "$fixture"
show 'provision' "$out"
check 'provision standin exits 0' 0 "$rc"
t 'the key exists, 0600, owned by avrana-party' 0 test "$(stat -c '%a %U:%G' "$key")" = '600 avrana-party:avrana-party'
t 'the registry entry exists' 0 test -s "$entry"
t 'the exec drop-in exists' 0 test -s "$dropin_dir/exec.conf"
t 'the socket unit is enabled and active' 0 bash -c 'systemctl is-enabled --quiet avrana-game@standin.socket && systemctl is-active --quiet avrana-game@standin.socket'
t 'the game socket is root:avrana-front 0660' 0 test "$(stat -c '%a %U:%G' "$sock")" = '660 root:avrana-front'
sha1=$(sha_of "$key")
capture prov standin --appliance "$fixture"
show 'second run' "$out"
check 'a second run exits 0 and has nothing to change' 0 "$([[ $rc == 0 && $out == *'nothing to change'* ]] && echo 0 || echo 1)"
t 'a second run leaves the key unchanged' 0 test "$(sha_of "$key")" = "$sha1"

# ---- g. refusals ---------------------------------------------------------------------------------------
capture prov nosuchgame --appliance "$fixture"
show 'unknown slug' "$out"
check 'an unknown slug is refused (exit 1)' 0 "$([[ $rc == 1 ]] && echo 0 || echo 1)"
capture prov bluff --appliance "$fixture"
show 'no grant' "$out"
check 'a game with a contract but no grant in the profile is refused (exit 1)' 0 "$([[ $rc == 1 ]] && echo 0 || echo 1)"
capture prov standin --appliance "$tree/contracts/appliances/avrana-pi4.json"
show 'product profile' "$out"
check 'the stand-in against the real product appliance profile is refused (exit 1)' 0 "$([[ $rc == 1 ]] && echo 0 || echo 1)"
t 'refusals created nothing' 0 test "$(ls /etc/avrana-party/games.d | paste -sd,)" = standin.json -a "$(ls "$keydir" | paste -sd,)" = standin.key

# ---- h. the full session over real socket activation, then the boundary checker ------------------------
s=$(status driver)
check 'a full session: two phones, launch, tickets, redeems, strangers refused, finish with a result, results, home' 0 "$s"
t 'the game (a DynamicUser instance, socket-activated) is running' 0 systemctl is-active --quiet "$game"
t 'the game received the signed launch (journal)' 0 journal_has "$game" 'launched ('
t 'the game reported its signed ended and the party answered 200 (journal)' 0 journal_has "$game" 'finished; the party answered 200'
t 'Party Core did not refuse the result (journal has no "result refused")' nonzero journal_has "$party" 'result refused'
t 'Party Core was not restarted by any of it' 0 test "$(systemctl show -p ExecMainPID --value "$party")" = "$pid_before"

(cd "$tree" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.boundary --phase 2 --json) > "$work/phase2.json" || true
s=$(status python3 - "$work/phase2.json" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))
want = {'identity.groups', 'ipc.no_ip', 'hardening.native', 'ipc.socket.game', 'ipc.socket.party_internal', 'groups.front'}
names = [r['rule'] for r in rows]
bad = [f"{r['rule']} ({r['subject']}): {r['detail']}" for r in rows if not r['ok']]
for r in rows:
    print(f"OBSERVE     phase {r['phase']} {'ok  ' if r['ok'] else 'FAIL'} {r['rule']} {r['subject']}")
assert sorted(names) == sorted(want), f'phase 2 rules present {sorted(names)}, expected {sorted(want)}'
assert not bad, 'rules not met: ' + '; '.join(bad)
PY
)
check 'boundary --phase 2: exactly the six native-game rules are present and all met' 0 "$s"

(cd "$tree" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.boundary --phase 1 --phase 2 --json) > "$work/both.json" || true
s=$(status python3 - "$work/both.json" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))
unmet1 = []
for r in rows:
    print(f"OBSERVE     phase {r['phase']} {'ok  ' if r['ok'] else 'FAIL'} {r['rule']:<26} {r['subject']}" + ('' if r['ok'] else f"  [{r['detail']}]"))
    if r['phase'] == 1 and not r['ok']:
        unmet1.append(r['rule'])
print(f"OBSERVE     phase 1: {sum(r['ok'] for r in rows if r['phase'] == 1)}/{sum(1 for r in rows if r['phase'] == 1)} rules met; not met: {unmet1 or 'none'}")
p2 = [r for r in rows if r['phase'] == 2]
assert len(p2) == 6 and all(r['ok'] for r in p2), 'phase 2 rules in the combined run: ' + str([(r['rule'], r['ok']) for r in p2])
PY
)
check 'boundary --phase 1 --phase 2: the phase 2 rules are unchanged (phase 1 is observed, not asserted)' 0 "$s"

# ---- i. rotation ---------------------------------------------------------------------------------------
sha_live=$(sha_of "$key")
s=$(status driver --hold)
check 'a second session is launched and held live' 0 "$s"
capture prov standin --appliance "$fixture" --rotate
show 'rotate during a session' "$out"
check 'rotate is refused while the game has a session (exit 1)' 0 "$([[ $rc == 1 ]] && echo 0 || echo 1)"
t 'the refused rotation left the key unchanged' 0 test "$(sha_of "$key")" = "$sha_live"
t 'the refused rotation did not stop the game' 0 systemctl is-active --quiet "$game"
s=$(status driver --end)
check 'the host ends the held session from Party Home' 0 "$s"
sleep 7                                   # longer than Party Core's status cache (5 s): rotate must not see the old session
capture prov standin --appliance "$fixture" --rotate
show 'rotate after the session' "$out"
check 'rotate succeeds once the session has ended (exit 0)' 0 "$rc"
t 'the key changed' nonzero test "$(sha_of "$key")" = "$sha_live"
t 'the key is still 0600 avrana-party' 0 test "$(stat -c '%a %U:%G' "$key")" = '600 avrana-party:avrana-party'
t 'rotation stopped the game so the next start loads the new key' nonzero systemctl is-active --quiet "$game"
sleep 2                                   # Party Core re-reads the registry on SIGHUP in a thread
s=$(status driver)
check 'a fresh full session works with the new key (game restarted, Party reloaded)' 0 "$s"
t 'the game is running again with the new key' 0 systemctl is-active --quiet "$game"

# ---- j. remove -----------------------------------------------------------------------------------------
capture prov standin --appliance "$fixture" --remove
show 'remove' "$out"
check 'remove exits 0' 0 "$rc"
t 'the socket unit is not enabled' nonzero systemctl is-enabled --quiet avrana-game@standin.socket
t 'the socket unit is not active' nonzero systemctl is-active --quiet avrana-game@standin.socket
t 'the game service is not active' nonzero systemctl is-active --quiet "$game"
t 'the key is gone' nonzero test -e "$key"
t 'the registry entry is gone' nonzero test -e "$entry"
t 'the socket file is gone' nonzero test -e "$sock"
t 'the drop-in directory is gone' nonzero test -e "$dropin_dir"
t 'the state directory is gone (/var/lib/avrana-games/standin)' nonzero test -e /var/lib/avrana-games/standin
t 'the state directory is gone (/var/lib/private/avrana-games/standin)' nonzero test -e /var/lib/private/avrana-games/standin
t 'Party Core is still active' 0 systemctl is-active --quiet "$party"
t 'Party Core was never restarted (same main PID and activation time as before provisioning)' 0 \
    test "$(systemctl show -p ExecMainPID --value "$party")" = "$pid_before" -a \
         "$(systemctl show -p ActiveEnterTimestampMonotonic --value "$party")" = "$since_before"
s=$(status driver --absent)
check 'Party Core no longer offers the game (/party/api/state)' 0 "$s"
capture prov standin --appliance "$fixture" --remove
check 'remove is repeatable and has nothing left to remove' 0 "$([[ $rc == 0 && $out == *'nothing to remove'* ]] && echo 0 || echo 1)"

# ---- k. summary ----------------------------------------------------------------------------------------
echo "failed checks: $fails"
[[ $fails == 0 ]]
