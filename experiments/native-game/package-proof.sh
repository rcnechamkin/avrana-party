#!/usr/bin/env bash
# Non-production proof for AVR-39 (EXPERIMENTAL .avrgame packages): the Hello Party package of the
# Games repository is built unprivileged from its committed recipe, refused when hostile or wrong,
# installed by the REAL `install-game` through the REAL `provision-game` path, launched by Party Core
# over its Unix socket, played by "phones", ended, and removed again without a trace. Linux +
# systemd + root only.
#
#   sudo AVRANA_PACKAGE_PROOF=1 AVRANA_GAMES_REPO=/path/to/avrana-party-games \
#        bash experiments/native-game/package-proof.sh
#
# Run it in CI or on a disposable Linux machine. NEVER on the Pi: that would be an unauthorized
# change to the appliance (AGENTS.md). Like checkers-proof.sh it refuses to start when
# /etc/avrana-party, /opt/avrana-party, /opt/avrana-party-games, /opt/avrana-games,
# /var/backups/avrana-party, the user avrana-party or the groups avrana-front / avrana-games already
# exist, so it can never eat a real installation. This script is a sibling of checkers-proof.sh and
# prepare-proof.sh and calls the tools; it never changes them.
#
# THE POINT: the game is known to this appliance ONLY through its package. The Party release tree
# copied to /opt has NO contracts/games/hello.json (it is deleted from the copy and its absence is
# asserted), the real appliance profile does not grant it, and provision-game alone refuses it.
#
# THE STORY, on a clean host:
#   1. ADR 0016 phase 1, Party Core on its EARLIER unit, ops/prepare-native-games (as
#      checkers-proof.sh), the owner prerequisites of the runbook (the "packages" key of
#      party-core.json, an empty root-owned /opt/avrana-games);
#   2. build: the committed recipe hello_party/avrgame.build.json, packed by an UNPRIVILEGED user,
#      twice: identical sha256; `validate` passes;
#   3. refusals, each leaving the host exactly as it was: a tampered archive, a format-bumped
#      manifest, a traversal entry, an id of a first-party game, an install by a non-root user;
#   4. `install-game install --grant party_roster`: dry run changes nothing; the run exits 0; the
#      record and the staged tree are root-owned and not writable by others; the registry entry, key
#      and drop-in exist; Party Core (reloaded, NOT restarted) offers the game; the generated
#      catalog (--packages) lists it installed, and a second install is refused;
#   5. session 1: two players and a watcher through Party Core's public API and the game's Unix
#      socket (package-driver.py): the socket-activated process runs from the STAGED tree as a
#      DynamicUser, each seat holds a secret word only it sees, each says hello over the game's HTTP
#      API, a reload returns the same seat, the game ends by itself with a signed `ended` that Party
#      Core accepts; the boundary checker (phase 2) while it runs;
#   6. session 2: `install-game remove` is REFUSED during the live session, then the Host ends it;
#   7. `install-game remove hello`: nothing is left (record, tree, key, entry, drop-in, socket,
#      state), Party Core no longer offers it and was not restarted, a second remove is a clean
#      no-op, a re-install works, and is removed again.
#
# It CREATES (and removes again on exit, whatever happened): the same users, groups, /etc, /opt,
# units and runtime directories as checkers-proof.sh, plus /opt/avrana-games (the staged trees),
# /etc/avrana-party/packages.d (the install records) and /run/avrana-package-proof (scratch).
# Services it runs: avrana-party-core (the real unit) and avrana-game@hello.
#
# Output: one line per check. CHECK lines are assumptions the design depends on (a FAIL exits 1).
# OBSERVE lines record behaviour worth reading either way. On failure the journal of the two
# services is printed (the code never logs a key, ticket, token, secret word or cookie).
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

[[ ${AVRANA_PACKAGE_PROOF:-} == 1 ]] || { echo 'set AVRANA_PACKAGE_PROOF=1 (CI or a disposable machine only; never the Pi)' >&2; exit 2; }
[[ $(id -u) == 0 ]] || { echo 'run as root (sudo)' >&2; exit 2; }
command -v systemctl >/dev/null && [[ -d /run/systemd/system ]] || { echo 'systemd is not running here' >&2; exit 2; }
command -v curl >/dev/null || { echo 'curl not found' >&2; exit 2; }
command -v runuser >/dev/null || { echo 'runuser not found' >&2; exit 2; }
getent passwd nobody >/dev/null || { echo 'the user nobody does not exist' >&2; exit 2; }
games_repo=${AVRANA_GAMES_REPO:-}
[[ -n $games_repo && -f $games_repo/hello_party/avrgame.build.json && -f $games_repo/hello_party/avrgame.json \
    && -f $games_repo/core/party_protocol.py && -f $games_repo/web/avrana-party-bridge.js \
    && -f $games_repo/avrana_gamekit/__init__.py ]] \
    || { echo 'set AVRANA_GAMES_REPO to a checkout of avrana-party-games with hello_party/avrgame.build.json (the paired AVR-39 branch)' >&2; exit 2; }
games_repo=$(cd "$games_repo" && pwd)

repo=$(cd "$(dirname "$0")/../.." && pwd)
here=$repo/experiments/native-game
work=/run/avrana-package-proof
marker=/run/avrana-package-proof.marker
unit_dir=/etc/systemd/system
rel=/opt/avrana-party/releases/ci
tree=/opt/avrana-party/current
appliance=$tree/contracts/appliances/avrana-pi4.json      # the REAL profile of the release tree
conf=/etc/avrana-party/party-core.json
keydir=/etc/avrana-party/game-keys
key=$keydir/hello.key
entry=/etc/avrana-party/games.d/hello.json
packages=/etc/avrana-party/packages.d
record=$packages/hello.json
groot=/opt/avrana-games
backups=/var/backups/avrana-party
node=/run/avrana-party/internal.sock
sock=/run/avrana-games/hello.sock
dropin_dir=$unit_dir/avrana-game@hello.service.d
party=avrana-party-core.service
psock=avrana-party-core.socket
game=avrana-game@hello.service
gsock=avrana-game@hello.socket
fails=0

# ---- refuse to touch anything that is not ours -------------------------------------------------
# Before the trap exists: a refusal must not run the cleanup below. A marker from an earlier run
# of this script (a crash, then a re-run on the same machine) says the leftovers are ours.
if [[ ! -e $marker ]]; then
    for p in /etc/avrana-party /opt/avrana-party /opt/avrana-party-games /opt/avrana-games /var/backups/avrana-party \
        /var/lib/avrana-party-core /var/lib/avrana-games; do
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
    rm -rf /etc/avrana-party /opt/avrana-party /opt/avrana-party-games /opt/avrana-games /var/backups/avrana-party \
        /var/lib/avrana-party-core /var/lib/private/avrana-party-core /var/lib/avrana-games \
        /var/lib/private/avrana-games /run/avrana-games /run/avrana-party /run/avrana-install-game.lock "$work"
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
    for p in /etc/avrana-party /opt/avrana-party /opt/avrana-party-games /opt/avrana-games /var/backups/avrana-party \
        /run/avrana-games /run/avrana-party "$work" /var/lib/avrana-games /var/lib/private/avrana-games \
        "$unit_dir/$party" "$unit_dir/$psock" "$unit_dir/avrana-game@.socket" "$unit_dir/avrana-game@.service" "$dropin_dir"; do
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
        echo '--- journal (avrana-party-core, avrana-game@hello) ---'
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
prov() { (cd "$tree" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.provision_game "$@"); }
inst() { (cd "$tree" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.install_game "$@"); }
inst_nobody() { (cd "$work" && runuser -u nobody -- env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$tree" python3 -m avrana.ops.install_game "$@"); }
packer() { (cd "$work" && runuser -u nobody -- env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$work/tool" python3 -m avrana.avrgame "$@"); }
prep() { "$tree/ops/prepare-native-games" "$@"; }            # the wrapper, run from the release tree
driver() { python3 "$here/package-driver.py" "$@"; }
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
host_state() {  # a digest of every name (and kind) under the places an install writes; changes iff the host does
    { find /etc/avrana-party /opt/avrana-games /var/lib/avrana-games /var/lib/private/avrana-games /run/avrana-games \
          "$unit_dir"/avrana-game@* -printf '%y %p\n' 2>/dev/null || true; } | sort | sha256sum | cut -d' ' -f1
}
nothing_of_hello() {  # prints what is left of the game "hello" on this host (empty when nothing is)
    local p
    for p in "$record" "$groot/hello" "$key" "$entry" "$dropin_dir" "$sock" /var/lib/avrana-games/hello \
        /var/lib/private/avrana-games/hello; do
        if [[ -e $p || -L $p ]]; then echo "$p"; fi
    done
    return 0
}

echo "systemd $(systemctl --version | head -n1 | awk '{print $2}'), kernel $(uname -r), $(uname -m), $(python3 --version)"

# ---- a. the release tree: root-owned, WITHOUT the contract of the game ------------------------------
opt_mode=$(stat -c %a /opt); echo "$opt_mode" > "$marker.opt-mode"
echo "OBSERVE     /opt is $(stat -c '%U:%G %a' /opt) on this machine; set to 0755 for the run"
chmod 0755 /opt
install -d -m 0755 /opt/avrana-party /opt/avrana-party/releases "$rel" "$rel/deploy" "$rel/deploy/party-core" "$rel/ops"
cp -r "$repo/avrana" "$repo/contracts" "$rel/"
cp -r "$repo/deploy/games" "$rel/deploy/games"
install -m 0644 "$repo/deploy/party-core/avrana-party-core.service" "$repo/deploy/party-core/avrana-party-core.socket" "$rel/deploy/party-core/"
install -m 0755 "$repo/ops/provision-game" "$rel/ops/provision-game"
install -m 0755 "$repo/ops/prepare-native-games" "$rel/ops/prepare-native-games"
install -m 0755 "$repo/ops/install-game" "$rel/ops/install-game"
rm -f "$rel/contracts/games/hello.json"                    # the point: only the package can make Party know this game
find "$rel" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R root:root /opt/avrana-party
chmod -R u=rwX,go=rX /opt/avrana-party
ln -sfn "$rel" "$tree"
t 'the Party release tree is root-owned and not group or world writable' 0 \
    test -z "$(find /opt/avrana-party -not -type l \( -not -user root -o -perm /022 \) -print -quit)"
t 'the Party release tree has NO contract for the game (contracts/games/hello.json is absent)' nonzero \
    test -e "$tree/contracts/games/hello.json"
t 'and the real appliance profile does not mention the game at all' nonzero grep -q hello "$appliance"
# The owner's prerequisite for packages: an empty root-owned games root (docs/runbooks/install-game.md).
install -d -m 0755 -o root -g root "$groot"
mkdir -m 0755 "$work"

# ---- b. identities, as ADR 0016 phase 1 (ops/migrate-service-users.sh) --------------------------------
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

# ---- c. Party Core on its EARLIER unit, then ops/prepare-native-games ----------------------------------
sed -e '/^ExecReload=/d' -e '/^Wants=avrana-party-core\.socket$/d' \
    -e 's/^After=network\.target avrana-party-core\.socket$/After=network.target/' \
    "$repo/deploy/party-core/avrana-party-core.service" > "$work/earlier.service"
install -m 0644 "$work/earlier.service" "$unit_dir/$party"
systemctl daemon-reload
# The "packages" key is the owner's one-time edit that lets Party Core read install records.
cat > "$conf" <<'JSON'
{
  "hosts": ["party.ci.test"],
  "origins": ["http://party.ci.test"],
  "secure_cookie": false,
  "games": {},
  "packages": "/etc/avrana-party/packages.d",
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
capture prep
show 'prepare-native-games' "$out"
check 'ops/prepare-native-games exits 0' 0 "$rc"
t 'prepare-native-games kept the "packages" key of party-core.json' 0 \
    python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); assert c["packages"]=="/etc/avrana-party/packages.d" and c["registry"]=="/etc/avrana-party/games.d", c' "$conf"
wait_ready
t 'Party Core was restarted onto the socket, is active and answers on loopback' 0 test "$ready" = 0
pid_before=$(pid)
since_before=$(entered "$party")

# ---- d. the game is unknown: only a package can introduce it ----------------------------------------------
capture prov hello --appliance "$appliance"
refused 'provision-game alone refuses the game: this appliance has no Game Contract for it' 'no Game Contract'
run_driver 'Party Core does not offer the game yet' --absent

# ---- e. build, UNPRIVILEGED, from the committed recipe ----------------------------------------------------------
src=$work/src; tool=$work/tool; build=$work/build
install -d -m 0755 "$src" "$src/core" "$src/web" "$tool" "$build"
cp -r "$games_repo/hello_party" "$games_repo/avrana_gamekit" "$src/"
cp "$games_repo/core/__init__.py" "$games_repo/core/party_protocol.py" "$games_repo/core/party_result.py" "$src/core/"
cp "$games_repo/web/avrana-party-bridge.js" "$src/web/"
cp -r "$repo/avrana" "$repo/contracts" "$tool/"
find "$src" "$tool" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R root:root "$src" "$tool"
chmod -R u=rwX,go=rX "$src" "$tool"
chown nobody "$build"
recipe=$src/hello_party/avrgame.build.json
capture packer pack "$recipe" --out "$build/a.avrgame"
show 'pack (nobody)' "$out"
check 'the package builds from the committed recipe as an unprivileged user' 0 "$rc"
sha_a=$(sed -n 's/^sha256: //p' <<<"$out")
capture packer pack "$recipe" --out "$build/b.avrgame"
check 'a second build succeeds' 0 "$rc"
sha_b=$(sed -n 's/^sha256: //p' <<<"$out")
check 'two builds are byte-identical (same sha256, same bytes)' 0 \
    "$([[ -n $sha_a && $sha_a == "$sha_b" ]] && cmp -s "$build/a.avrgame" "$build/b.avrgame" && echo 0 || echo 1)"
t 'the archive is owned by the unprivileged user, not root' 0 test "$(stat -c %U "$build/a.avrgame")" = nobody
capture packer validate "$build/a.avrgame"
show 'validate' "$out"
check 'validate passes and agrees on the sha256' 0 "$([[ $rc == 0 && $out == *"$sha_a"* ]] && echo 0 || echo 1)"
sha12=${sha_a:0:12}

# ---- f. refusals: each leaves the host exactly as it was -----------------------------------------------------------
python3 - "$build/a.avrgame" "$build" <<'PY'
import json, sys, zipfile
src, out = sys.argv[1:3]
data = open(src, 'rb').read()
flipped = bytearray(data)
flipped[data.index(b'import ')] ^= 0x01            # one byte inside a stored source file: the CRC no longer matches
open(f'{out}/tampered.avrgame', 'wb').write(flipped)

def rewrite(name, edit=None, extra=()):
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(f'{out}/{name}', 'w', zipfile.ZIP_STORED) as zout:
        for info in zin.infolist():
            blob = zin.read(info)
            if info.filename == 'avrgame.json' and edit:
                doc = json.loads(blob)
                edit(doc)
                blob = json.dumps(doc).encode()
            copy = zipfile.ZipInfo(info.filename, (1980, 1, 1, 0, 0, 0))
            copy.compress_type, copy.external_attr = zipfile.ZIP_STORED, info.external_attr
            zout.writestr(copy, blob)
        for entry, blob in extra:
            item = zipfile.ZipInfo(entry, (1980, 1, 1, 0, 0, 0))
            item.compress_type, item.external_attr = zipfile.ZIP_STORED, 0o100644 << 16
            zout.writestr(item, blob)

rewrite('format.avrgame', lambda m: m.update(format='avrana.avrgame/experimental.2'))
rewrite('traversal.avrgame', extra=[('../evil.py', b'print(1)\n')])
rewrite('collides.avrgame', lambda m: m['game'].update(id='checkers'))
PY
chmod 0644 "$build"/*.avrgame
host_before=$(host_state)
capture inst install "$build/tampered.avrgame" --grant party_roster
refused 'a tampered archive is refused' 'package refused'
capture inst install "$build/format.avrgame" --grant party_roster
refused 'a manifest with a newer format is refused (compatibility fails closed)' 'package refused'
capture inst install "$build/traversal.avrgame" --grant party_roster
refused 'an archive with a ../ entry is refused' 'package refused'
capture inst install "$build/collides.avrgame" --grant party_roster
refused 'a package with the id of a first-party game (checkers) is refused' 'first-party'
capture inst_nobody install "$build/a.avrgame" --grant party_roster
refused 'an install by a non-root user is refused' 'must run as root'
t 'none of those left anything behind (the host is byte-for-byte as before, by name)' 0 test "$(host_state)" = "$host_before"
t 'and nothing of the game exists on the host' 0 test -z "$(nothing_of_hello)"
t 'and no failed run left a staging directory in the games root' 0 test -z "$(find "$groot" -mindepth 1 -print -quit)"
# AVR-336: a grant must not say more than the sandbox gives, and the roster arrives whatever was granted
capture inst install "$build/a.avrgame" --grant party_roster --grant camera
refused 'a grant the package sandbox cannot provide (camera) is refused, not recorded' 'cannot provide'
capture inst install "$build/a.avrgame"
refused 'an install without --grant party_roster is refused: Party Core hands every game the roster' 'receives the Party roster'
t 'neither of those left anything behind' 0 test "$(host_state)" = "$host_before"
# AVR-336: a stray directory under the games root never makes a first-party game removable
mkdir "$groot/checkers"
echo stray > "$groot/checkers/keep.txt"
capture inst remove checkers
refused 'remove refuses a first-party id even when a stray directory of that name exists' 'first-party'
t 'and the stray directory is untouched' 0 test -f "$groot/checkers/keep.txt"
rm -rf "$groot/checkers"
t 'and the host is as before' 0 test "$(host_state)" = "$host_before"

# ---- g. install --------------------------------------------------------------------------------------------------------
capture inst install "$build/a.avrgame" --grant party_roster --dry-run
show 'dry run' "$out"
check 'install --dry-run exits 0 and says what it would do' 0 "$([[ $rc == 0 && $out == *'would install 0.1.0'* && $out == *"would stage"* ]] && echo 0 || echo 1)"
t 'a dry run changed nothing' 0 test "$(host_state)" = "$host_before"
t 'a dry run wrote no install record' nonzero test -e "$record"

capture inst install "$build/a.avrgame" --grant party_roster
show 'install' "$out"
check 'install-game install exits 0' 0 "$rc"
staged=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root"])' "$record")
check 'the staged tree is /opt/avrana-games/hello/<version>-<first 12 hex of the archive sha256>' 0 \
    "$([[ $staged == "/opt/avrana-games/hello/0.1.0-$sha12" ]] && echo 0 || echo 1)"
t 'the staged tree exists and holds the game (hello_party/__main__.py and the bridge shim)' 0 \
    test -f "$staged/hello_party/__main__.py" -a -f "$staged/web/avrana-party-bridge.js" -a -f "$staged/avrgame.json"
t 'the staged tree is root-owned and nothing in it is group or world writable' 0 \
    test -z "$(find "$groot" -not -type l \( -not -user root -o -perm /022 \) -print -quit)"
t 'no symbolic link is anywhere in the staged tree' 0 test -z "$(find "$groot" -type l -print -quit)"
t 'the install record is root:root 0644' 0 test "$(stat -c '%U:%G %a' "$record")" = 'root:root 644'
t 'install-game verify: every staged file matches the record' 0 inst verify hello
t 'the registry entry names the game socket and key' 0 \
    python3 -c 'import json,sys; e=json.load(open(sys.argv[1])); assert e["id"]=="hello" and e["socket"]=="/run/avrana-games/hello.sock" and e["key_file"]==sys.argv[2], e' "$entry" "$key"
t 'the key exists, 0600, owned by avrana-party' 0 test "$(stat -c '%a %U:%G' "$key")" = '600 avrana-party:avrana-party'
t 'the drop-in carries the community-tier ceilings (MemoryMax, TasksMax, CPUQuota) and confinement' 0 \
    bash -c 'for l in MemoryMax=256M TasksMax=64 CPUQuota=100% CapabilityBoundingSet= PrivateNetwork=yes ProtectProc=invisible RestrictNamespaces=yes; do grep -qxF "$l" "$1/exec.conf" || { echo "missing $l"; exit 1; }; done' _ "$dropin_dir"
t 'the exec drop-in runs /usr/bin/python3 -m hello_party from the STAGED tree' 0 \
    bash -c 'grep -qxF "ExecStart=\"/usr/bin/python3\" \"-m\" \"hello_party\"" "$1/exec.conf" && grep -qxF "WorkingDirectory=$2" "$1/exec.conf"' _ "$dropin_dir" "$staged"
t 'the drop-in hands the game the Party origin from party-core.json' 0 \
    grep -qxF 'Environment=AVRANA_PARTY_ORIGIN=http://party.ci.test' "$dropin_dir/exec.conf"
t 'the socket unit is enabled and active; the game is socket-activated (service not yet running)' 0 \
    bash -c 'systemctl is-enabled --quiet "$1" && systemctl is-active --quiet "$1" && ! systemctl is-active --quiet "$2"' _ "$gsock" "$game"
t 'install-game reloaded Party Core and did not restart it (same process, same activation time)' 0 \
    test "$(pid)" = "$pid_before" -a "$(entered "$party")" = "$since_before"
run_driver 'Party Core (reloaded) now offers the game, known only through its install record' --offered
capture inst list
show 'list' "$out"
check 'list shows the package, tier community, the grant and the publisher as an unverified claim' 0 \
    "$([[ $out == *'hello 0.1.0'* && $out == *'tier community'* && $out == *'granted: party_roster'* && $out == *'(unverified claim)'* ]] && echo 0 || echo 1)"
t 'list --json says the tree still verifies' 0 \
    python3 -c 'import json,sys; d=json.loads(sys.argv[1])["installed"]; assert len(d)==1 and d[0]["id"]=="hello" and d[0]["tree"]=="ok" and d[0]["tier"]=="community" and d[0]["permissions_granted"]==["party_roster"], d' "$(inst list --json)"

catalog_sha=$(sha_of "$repo/web/party/catalog.json")
# the generated catalog (a file in $work: the committed catalog and the appliance's web root are not touched)
mkdir "$work/cat-games"
cp "$tree/contracts/games/checkers.json" "$work/cat-games/"
python3 - "$repo/tests/fixtures/appliances/ci-hello.json" "$work/cat-appliance.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
doc['installed'] = []                                    # this profile grants no game at all; only the package can
json.dump(doc, open(sys.argv[2], 'w'))
PY
catalog() { (cd "$tree" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.contracts.catalog --games "$work/cat-games" \
    --appliance "$work/cat-appliance.json" --packages "$packages" --out "$1"); }
capture catalog "$work/catalog-with.json"
check 'the catalog generator accepts --packages with an explicit --out' 0 "$rc"
t 'the generated catalog lists the package installed, at /games/hello/, native' 0 \
    python3 -c 'import json,sys; g={x["id"]:x for x in json.load(open(sys.argv[1]))["games"]}; h=g["hello"]; assert h["installed"] is True and h["entry"]=="/games/hello/" and h["provider"]=="native" and h["status"]=="current" and h["playableHere"] is True, h; assert g["checkers"]["installed"] is False' "$work/catalog-with.json"
capture bash -c 'cd "$1" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.contracts.catalog --packages "$2"' _ "$tree" "$packages"
check 'catalog --packages without an explicit --out is refused (exit 2): the committed catalog is never the target' 0 "$([[ $rc == 2 ]] && echo 0 || echo 1)"
t 'the committed web/party/catalog.json is byte-identical before and after' 0 test "$(sha_of "$repo/web/party/catalog.json")" = "$catalog_sha"

host_installed=$(host_state)
capture inst install "$build/a.avrgame" --grant party_roster
refused 'a second install of the same id is refused ("remove it first")' 'remove it first'
t 'and the refused second install changed nothing' 0 test "$(host_state)" = "$host_installed"
vf=$staged/hello_party/__main__.py
cp -p "$vf" "$work/main.keep"                     # under set -e: a failed backup stops the proof loudly
echo '#' >> "$vf"
t 'verify catches a modified staged file' nonzero inst verify hello
cp -p "$work/main.keep" "$vf"
t 'and verify passes again once the file is restored' 0 inst verify hello

# ---- h. session 1: a complete session, then the boundary checker while the game is up ----------------------------------------
run_driver 'session 1: two players and a watcher, private secret words, hello over the game API, reconnect, result accepted, home'
t 'the game (socket-activated) is running' 0 systemctl is-active --quiet "$game"
gpid=$(systemctl show -p MainPID --value "$game")
t 'the game process runs from the STAGED package tree (/proc/<pid>/cwd)' 0 \
    test "$(readlink -f "/proc/$gpid/cwd")" = "$(readlink -f "$staged")"
t 'the unit WorkingDirectory is the staged tree' 0 test "$(systemctl show -p WorkingDirectory --value "$game")" = "$staged"
t 'the game runs as a systemd DynamicUser (DynamicUser=yes) and not as root' 0 \
    bash -c 'test "$(systemctl show -p DynamicUser --value "$1")" = yes && test "$(ps -o uid= -p "$2" | tr -d " ")" != 0' _ "$game" "$gpid"
echo "OBSERVE     the game runs as user $(ps -o user= -p "$gpid" | tr -d ' ')"
# AVR-336: the ceilings and confinement are real on the running process, not only written in a file
t 'systemd applies MemoryMax=256M, TasksMax=64 and CPUQuota=100% to the game unit' 0 \
    bash -c 'test "$(systemctl show -p MemoryMax --value "$1")" = 268435456 && test "$(systemctl show -p TasksMax --value "$1")" = 64 && test "$(systemctl show -p CPUQuotaPerSecUSec --value "$1")" = 1s' _ "$game"
echo "OBSERVE     memory.max in the cgroup: $(cat "/sys/fs/cgroup/system.slice/$game/memory.max" 2>/dev/null || echo 'not readable here')"
t 'the game process has no capability at all (CapBnd and CapEff are zero)' 0 \
    bash -c '! grep -E "^Cap(Bnd|Eff):" "/proc/$1/status" | grep -qv "0000000000000000$"' _ "$gpid"
t 'the game is in its own network namespace (no abstract sockets of the host)' 0 \
    test "$(readlink "/proc/$gpid/ns/net")" != "$(readlink /proc/1/ns/net)"
t 'ProtectProc=invisible is applied to the game unit (other users processes are hidden from it)' 0 \
    bash -c 'test "$(systemctl show -p ProtectProc --value "$1")" = invisible' _ "$game"
t 'the game received the signed launch (journal)' 0 journal_has "$game" 'launched ('
t 'the game reported its signed ended and the party accepted the result (journal)' 0 journal_has "$game" 'the party accepted the result'
t 'Party Core was not restarted by any of it' 0 test "$(pid)" = "$pid_before"
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
assert any('hello' in r['subject'] for r in rows), 'no rule names the hello game'
assert not bad, 'rules not met: ' + '; '.join(bad)
PY
)
check 'boundary --phase 2 with the installed package: every rule is present and met, and a rule names the game' 0 "$s"

# AVR-336: what an identity with a package game's groups can reach. A transient unit with the template's
# identity (DynamicUser, SupplementaryGroups=avrana-games, AF_UNIX only) stands in for the game process.
cat > "$work/probe.py" <<'PY'
import socket, sys

def connect(path):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(3)
    try:
        s.connect(path)
        return 'connected'
    except PermissionError:
        return 'denied'
    except OSError as exc:
        return f'error-{exc.errno}'
    finally:
        s.close()

def read(path):
    try:
        with open(path, 'rb') as f:
            f.read(1)
        return 'read'
    except PermissionError:
        return 'denied'
    except OSError as exc:
        return f'error-{exc.errno}'

print('connect-game-socket', connect('/run/avrana-games/hello.sock'))
print('connect-party-internal', connect('/run/avrana-party/internal.sock'))
print('read-game-key', read('/etc/avrana-party/game-keys/hello.key'))
print('read-record', read('/etc/avrana-party/packages.d/hello.json'))
PY
chmod 0644 "$work/probe.py"
set +e
systemd-run --quiet --wait --pipe --collect -p DynamicUser=yes -p SupplementaryGroups=avrana-games \
    -p RestrictAddressFamilies=AF_UNIX /usr/bin/python3 -I "$work/probe.py" > "$work/probe.out" 2>&1
probe_rc=$?
set -e
show 'identity with the games group (as a package game has it)' "$(cat "$work/probe.out")"
check 'the probe ran as a transient dynamic user' 0 "$probe_rc"
t 'an identity in avrana-games alone cannot connect to a game socket (root:avrana-front 0660): other games stay unreachable' 0 \
    grep -qx 'connect-game-socket denied' "$work/probe.out"
t 'and the same identity CAN connect to Party Core internal socket (so the denial above is not vacuous)' 0 \
    grep -qx 'connect-party-internal connected' "$work/probe.out"
t 'it cannot read the key store (the keys are the Party own)' 0 grep -qx 'read-game-key denied' "$work/probe.out"
t 'it can read the world-readable install record (documented: records hold no secret)' 0 grep -qx 'read-record read' "$work/probe.out"

# ---- i. session 2: removal is refused during a live session; the Host ends it ----------------------------------------------------
run_driver 'session 2: remove is refused during the live session, then the Host ends it from Party' --end --cwd "$tree" \
    --during-live python3 -m avrana.ops.install_game remove hello
t 'the package is still fully installed after the refused removal' 0 bash -c 'test -f "$1" && test -d "$2" && test -f "$3"' _ "$record" "$staged" "$entry"
t 'the game saw the end the Party sent (journal: ended by the party)' 0 journal_has "$game" 'ended by the party'
gone=1
for _ in $(seq 1 100); do                    # the game releases its process after 60 s without a session
    if ! systemctl is-active --quiet "$game"; then gone=0; break; fi
    sleep 1
done
check 'the game process holds no session: it exited on its own (idle stop) after the end; the socket stays' 0 "$gone"

# ---- j. remove ----------------------------------------------------------------------------------------------------------------------
sleep 7                                   # longer than Party Core's status cache: remove must not see the finished session as live
capture inst remove hello --dry-run
show 'remove dry run' "$out"
check 'remove --dry-run exits 0 and removes nothing' 0 "$([[ $rc == 0 && $out == *'would remove'* && -f $record ]] && echo 0 || echo 1)"
capture inst remove hello
show 'remove' "$out"
check 'install-game remove exits 0' 0 "$rc"
t 'nothing of the game is left (record, staged tree, key, registry entry, drop-in, socket, state)' 0 test -z "$(nothing_of_hello)"
t 'the socket unit is neither enabled nor active, the service is not active' nonzero \
    bash -c 'systemctl is-enabled --quiet "$1" || systemctl is-active --quiet "$1" || systemctl is-active --quiet "$2"' _ "$gsock" "$game"
t 'Party Core is still active and was never restarted since the first install' 0 \
    test "$(pid)" = "$pid_before" -a "$(entered "$party")" = "$since_before"
run_driver 'Party Core no longer offers the game' --absent
capture catalog "$work/catalog-without.json"
t 'the generated catalog no longer lists the game' 0 \
    python3 -c 'import json,sys; g={x["id"] for x in json.load(open(sys.argv[1]))["games"]}; assert "hello" not in g, g' "$work/catalog-without.json"
t 'list shows nothing installed' 0 bash -c '[[ $(cd "$1" && python3 -m avrana.ops.install_game list) == "no packages installed" ]]' _ "$tree"
capture inst remove hello
show 'second remove' "$out"
check 'a second remove is a clean no-op' 0 "$([[ $rc == 0 && $out == *'nothing to remove'* ]] && echo 0 || echo 1)"

# ---- k. install again, then remove again --------------------------------------------------------------------------------------------
capture inst install "$build/a.avrgame" --grant party_roster
check 're-installing after a removal works' 0 "$rc"
run_driver 'Party Core offers the re-installed game' --offered
t 'the re-installed tree is the same version and hash' 0 test -d "$groot/hello/0.1.0-$sha12"
capture inst remove hello
check 'and removing it again works' 0 "$rc"
t 'nothing of the game is left again' 0 test -z "$(nothing_of_hello)"
t 'Party Core was never restarted in the whole run' 0 test "$(pid)" = "$pid_before" -a "$(entered "$party")" = "$since_before"

# ---- l. summary (the cleanup trap restores the host and says so) ------------------------------------------------------------------------
echo "failed checks: $fails"
[[ $fails == 0 ]]
