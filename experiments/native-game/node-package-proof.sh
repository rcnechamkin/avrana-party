#!/usr/bin/env bash
# Non-production proof for AVR-68 (EXPERIMENTAL .avrgame packages on the optional Node.js runtime):
# the pinned Node build is installed OFFLINE by the real `install-node-runtime` from a tarball that
# must match the SHA-256 pinned in the repository; the Node fixture game (tests/fixtures/node-game)
# is built unprivileged, refused while the runtime is missing, installed by the REAL `install-game`
# through the REAL `provision-game` path, launched by Party Core over its Unix socket, played by
# "phones", ended, and removed again without a trace. Linux + systemd + root only.
#
#   sudo AVRANA_NODE_PROOF=1 AVRANA_NODE_TARBALL=/path/to/node-v<version>-linux-<arch>.tar.xz \
#        bash experiments/native-game/node-package-proof.sh
#
# Run it in CI or on a disposable Linux machine. NEVER on the Pi: that would be an unauthorized
# change to the appliance (AGENTS.md). Like package-proof.sh, whose first steps it repeats, it
# refuses to start when /etc/avrana-party, /opt/avrana-party, /opt/avrana-games,
# /opt/avrana-runtimes, the user avrana-party or the groups avrana-front / avrana-games already
# exist, so it can never eat a real installation. It calls the tools; it never changes them. This
# script downloads nothing: whoever runs it brings the tarball (the CI job fetches it first).
#
# THE STORY, on a clean host:
#   1. ADR 0016 phase 1, Party Core on its earlier unit, ops/prepare-native-games, the owner
#      prerequisites of the runbook (as package-proof.sh);
#   2. the fixture is packed by an UNPRIVILEGED user from its recipe with its dependency vendored
#      under node_modules, twice: identical sha256;
#   3. WITHOUT the runtime, `install-game install` refuses the Node package and says what to do;
#   4. `install-node-runtime`: a tampered tarball and a non-root run are refused; the install runs
#      in a network namespace with no interface at all (offline); the tree is root-owned and holds
#      the binary, the licence and a record, nothing else (no npm); a second run changes nothing;
#   5. refusals of the package: a native addon, compiled code under another name, a `.js` entry;
#   6. `install-game install --grant party_roster`: the drop-in runs the pinned node by absolute
#      path on the package's `.mjs` entry, with the ceilings and confinement of every package; no
#      install script of the vendored package.json ran;
#   7. session 1 (package-driver.py --game hellonode): the socket-activated process IS the pinned
#      node, runs from the staged tree as a DynamicUser, in the unit's sandbox (`systemctl show`),
#      V8 maps executable memory there (WebAssembly compiles and runs), MemoryMax and TasksMax are
#      applied, the game ends by itself with a signed `ended` that Party Core accepts; the RSS,
#      thread and task counts of the idle process are MEASURED and printed; a transient unit with
#      the same confinement shows that the runtime reaches no IP address, not even Party Core's
#      loopback port; `--jitless` is measured beside the default;
#   8. session 2: `install-game remove` is refused during the live session; the Host ends it; the
#      process stops by itself when idle;
#   9. `install-node-runtime remove` is refused while the package is installed; `install-game
#      remove`; then the runtime is removed and nothing is left.
#
# Output: one line per check. CHECK lines are assumptions the design depends on (a FAIL exits 1).
# OBSERVE lines record behaviour worth reading either way; MEASURE lines are the numbers.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

[[ ${AVRANA_NODE_PROOF:-} == 1 ]] || { echo 'set AVRANA_NODE_PROOF=1 (CI or a disposable machine only; never the Pi)' >&2; exit 2; }
[[ $(id -u) == 0 ]] || { echo 'run as root (sudo)' >&2; exit 2; }
command -v systemctl >/dev/null && [[ -d /run/systemd/system ]] || { echo 'systemd is not running here' >&2; exit 2; }
for tool in curl runuser unshare nsenter systemd-run; do
    command -v "$tool" >/dev/null || { echo "$tool not found" >&2; exit 2; }
done
getent passwd nobody >/dev/null || { echo 'the user nobody does not exist' >&2; exit 2; }
tarball=${AVRANA_NODE_TARBALL:-}
[[ -n $tarball && -f $tarball ]] || { echo 'set AVRANA_NODE_TARBALL to the official tarball of the pinned Node build for this machine' >&2; exit 2; }

repo=$(cd "$(dirname "$0")/../.." && pwd)
here=$repo/experiments/native-game
fixture=$repo/tests/fixtures/node-game
[[ -f $fixture/avrgame.json && -f $fixture/server/main.mjs ]] || { echo "the Node fixture game is missing ($fixture)" >&2; exit 2; }
id=hellonode
work=/run/avrana-node-proof
marker=/run/avrana-node-proof.marker
unit_dir=/etc/systemd/system
rel=/opt/avrana-party/releases/ci
tree=/opt/avrana-party/current
appliance=$tree/contracts/appliances/avrana-pi4.json
conf=/etc/avrana-party/party-core.json
keydir=/etc/avrana-party/game-keys
key=$keydir/$id.key
entry=/etc/avrana-party/games.d/$id.json
packages=/etc/avrana-party/packages.d
web=/var/www/avrana-party/web
overlay=/var/lib/avrana-party/catalog/catalog.json
record=$packages/$id.json
groot=/opt/avrana-games
runtimes=/opt/avrana-runtimes
sock=/run/avrana-games/$id.sock
dropin_dir=$unit_dir/avrana-game@$id.service.d
party=avrana-party-core.service
psock=avrana-party-core.socket
game=avrana-game@$id.service
gsock=avrana-game@$id.socket
mark=avr68-lifecycle-ran
fails=0

# ---- refuse to touch anything that is not ours -------------------------------------------------
if [[ ! -e $marker ]]; then
    for p in /etc/avrana-party /opt/avrana-party /opt/avrana-party-games /opt/avrana-games "$runtimes" /var/backups/avrana-party \
        /var/lib/avrana-party-core /var/lib/avrana-games /var/lib/avrana-party /var/www/avrana-party; do
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
    rm -rf /etc/avrana-party /opt/avrana-party /opt/avrana-party-games /opt/avrana-games "$runtimes" /var/backups/avrana-party \
        /var/lib/avrana-party-core /var/lib/private/avrana-party-core /var/lib/avrana-games \
        /var/lib/private/avrana-games /run/avrana-games /run/avrana-party /run/avrana-install-game.lock "$work" \
        /var/lib/avrana-party /var/www/avrana-party "/tmp/$mark"
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
leftovers() {
    local p
    for p in /etc/avrana-party /opt/avrana-party /opt/avrana-party-games /opt/avrana-games "$runtimes" /var/backups/avrana-party \
        /run/avrana-games /run/avrana-party "$work" /var/lib/avrana-games /var/lib/private/avrana-games \
        /var/lib/avrana-party /var/www/avrana-party \
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
        echo "--- journal (avrana-party-core, avrana-game@$id) ---"
        journalctl -u "$party" -u "$psock" -u "$game" -u "$gsock" --no-pager -n 150
        echo '--- end journal ---'
    fi
    cleanup
    local left
    left=$(leftovers | paste -sd' ')
    if [[ -z $left ]]; then echo 'CHECK PASS  the cleanup restored the host: no user, group, directory, runtime or unit of this proof is left'
    else echo "CHECK FAIL  the cleanup left: $left"; (( rc == 0 )) && rc=1; fi
    exit $rc
}
touch "$marker"
trap on_exit EXIT
cleanup && touch "$marker"

check() {
    if { [[ $2 == 0 && $3 == 0 ]] || [[ $2 != 0 && $3 != 0 ]]; }; then echo "CHECK PASS  $1"
    else echo "CHECK FAIL  $1 (status $3)"; fails=$((fails + 1)); fi
}
t() {
    local name=$1 want=$2; shift 2
    set +e; "$@" >/dev/null 2>&1; local s=$?; set -e
    check "$name" "$want" "$s"
}
status() { set +e; "$@" >&2; local s=$?; set -e; echo "$s"; }
capture() { set +e; out=$("$@" 2>&1); rc=$?; set -e; }
show() { local line; while IFS= read -r line; do echo "OBSERVE     $1: $line"; done <<<"$2"; }
inst() { (cd "$tree" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.install_game "$@"); }
inst_nobody() { (cd "$work" && runuser -u nobody -- env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$tree" python3 -m avrana.ops.install_game "$@"); }
packer() { (cd "$work" && runuser -u nobody -- env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$work/tool" python3 -m avrana.avrgame "$@"); }
noderuntime() { "$tree/ops/install-node-runtime" "$@"; }
prep() { "$tree/ops/prepare-native-games" "$@"; }
driver() { python3 "$here/package-driver.py" --game "$id" "$@"; }
party_status() { curl -fsS --max-time 10 -H 'Host: party.ci.test' http://127.0.0.1:8191/party/api/status; }
pid() { systemctl show -p ExecMainPID --value "$party"; }
entered() { systemctl show -p ActiveEnterTimestampMonotonic --value "$1"; }
prop() { systemctl show -p "$1" --value "$game"; }
wait_ready() {
    ready=1
    for _ in $(seq 1 60); do
        if systemctl is-active --quiet "$party" && party_status >/dev/null 2>&1; then ready=0; break; fi
        sleep 0.5
    done
}
refused() { check "$1" 0 "$([[ $rc == 1 && $out == *"$2"* ]] && echo 0 || echo 1)"; }
journal_has() { journalctl --sync >/dev/null 2>&1 || true; journalctl -u "$1" --no-pager 2>/dev/null | grep -qF -- "$2"; }
run_driver() {
    local name=$1 s out_file="$work/driver.out"; shift
    set +e; driver "$@" >"$out_file" 2>&1; s=$?; set -e
    show "driver ($name)" "$(cat "$out_file")"
    check "$name" 0 "$s"
}
host_state() {
    { find /etc/avrana-party /opt/avrana-games /var/lib/avrana-games /var/lib/private/avrana-games /run/avrana-games \
          "$unit_dir"/avrana-game@* -printf '%y %p\n' 2>/dev/null || true; } | sort | sha256sum | cut -d' ' -f1
}
nothing_of_game() {
    local p
    for p in "$record" "$groot/$id" "$key" "$entry" "$dropin_dir" "$sock" "/var/lib/avrana-games/$id" \
        "/var/lib/private/avrana-games/$id"; do
        if [[ -e $p || -L $p ]]; then echo "$p"; fi
    done
    return 0
}
marks() { find /tmp /var/tmp /root /opt/avrana-games /opt/avrana-party "$work" -name "$mark" 2>/dev/null; }

echo "systemd $(systemctl --version | head -n1 | awk '{print $2}'), kernel $(uname -r), $(uname -m), $(python3 --version)"

# ---- a. the release tree, root-owned --------------------------------------------------------------
opt_mode=$(stat -c %a /opt); echo "$opt_mode" > "$marker.opt-mode"
chmod 0755 /opt
install -d -m 0755 /opt/avrana-party /opt/avrana-party/releases "$rel" "$rel/deploy" "$rel/deploy/party-core" "$rel/ops"
cp -r "$repo/avrana" "$repo/contracts" "$rel/"
cp -r "$repo/deploy/games" "$rel/deploy/games"
install -m 0644 "$repo/deploy/party-core/avrana-party-core.service" "$repo/deploy/party-core/avrana-party-core.socket" "$rel/deploy/party-core/"
for tool in provision-game prepare-native-games install-game catalog-overlay install-node-runtime; do
    install -m 0755 "$repo/ops/$tool" "$rel/ops/$tool"
done
find "$rel" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R root:root /opt/avrana-party
chmod -R u=rwX,go=rX /opt/avrana-party
ln -sfn "$rel" "$tree"
t 'the Party release tree is root-owned and not group or world writable' 0 \
    test -z "$(find /opt/avrana-party -not -type l \( -not -user root -o -perm /022 \) -print -quit)"
t 'the Party release tree has no contract for the fixture game: only its package can make Party know it' nonzero \
    test -e "$tree/contracts/games/$id.json"
install -d -m 0755 -o root -g root "$groot"
install -d -m 0755 -o root -g root /var/www/avrana-party "$web" "$web/releases" "$web/releases/ci"
install -m 0644 -o root -g root "$repo/web/party/catalog.json" "$web/releases/ci/catalog.json"
ln -sfn "$web/releases/ci" "$web/current"
install -d -m 0711 -o root -g root /var/lib/avrana-party
mkdir -m 0755 "$work"
nodebin=$(cd "$tree" && python3 -c 'from avrana.avrgame import node_pin; print(node_pin.EXECUTABLE)')
nodeversion=$(cd "$tree" && python3 -c 'from avrana.avrgame import node_pin; print(node_pin.VERSION)')
noderoot=$(dirname "$(dirname "$nodebin")")
echo "OBSERVE     the pinned runtime is Node $nodeversion at $nodebin"

# ---- b. identities, as ADR 0016 phase 1 ---------------------------------------------------------------
for g in avrana-front avrana-games; do groupadd --system "$g"; done
useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin avrana-party
if ! getent passwd www-data >/dev/null; then
    useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin www-data
    echo www-data >> "$marker"
fi
usermod -a -G avrana-front avrana-party
usermod -a -G avrana-front www-data
install -d -m 0755 -o root -g root /etc/avrana-party
install -d -m 0700 -o avrana-party -g avrana-party "$keydir"

# ---- c. Party Core on its earlier unit, then ops/prepare-native-games ---------------------------------
sed -e '/^ExecReload=/d' -e '/^Wants=avrana-party-core\.socket$/d' \
    -e 's/^After=network\.target avrana-party-core\.socket$/After=network.target/' \
    "$repo/deploy/party-core/avrana-party-core.service" > "$work/earlier.service"
install -m 0644 "$work/earlier.service" "$unit_dir/$party"
systemctl daemon-reload
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
wait_ready
t 'Party Core was restarted onto the socket, is active and answers on loopback' 0 test "$ready" = 0
pid_before=$(pid)
since_before=$(entered "$party")
t 'Party Core runs with no Node runtime on the host at all' nonzero test -e "$runtimes"
run_driver 'Party Core does not offer the game yet' --absent

# ---- d. build the fixture, UNPRIVILEGED, dependency vendored as plain files ------------------------------
src=$work/src; tool=$work/tool; build=$work/build
install -d -m 0755 "$src" "$tool" "$build"
cp "$fixture/avrgame.json" "$fixture/avrgame.build.json" "$src/"
cp -r "$fixture/server" "$fixture/web" "$src/"
cp -r "$fixture/vendored" "$src/node_modules"            # vendored: copied files. Nothing runs npm, here or anywhere
cp -r "$repo/avrana" "$repo/contracts" "$tool/"
find "$src" "$tool" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R root:root "$src" "$tool"
chmod -R u=rwX,go=rX "$src" "$tool"
chown nobody "$build"
capture packer pack "$src/avrgame.build.json" --out "$build/a.avrgame"
show 'pack (nobody)' "$out"
check 'the Node package builds from its recipe as an unprivileged user' 0 "$rc"
sha_a=$(sed -n 's/^sha256: //p' <<<"$out")
capture packer pack "$src/avrgame.build.json" --out "$build/b.avrgame"
sha_b=$(sed -n 's/^sha256: //p' <<<"$out")
check 'two builds are byte-identical (same sha256, same bytes), node_modules included' 0 \
    "$([[ -n $sha_a && $sha_a == "$sha_b" ]] && cmp -s "$build/a.avrgame" "$build/b.avrgame" && echo 0 || echo 1)"
capture packer inspect "$build/a.avrgame"
show 'inspect' "$out"
check 'the package declares the node runtime and its .mjs entry, and carries its vendored dependency' 0 \
    "$([[ $rc == 0 && $out == *'server: node server/main.mjs'* && $out == *'node_modules/avr-fixture-dep/package.json'* ]] && echo 0 || echo 1)"
sha12=${sha_a:0:12}
python3 - "$build/a.avrgame" "$build" <<'PY'
import json, sys, zipfile
src, out = sys.argv[1:3]

def rewrite(name, edit=None, extra=(), rename=None):
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(f'{out}/{name}', 'w', zipfile.ZIP_STORED) as zout:
        for info in zin.infolist():
            blob = zin.read(info)
            target = info.filename
            if info.filename == 'avrgame.json' and edit:
                doc = json.loads(blob)
                edit(doc)
                blob = json.dumps(doc).encode()
            if rename and target in rename:
                target = rename[target]
            copy = zipfile.ZipInfo(target, (1980, 1, 1, 0, 0, 0))
            copy.compress_type, copy.external_attr = zipfile.ZIP_STORED, info.external_attr
            zout.writestr(copy, blob)
        for entry, blob in extra:
            item = zipfile.ZipInfo(entry, (1980, 1, 1, 0, 0, 0))
            item.compress_type, item.external_attr = zipfile.ZIP_STORED, 0o100644 << 16
            zout.writestr(item, blob)

elf = open('/bin/true', 'rb').read()                       # a real ELF executable of this machine
rewrite('addon.avrgame', extra=[('node_modules/avr-fixture-dep/build/Release/addon.node', b'\x00')])
rewrite('elf.avrgame', extra=[('node_modules/avr-fixture-dep/helper.js', elf)])
rewrite('js.avrgame', lambda m: m['server'].update(args=['server/main.js']), rename={'server/main.mjs': 'server/main.js'})
rewrite('eval.avrgame', lambda m: m['server'].update(args=['--eval', 'process.exit(0)']))
rewrite('link.avrgame')
with zipfile.ZipFile(f'{out}/link.avrgame', 'a') as z:     # a symbolic link among the dependencies
    link = zipfile.ZipInfo('node_modules/alias', (1980, 1, 1, 0, 0, 0))
    link.external_attr = 0o120777 << 16
    z.writestr(link, b'avr-fixture-dep')
PY
chmod 0644 "$build"/*.avrgame

# ---- e. WITHOUT the runtime: the Node package is refused, clearly, and nothing changes ---------------------
host_before=$(host_state)
capture inst install "$build/a.avrgame" --grant party_roster
show 'install without the runtime' "$out"
refused 'without the Node runtime, install-game refuses the Node package' 'which this appliance does not have'
check 'and the refusal names the missing binary and the tool that installs it' 0 \
    "$([[ $out == *"$nodebin is missing"* && $out == *'install-node-runtime'* ]] && echo 0 || echo 1)"
capture inst install "$build/a.avrgame" --grant party_roster --dry-run
refused 'a dry run says the same' 'which this appliance does not have'
t 'the refusal left the host exactly as it was' 0 test "$(host_state)" = "$host_before"
t 'and nothing of the game exists on the host' 0 test -z "$(nothing_of_game)"

# ---- f. the runtime: verified against the pin, installed offline, nothing but the binary -----------------------
install -m 0644 "$tarball" "$work/node.tar.xz"
cp "$work/node.tar.xz" "$work/tampered.tar.xz"
printf 'x' >> "$work/tampered.tar.xz"
capture noderuntime verify
check 'install-node-runtime verify says the runtime is not installed (exit 1)' 0 "$([[ $rc == 1 && $out == *'not installed'* ]] && echo 0 || echo 1)"
capture noderuntime install "$work/tampered.tar.xz"
refused 'a tarball whose SHA-256 is not the pinned one is refused' 'not the one pinned'
capture runuser -u nobody -- "$tree/ops/install-node-runtime" install "$work/node.tar.xz"
refused 'an install by a non-root user is refused' 'must run as root'
t 'neither left anything under /opt' nonzero test -e "$runtimes"
capture noderuntime install "$work/node.tar.xz" --dry-run
check 'install --dry-run exits 0, says what it would do and changes nothing' 0 \
    "$([[ $rc == 0 && $out == *'would install'* && ! -e $runtimes ]] && echo 0 || echo 1)"
# Offline: a new network namespace has no interface but a loopback that is down. The install must not need more.
capture unshare -n -- "$tree/ops/install-node-runtime" install "$work/node.tar.xz"
show 'install-node-runtime (in an empty network namespace)' "$out"
check 'install-node-runtime installs the pinned build with no network at all' 0 "$rc"
t 'the runtime is exactly bin/node, LICENSE and its record: no npm, npx, corepack, headers or link' 0 \
    test "$(cd "$noderoot" && find . -mindepth 1 | sort | paste -sd' ')" = './LICENSE ./avrana-runtime.json ./bin ./bin/node'
t 'the runtime tree is root-owned, nothing in it is group or world writable, and it holds no link' 0 \
    test -z "$(find "$runtimes" \( -not -user root -o -perm /022 -o -type l \) -print -quit)"
t 'bin/node is 0755 and answers the pinned version' 0 \
    bash -c 'test "$(stat -c %a "$1")" = 755 && test "$(env -i "$1" --version)" = "v$2"' _ "$nodebin" "$nodeversion"
t 'install-node-runtime verify passes' 0 noderuntime verify
t 'there is no npm on this appliance path' nonzero bash -c 'ls "$1"/bin/npm "$1"/bin/npx "$1"/lib 2>/dev/null | grep -q .' _ "$noderoot"
before=$(find "$runtimes" -printf '%p %T@ %i\n' | sort | sha256sum)
capture noderuntime install "$work/node.tar.xz"
check 'a second install changes nothing and says so' 0 \
    "$([[ $rc == 0 && $out == *'already installed'* && $(find "$runtimes" -printf '%p %T@ %i\n' | sort | sha256sum) == "$before" ]] && echo 0 || echo 1)"
t 'Party Core was not touched by any of it' 0 test "$(pid)" = "$pid_before" -a "$(entered "$party")" = "$since_before"

# ---- g. refusals of a Node package, each leaving the host as it was ---------------------------------------------
capture inst install "$build/addon.avrgame" --grant party_roster
refused 'a package with a native addon (.node) is refused' 'compiled code'
capture inst install "$build/elf.avrgame" --grant party_roster
refused 'a package with an ELF executable under a .js name is refused (by content)' 'compiled code'
capture inst install "$build/js.avrgame" --grant party_roster
refused 'a package whose entry is a .js file is refused' '.mjs'
capture inst install "$build/eval.avrgame" --grant party_roster
refused 'a package whose first argument is an option of Node (--eval) is refused' 'never an option of Node'
capture inst install "$build/link.avrgame" --grant party_roster
refused 'a package with a symbolic link among its dependencies is refused' 'package refused'
capture inst_nobody install "$build/a.avrgame" --grant party_roster
refused 'an install by a non-root user is refused' 'must run as root'
t 'none of those left anything behind' 0 test "$(host_state)" = "$host_before"
t 'and no failed run left a staging directory in the games root' 0 test -z "$(find "$groot" -mindepth 1 -print -quit)"

# ---- h. install ------------------------------------------------------------------------------------------------------
capture inst install "$build/a.avrgame" --grant party_roster --dry-run
show 'dry run' "$out"
check 'install --dry-run exits 0 and changes nothing' 0 "$([[ $rc == 0 && $out == *'would install 0.1.0'* && $(host_state) == "$host_before" ]] && echo 0 || echo 1)"
capture inst install "$build/a.avrgame" --grant party_roster
show 'install' "$out"
check 'install-game install exits 0 for the Node package' 0 "$rc"
staged=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root"])' "$record")
check 'the staged tree is /opt/avrana-games/<id>/<version>-<first 12 hex of the archive sha256>' 0 \
    "$([[ $staged == "$groot/$id/0.1.0-$sha12" ]] && echo 0 || echo 1)"
t 'the staged tree holds the entry and the vendored dependency' 0 \
    test -f "$staged/server/main.mjs" -a -f "$staged/node_modules/avr-fixture-dep/index.js" -a -f "$staged/avrgame.json"
t 'the staged tree is root-owned, nothing in it is group or world writable or executable, and it holds no link' 0 \
    test -z "$(find "$groot" \( -not -user root -o -perm /022 -o -type l -o \( -type f -perm /111 \) \) -print -quit)"
t 'install-game verify: every staged file matches the record' 0 inst verify "$id"
t 'the exec drop-in runs the pinned node BY ABSOLUTE PATH on the package entry, from the staged tree' 0 \
    bash -c 'grep -qxF "ExecStart=\"$3\" \"server/main.mjs\"" "$1/exec.conf" && grep -qxF "WorkingDirectory=$2" "$1/exec.conf"' _ "$dropin_dir" "$staged" "$nodebin"
t 'the drop-in carries MemoryMax=256M, TasksMax=64 and the confinement of every package' 0 \
    bash -c 'for l in MemoryMax=256M TasksMax=64 CPUQuota=100% CapabilityBoundingSet= PrivateNetwork=yes ProtectProc=invisible RestrictNamespaces=yes; do grep -qxF "$l" "$1/exec.conf" || { echo "missing $l"; exit 1; }; done' _ "$dropin_dir"
t 'no install script of the vendored package.json ran (preinstall, install, postinstall would each leave a mark)' 0 test -z "$(marks)"
t 'the vendored package.json really declares them (the check above is not vacuous)' 0 \
    grep -q '"postinstall"' "$staged/node_modules/avr-fixture-dep/package.json"
t 'the socket unit is enabled and active; the game is socket-activated (service not yet running)' 0 \
    bash -c 'systemctl is-enabled --quiet "$1" && systemctl is-active --quiet "$1" && ! systemctl is-active --quiet "$2"' _ "$gsock" "$game"
t 'install-game reloaded Party Core and did not restart it' 0 test "$(pid)" = "$pid_before" -a "$(entered "$party")" = "$since_before"
run_driver 'Party Core (reloaded) now offers the game, known only through its install record' --offered
t 'the effective catalog lists the Node package like any other' 0 \
    python3 -c 'import json,sys; g={x["id"]:x for x in json.load(open(sys.argv[1]))["games"]}; h=g[sys.argv[2]]; assert h["installed"] is True and h["entry"]=="/games/"+sys.argv[2]+"/" and h["provider"]=="native", h' "$overlay" "$id"

# ---- i. session 1, then the running unit ------------------------------------------------------------------------------
run_driver 'session 1: two players and a watcher, private secret words, hello over the game API, reconnect, result accepted, home'
t 'the game (socket-activated) is running' 0 systemctl is-active --quiet "$game"
gpid=$(prop MainPID)
t 'the game process IS the pinned node (/proc/<pid>/exe)' 0 test "$(readlink -f "/proc/$gpid/exe")" = "$nodebin"
t 'its command line is node and the entry, nothing else' 0 \
    test "$(tr '\0' ' ' < "/proc/$gpid/cmdline")" = "$nodebin server/main.mjs "
t 'it runs from the STAGED package tree (/proc/<pid>/cwd)' 0 test "$(readlink -f "/proc/$gpid/cwd")" = "$(readlink -f "$staged")"
t 'it runs as a systemd DynamicUser and not as root' 0 \
    bash -c 'test "$(systemctl show -p DynamicUser --value "$1")" = yes && test "$(ps -o uid= -p "$2" | tr -d " ")" != 0' _ "$game" "$gpid"
echo "OBSERVE     the game runs as user $(ps -o user= -p "$gpid" | tr -d ' ')"
# The sandbox, as systemd applies it to the running unit. The same properties a Python package unit has.
for want in DynamicUser=yes ProtectSystem=strict ProtectHome=yes PrivateTmp=yes PrivateDevices=yes NoNewPrivileges=yes \
    PrivateNetwork=yes RestrictNamespaces=yes LockPersonality=yes RestrictRealtime=yes ProtectProc=invisible \
    ProtectKernelTunables=yes ProtectKernelModules=yes ProtectControlGroups=yes ProtectClock=yes ProtectHostname=yes \
    RestrictAddressFamilies=AF_UNIX CapabilityBoundingSet= UMask=0077 Restart=on-failure; do
    got=$(prop "${want%%=*}")
    check "systemctl show: ${want%%=*} is '${want#*=}'" 0 "$([[ $got == "${want#*=}" ]] && echo 0 || echo 1)"
done
t 'systemd applies MemoryMax=256M, TasksMax=64 and CPUQuota=100% to the Node unit' 0 \
    bash -c 'test "$(systemctl show -p MemoryMax --value "$1")" = 268435456 && test "$(systemctl show -p TasksMax --value "$1")" = 64 && test "$(systemctl show -p CPUQuotaPerSecUSec --value "$1")" = 1s' _ "$game"
cg=/sys/fs/cgroup/system.slice/system-avrana\\x2dgame.slice/$game
[[ -d $cg ]] || cg=$(find /sys/fs/cgroup -type d -name "$game" -print -quit)
t 'and the kernel holds them: memory.max is 268435456 and pids.max is 64 in the unit cgroup' 0 \
    bash -c 'test "$(cat "$1/memory.max")" = 268435456 && test "$(cat "$1/pids.max")" = 64' _ "$cg"
t 'the process has no capability at all (CapBnd and CapEff are zero)' 0 \
    bash -c '! grep -E "^Cap(Bnd|Eff):" "/proc/$1/status" | grep -qv "0000000000000000$"' _ "$gpid"
t 'the process is in its own network namespace' 0 test "$(readlink "/proc/$gpid/ns/net")" != "$(readlink /proc/1/ns/net)"
t 'which has no address beyond loopback and no route at all: there is no way out' 0 \
    bash -c 'test -z "$(nsenter -t "$1" -n ip -o addr show scope global)" && test -z "$(nsenter -t "$1" -n ip route show)" && test -z "$(nsenter -t "$1" -n ip -6 route show default)"' _ "$gpid"
t 'persistent_storage was not granted: the unit has NO state directory' 0 bash -c 'test -z "$(systemctl show -p StateDirectory --value "$1")"' _ "$game"
# V8 and the sandbox. The template and the package drop-in set neither MemoryDenyWriteExecute= nor a
# SystemCallFilter=, so nothing is relaxed for Node: the JIT maps executable memory under the same
# unit a Python package gets. The fixture proves it at start: it compiles and calls a WebAssembly
# function (V8 has no WebAssembly interpreter) and logs the outcome.
echo "OBSERVE     MemoryDenyWriteExecute on the unit: $(prop MemoryDenyWriteExecute); SystemCallFilter: '$(prop SystemCallFilter)'"
t 'MemoryDenyWriteExecute is not set on package units, for Python or for Node (nothing is relaxed for V8)' 0 test "$(prop MemoryDenyWriteExecute)" = no
journalctl --sync >/dev/null 2>&1 || true
start_line=$(journalctl -u "$game" --no-pager -o cat 2>/dev/null | grep -F 'serving /games/' | tail -n1 || true)
echo "OBSERVE     the fixture at start: $start_line"
t 'V8 compiled and ran machine code inside the sandbox (the fixture logs: jit ok)' 0 grep -qF 'jit ok' <<<"$start_line"
t 'the process runs the pinned version with no extra option of Node' 0 grep -qF "node v$nodeversion" <<<"$start_line"
t 'the game received the signed launch (journal)' 0 journal_has "$game" 'launched ('
t 'the game reported its signed ended and the party accepted the result (journal)' 0 journal_has "$game" 'the party accepted the result'
t 'no install script ran at any point' 0 test -z "$(marks)"

# The numbers. The session is over and reported; the process is idle (it stops itself after 60 s).
sleep 3
echo "MEASURE     idle Node fixture ($(uname -m), node v$nodeversion): RSS $(awk '/^VmRSS:/ {print $2 " " $3}' "/proc/$gpid/status"), \
high-water RSS $(awk '/^VmHWM:/ {print $2 " " $3}' "/proc/$gpid/status"), threads $(awk '/^Threads:/ {print $2}' "/proc/$gpid/status")"
echo "MEASURE     its unit cgroup: MemoryCurrent $(prop MemoryCurrent) bytes, MemoryPeak $(prop MemoryPeak) bytes of MemoryMax $(prop MemoryMax); \
TasksCurrent $(prop TasksCurrent) of TasksMax $(prop TasksMax)"
t 'the idle fixture is far inside its ceilings (under half of MemoryMax and of TasksMax)' 0 \
    bash -c 'test "$(systemctl show -p MemoryCurrent --value "$1")" -lt 134217728 && test "$(systemctl show -p TasksCurrent --value "$1")" -lt 32' _ "$game"

# No network egress: a transient unit with the confinement of a package unit, running the same binary.
cat > "$work/egress.mjs" <<'JS'
import dns from 'node:dns';
import net from 'node:net';

const tcp = (host, port) => new Promise((resolve) => {
  const s = net.connect({ host, port, timeout: 3000 });
  s.on('connect', () => { s.destroy(); resolve('connected'); });
  s.on('timeout', () => { s.destroy(); resolve('refused-timeout'); });
  s.on('error', (e) => resolve(`refused-${e.code}`));
});
const unix = (path) => new Promise((resolve) => {
  const s = net.connect({ path });
  s.on('connect', () => { s.destroy(); resolve('connected'); });
  s.on('error', (e) => resolve(`refused-${e.code}`));
});
console.log('tcp-party-loopback', await tcp('127.0.0.1', 8191));
console.log('tcp-internet', await tcp('1.1.1.1', 443));
console.log('tcp6-internet', await tcp('2606:4700:4700::1111', 443));
console.log('dns', await new Promise((resolve) => dns.lookup('nodejs.org', (e) => resolve(e ? `failed-${e.code}` : 'resolved'))));
console.log('unix-party-internal', await unix('/run/avrana-party/internal.sock'));
console.log('unix-game-socket', await unix(process.argv[2]));
JS
chmod 0644 "$work/egress.mjs"
t 'Party Core does listen on 127.0.0.1:8191 on the host (so a refusal below is not vacuous)' 0 party_status
set +e
systemd-run --quiet --wait --pipe --collect -p DynamicUser=yes -p SupplementaryGroups=avrana-games \
    -p RestrictAddressFamilies=AF_UNIX -p PrivateNetwork=yes -p CapabilityBoundingSet= -p MemoryMax=256M -p TasksMax=64 \
    "$nodebin" "$work/egress.mjs" "$sock" > "$work/egress.out" 2>&1
probe_rc=$?
set -e
show 'node with the confinement of a package unit' "$(cat "$work/egress.out")"
check 'the probe ran' 0 "$probe_rc"
t 'node cannot reach Party Core on loopback TCP' 0 grep -qE '^tcp-party-loopback refused-' "$work/egress.out"
t 'node cannot reach an IPv4 address' 0 grep -qE '^tcp-internet refused-' "$work/egress.out"
t 'node cannot reach an IPv6 address' 0 grep -qE '^tcp6-internet refused-' "$work/egress.out"
t 'it CAN connect to Party Core internal Unix socket, as every native game (the refusals are not vacuous)' 0 \
    grep -qx 'unix-party-internal connected' "$work/egress.out"
t 'and it cannot connect to a game socket (root:avrana-front 0660): other games stay unreachable' 0 \
    grep -qE '^unix-game-socket refused-' "$work/egress.out"

# --jitless, measured beside the default (outside the unit, as an unprivileged user; one run each).
cat > "$work/bench.mjs" <<'JS'
const start = process.hrtime.bigint();
let x = 0;
for (let i = 0; i < 30_000_000; i += 1) x = (x + i * i) % 1000003;
const ms = Number(process.hrtime.bigint() - start) / 1e6;
console.log(`loop ${ms.toFixed(0)} ms, rss ${(process.memoryUsage().rss / 1024).toFixed(0)} kB, WebAssembly ${typeof WebAssembly}, x ${x}`);
JS
chmod 0644 "$work/bench.mjs"
echo "MEASURE     default (JIT):   $(runuser -u nobody -- env -i "$nodebin" "$work/bench.mjs" 2>&1 | tail -n1)"
echo "MEASURE     --jitless:       $(runuser -u nobody -- env -i "$nodebin" --jitless "$work/bench.mjs" 2>&1 | tail -n1)"

# ---- j. session 2: removal refused during a live session; the Host ends it -------------------------------------------------
run_driver 'session 2: remove is refused during the live session, then the Host ends it from Party' --end --cwd "$tree" \
    --during-live python3 -m avrana.ops.install_game remove "$id"
t 'the package is still fully installed after the refused removal' 0 bash -c 'test -f "$1" && test -d "$2" && test -f "$3"' _ "$record" "$staged" "$entry"
t 'the game saw the end the Party sent (journal: ended by the party)' 0 journal_has "$game" 'ended by the party'
gone=1
for _ in $(seq 1 100); do
    if ! systemctl is-active --quiet "$game"; then gone=0; break; fi
    sleep 1
done
check 'the Node process holds no session: it exited on its own (idle stop) after the end; the socket stays' 0 "$gone"
t 'it stopped cleanly: the unit is not failed (exit status 0)' 0 \
    bash -c 'test "$(systemctl show -p Result --value "$1")" = success && test "$(systemctl show -p ExecMainStatus --value "$1")" = 0' _ "$game"

# ---- k. remove: the package, then the runtime ------------------------------------------------------------------------------------
capture noderuntime remove
refused 'install-node-runtime remove is refused while a package runs on the runtime' 'installed packages run on this runtime'
t 'and the runtime is still there and verifies' 0 noderuntime verify
sleep 7                                   # longer than Party Core's status cache
capture inst remove "$id"
show 'remove' "$out"
check 'install-game remove exits 0' 0 "$rc"
t 'nothing of the game is left (record, staged tree, key, registry entry, drop-in, socket, state)' 0 test -z "$(nothing_of_game)"
t 'the socket unit is neither enabled nor active, the service is not active' nonzero \
    bash -c 'systemctl is-enabled --quiet "$1" || systemctl is-active --quiet "$1" || systemctl is-active --quiet "$2"' _ "$gsock" "$game"
run_driver 'Party Core no longer offers the game' --absent
t 'the effective catalog is gone with the package' nonzero test -e "$overlay"
capture inst remove "$id"
check 'a second remove is a clean no-op' 0 "$([[ $rc == 0 && $out == *'nothing to remove'* ]] && echo 0 || echo 1)"
capture inst install "$build/a.avrgame" --grant party_roster
check 're-installing the Node package after a removal works' 0 "$rc"
capture inst remove "$id"
check 'and removing it again works' 0 "$rc"
t 'nothing of the game is left again' 0 test -z "$(nothing_of_game)"
capture noderuntime remove --dry-run
check 'install-node-runtime remove --dry-run removes nothing' 0 "$([[ $rc == 0 && $out == *'would remove'* && -x $nodebin ]] && echo 0 || echo 1)"
capture noderuntime remove
show 'remove the runtime' "$out"
check 'with no package on it, install-node-runtime remove exits 0' 0 "$rc"
t 'nothing of the runtime is left (/opt/avrana-runtimes is gone)' nonzero test -e "$runtimes"
capture inst install "$build/a.avrgame" --grant party_roster
refused 'and the Node package is refused again, as before the runtime was installed' 'which this appliance does not have'
t 'Party Core was never restarted in the whole run' 0 test "$(pid)" = "$pid_before" -a "$(entered "$party")" = "$since_before"
t 'no install script ran in the whole run' 0 test -z "$(marks)"

# ---- l. summary ---------------------------------------------------------------------------------------------------------------
echo "failed checks: $fails"
[[ $fails == 0 ]]
