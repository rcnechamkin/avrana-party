#!/usr/bin/env bash
# Non-production proof for ADR 0016 (AVR-227): do the ordinary systemd primitives the service
# trust boundary relies on behave as the ADR assumes? Linux + systemd + root only.
#
#   sudo AVRANA_TRUST_PROOF=1 bash experiments/service-trust/proof.sh
#
# It runs a few transient units (systemd-run) as DynamicUser and one instance,
# avrana-game@proofgame.service, of a template it writes under /run/systemd/system for the boundary
# checker to collect; creates and deletes two throwaway groups and files under
# /run/avrana-trust-proof and /var/lib/private; and leaves nothing installed. Run it in CI or on a disposable Linux machine. NEVER on the Pi: that would be
# an unauthorized change to the appliance (AGENTS.md), and a real-Pi check is a separate,
# owner-run step listed in the ADR.
#
# Output: one line per check. CHECK lines are assumptions the design depends on (a FAIL exits 1).
# OBSERVE lines record behaviour the ADR must describe correctly either way.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

[[ ${AVRANA_TRUST_PROOF:-} == 1 ]] || { echo 'set AVRANA_TRUST_PROOF=1 (CI or a disposable machine only; never the Pi)' >&2; exit 2; }
[[ $(id -u) == 0 ]] || { echo 'run as root (sudo)' >&2; exit 2; }
command -v systemd-run >/dev/null || { echo 'systemd-run not found' >&2; exit 2; }

repo=$(cd "$(dirname "$0")/../.." && pwd)
work=/run/avrana-trust-proof
front=avrtp-front      # stands in for avrana-front: may connect to a game's socket
games=avrtp-games      # stands in for avrana-games: may connect to the party's internal socket
template=/run/systemd/system/avrana-game@.service   # runtime-only: gone on reboot, removed below
fails=0
pids=()

cleanup() {
    for p in ${pids[@]+"${pids[@]}"}; do kill "$p" 2>/dev/null || true; done
    systemctl stop 'avrana-game@proofgame.service' 2>/dev/null || true
    if [[ -e $template ]]; then rm -f "$template"; systemctl daemon-reload; fi
    rm -rf "$work" /var/lib/private/avrana-trust-proof-a /var/lib/avrana-trust-proof-a \
        /var/lib/private/avrana-trust-proof-k /var/lib/avrana-trust-proof-k \
        /var/lib/private/avrana-games/proofgame /var/lib/avrana-games/proofgame
    groupdel "$front" 2>/dev/null || true
    groupdel "$games" 2>/dev/null || true
}
trap cleanup EXIT
cleanup

check() {  # check <name> <expected: 0|nonzero> <actual status>
    if { [[ $2 == 0 && $3 == 0 ]] || [[ $2 != 0 && $3 != 0 ]]; }; then echo "CHECK PASS  $1"
    else echo "CHECK FAIL  $1 (status $3)"; fails=$((fails + 1)); fi
}
# run <systemd-run properties...> -- <python source>: a transient unit, stdout passed through
run() {
    local props=()
    while [[ $1 != -- ]]; do props+=(-p "$1"); shift; done
    shift
    systemd-run --quiet --wait --collect --pipe -p DynamicUser=yes "${props[@]}" /usr/bin/python3 -c "$1"
}
status() { set +e; "$@" >&2; local s=$?; set -e; echo "$s"; }

echo "systemd $(systemctl --version | head -n1 | awk '{print $2}'), kernel $(uname -r), $(uname -m)"
groupadd -r "$front"; groupadd -r "$games"
install -d -m 0755 "$work"
install -m 0644 "$repo/avrana/party/protocol.py" "$work/protocol.py"   # the real key reader
install -d -m 0700 "$work/keys"                                        # the party's key store
printf '%064d\n' 0 > "$work/keys/demo.key"; chmod 0600 "$work/keys/demo.key"

# 1. A game identity cannot read the key store, but receives its own key as a credential.
s=$(status run -- "open('$work/keys/demo.key').read()" 2>/dev/null)
check 'a dynamic identity cannot read the 0700 key store' nonzero "$s"
s=$(status run "LoadCredential=demo.key:$work/keys/demo.key" -- "
import os; p = os.path.join(os.environ['CREDENTIALS_DIRECTORY'], 'demo.key')
assert len(open(p).read().strip()) == 64")
check 'the same identity reads its own key through LoadCredential' 0 "$s"

# 2. What a credential file looks like to the service (systemd grants access with a POSIX ACL, so
#    its mode shows group bits), and that the real key reader accepts exactly that file (AVR-253)
#    while still refusing the same key copied with plain group access.
s=$(status run "LoadCredential=demo.key:$work/keys/demo.key" StateDirectory=avrana-trust-proof-k -- "
import os, shutil, subprocess, sys; sys.path.insert(0, '$work'); import protocol
p = os.path.join(os.environ['CREDENTIALS_DIRECTORY'], 'demo.key'); st = os.stat(p)
print('OBSERVE     credential mode %o, owner uid %d, service uid %d' % (st.st_mode & 0o777, st.st_uid, os.getuid()))
try: print('OBSERVE     credential ACL xattr', os.getxattr(p, 'system.posix_acl_access').hex())
except OSError as e: print('OBSERVE     credential has no ACL xattr:', e)
if shutil.which('getfacl'):
    for line in subprocess.run(['getfacl', '-n', '-p', p], capture_output=True, text=True).stdout.splitlines():
        if line: print('OBSERVE     getfacl:', line)
else: print('OBSERVE     getfacl is not installed')
assert len(protocol.read_key(p)) == 32
loose = os.path.join(os.environ['STATE_DIRECTORY'], 'loose.key')
shutil.copyfile(p, loose); os.chmod(loose, 0o640)
try: protocol.read_key(loose)
except ValueError as e: print('OBSERVE     a group-readable copy is refused:', e)
else: raise SystemExit('read_key accepted a key with plain group access')
")
check 'protocol.read_key accepts a real LoadCredential file and still refuses plain group access' 0 "$s"

# 3. One game's state directory is closed to another game.
run StateDirectory=avrana-trust-proof-a -- "
import os; open(os.path.join(os.environ['STATE_DIRECTORY'], 'save'), 'w').write('a')"
s=$(status run -- "
import os
for p in ('/var/lib/avrana-trust-proof-a/save', '/var/lib/private/avrana-trust-proof-a/save'):
    try: open(p).read(); raise SystemExit(0)
    except OSError: pass
raise SystemExit(1)" 2>/dev/null)
check "another identity cannot read a game's state directory" nonzero "$s"

# 4. Socket permissions, not addresses, decide who may speak. Two root-held listeners stand in
#    for a game's socket (group $front) and the party's internal socket (group $games).
listen() {  # listen <path> <group>
    python3 -c "
import os, socket, sys
s = socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); os.chmod(sys.argv[1], 0o660)
import shutil; shutil.chown(sys.argv[1], 'root', sys.argv[2]); s.listen(8)
while True:
    c, _ = s.accept(); c.sendall(b'ok'); c.close()" "$1" "$2" &
    pids+=($!)
}
listen "$work/game.sock" "$front"
listen "$work/party-internal.sock" "$games"
for _ in 1 2 3 4 5 6 7 8 9 10; do [[ -S $work/game.sock && -S $work/party-internal.sock ]] && break; sleep 0.3; done
connect="import socket, sys
s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); assert s.recv(2) == b'ok'"
client() { local props=(); while [[ $1 != -- ]]; do props+=(-p "$1"); shift; done; shift
    systemd-run --quiet --wait --collect --pipe -p DynamicUser=yes "${props[@]}" /usr/bin/python3 -c "$connect" "$1" 2>/dev/null; }

s=$(status client "SupplementaryGroups=$front" -- "$work/game.sock")
check "a member of the front group (nginx, party) connects to a game's socket" 0 "$s"
s=$(status client "SupplementaryGroups=$games" -- "$work/game.sock")
check "a game identity cannot connect to another game's socket" nonzero "$s"
s=$(status client "SupplementaryGroups=$games" RestrictAddressFamilies=AF_UNIX PrivateNetwork=yes -- "$work/party-internal.sock")
check "a game with no IP networking and its own network namespace still reaches the party's internal socket" 0 "$s"
s=$(status client -- "$work/party-internal.sock")
check "an identity outside the games group cannot reach the party's internal socket" nonzero "$s"
s=$(status run RestrictAddressFamilies=AF_UNIX -- "
import socket
socket.socket(socket.AF_INET)" 2>/dev/null)
check 'RestrictAddressFamilies=AF_UNIX leaves a game no IP socket (loopback included)' nonzero "$s"

# 5. The boundary checker's collector (avrana/ops/boundary.py) against a real dynamic-user unit
#    named like a native game. It only reads; this is the one place it meets real systemd output.
#    The unit is an instance of a real template written the way ADR 0016 section 5 writes it
#    (%i in the credential line, and whitespace around one "="), so the collector has to expand
#    the instance name itself when `systemctl show` will not print the list (AVR-257).
slug=proofgame
cp "$work/keys/demo.key" "$work/keys/$slug.key"; chmod 0600 "$work/keys/$slug.key"
install -d -m 0755 "$(dirname "$template")"
cat > "$template" <<UNIT
[Unit]
Description=Avrana trust proof: a native game instance (%i)
[Service]
DynamicUser=yes
SupplementaryGroups=$games
StateDirectory=avrana-games/%i
StateDirectoryMode=0700
RestrictAddressFamilies=AF_UNIX
PrivateDevices=yes
ProtectHome=yes
LoadCredential = %i.key:$work/keys/%i.key
ExecStart=/usr/bin/sleep 120
UNIT
systemctl daemon-reload
systemctl start "avrana-game@$slug.service"
for _ in 1 2 3 4 5 6 7 8 9 10; do systemctl is-active --quiet "avrana-game@$slug.service" && break; sleep 0.3; done
echo "OBSERVE     systemctl show LoadCredential: [$(systemctl show "avrana-game@$slug.service" -p LoadCredential --value)]"
(cd "$repo" && python3 -m avrana.ops.boundary --collect) > "$work/facts.json"
s=$(status python3 - "$work/facts.json" "$slug" "$games" "$work/keys/$slug.key" <<'PY'
import json, sys
facts, slug, games, key = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3], sys.argv[4]
found = [s for s in facts['services'] if s['unit'] == f'avrana-game@{slug}.service']
print('collected:', json.dumps(found, sort_keys=True))
assert len(found) == 1, 'the unit was not collected'
s = found[0]
want = {'role': 'native-game', 'slug': slug, 'dynamic_user': True, 'supplementary_groups': [games],
        'address_families': ['AF_UNIX'], 'private_devices': True, 'private_tmp': True,
        'protect_home': 'yes', 'protect_system': 'strict', 'no_new_privileges': True,
        'credentials': [key], 'tcp': []}
wrong = {k: (s.get(k), v) for k, v in want.items() if s.get(k) != v}
assert not wrong, f'collected value, expected value: {wrong}'
state = [p for p in s['state'] if p['path'] == f'/var/lib/private/avrana-games/{slug}']
assert state and state[0]['mode'] == '0700', s['state']
assert s['user'] not in facts['users'], 'a dynamic identity must not be recorded as a static user'
PY
)
check "the boundary checker collects a template game unit as the ADR describes it, credential path expanded" 0 "$s"
systemctl stop "avrana-game@$slug.service" 2>/dev/null || true

echo "failed checks: $fails"
[[ $fails == 0 ]]
