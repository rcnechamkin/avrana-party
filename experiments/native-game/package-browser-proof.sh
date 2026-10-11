#!/usr/bin/env bash
# Non-production proof for AVR-338 (EXPERIMENTAL .avrgame packages): the INSTALLED Hello Party package,
# driven by REAL BROWSERS (Playwright) through the intended Party experience. Linux + systemd + root
# only; run it in CI or on a disposable Linux machine. NEVER on the Pi (AGENTS.md).
#
#   sudo env "PATH=$PATH" AVRANA_PACKAGE_BROWSER_PROOF=1 AVRANA_GAMES_REPO=/path/to/avrana-party-games \
#        bash experiments/native-game/package-browser-proof.sh
#
# package-proof.sh (AVR-39) proves the install with HTTP clients standing in for phones. This script
# keeps its disposable appliance and replaces the clients with browsers. What is REAL here:
#   - the package: built unprivileged from the committed recipe, installed by the REAL `install-game`
#     through the REAL `provision-game` path, removed by the REAL `install-game remove`;
#   - Party Core (the real unit, socket-activated), the game (avrana-game@hello, socket-activated,
#     DynamicUser, running from the staged tree), the signed launch and the signed result;
#   - nginx: the COMMITTED avrana-party.nginx, byte for byte (cmp'd), on its real ports 80 and 443,
#     with the real host names party.avrana.net and games.avrana.net, the real native-game rule that
#     proxies to /run/avrana-games/hello.sock, and the real built web shell (avrana.web.build);
#   - the browsers: Playwright's Chromium (and WebKit when AVRANA_BROWSER_WEBKIT=1), one browser context
#     per phone, the Party's real HTTPS-only `Secure` cookie.
# What is SUBSTITUTED (each lowers the evidence tier):
#   - TLS: a throwaway self-signed certificate for the two names, in the place the appliance keeps its
#     certificate (/etc/avrana-party/tls/current/); the browsers ignore the certificate error;
#   - DNS: one line in /etc/hosts sends both names to 127.0.0.1 (removed on exit);
#   - DISCOVERY IS HARNESS-ASSISTED (see serve_catalog below): the shell reads a static catalog.json,
#     and nothing on this branch makes the appliance regenerate it from the installed packages
#     (AVR-337 builds that). This script generates it with the existing
#     `python -m avrana.contracts.catalog --packages` and writes it into the web root;
#   - the web shell's service worker is blocked in the browsers (as in the other Playwright suites);
#   - the host is a CI runner: not a phone, not Wi-Fi, not the Pi.
#
# It CREATES (and removes again on exit, whatever happened) what package-proof.sh does, plus
# /var/www/avrana-party, /etc/avrana-party/tls, one /etc/hosts line and an nginx on ports 80 and 443.
# The Playwright steps run as AVRANA_BROWSER_USER (default: the user who ran sudo) from the checkout.
# Output: one line per check (CHECK PASS/FAIL), then the Playwright list reporter.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

[[ ${AVRANA_PACKAGE_BROWSER_PROOF:-} == 1 ]] || { echo 'set AVRANA_PACKAGE_BROWSER_PROOF=1 (CI or a disposable machine only; never the Pi)' >&2; exit 2; }
[[ $(id -u) == 0 ]] || { echo 'run as root (sudo)' >&2; exit 2; }
command -v systemctl >/dev/null && [[ -d /run/systemd/system ]] || { echo 'systemd is not running here' >&2; exit 2; }
for c in curl runuser openssl npx; do command -v "$c" >/dev/null || { echo "$c not found (sudo env \"PATH=\$PATH\" keeps node's)" >&2; exit 2; }; done
getent passwd nobody >/dev/null || { echo 'the user nobody does not exist' >&2; exit 2; }
games_repo=${AVRANA_GAMES_REPO:-}
[[ -n $games_repo && -f $games_repo/hello_party/avrgame.build.json && -f $games_repo/hello_party/avrgame.json \
    && -f $games_repo/core/party_protocol.py && -f $games_repo/web/avrana-party-bridge.js \
    && -f $games_repo/avrana_gamekit/__init__.py ]] \
    || { echo 'set AVRANA_GAMES_REPO to a checkout of avrana-party-games with hello_party/avrgame.build.json' >&2; exit 2; }
games_repo=$(cd "$games_repo" && pwd)
pwuser=${AVRANA_BROWSER_USER:-${SUDO_USER:-}}
[[ -n $pwuser && $pwuser != root ]] || { echo 'set AVRANA_BROWSER_USER (the unprivileged user that owns node_modules and the browsers)' >&2; exit 2; }
pwhome=$(getent passwd "$pwuser" | cut -d: -f6)
NGINX=$(command -v nginx || true)
if [[ -z $NGINX ]]; then
    apt-get install -y nginx-light >/dev/null 2>&1 || apt-get install -y nginx >/dev/null
    systemctl stop nginx 2>/dev/null || true
    NGINX=$(command -v nginx)
fi

repo=$(cd "$(dirname "$0")/../.." && pwd)
[[ -d $repo/node_modules/@playwright ]] || { echo "run npm ci in $repo first" >&2; exit 2; }
work=/run/avrana-package-browser
marker=/run/avrana-package-browser.marker
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
tls=/etc/avrana-party/tls/current
web=/var/www/avrana-party/web/current
sock=/run/avrana-games/hello.sock
dropin_dir=$unit_dir/avrana-game@hello.service.d
party=avrana-party-core.service
psock=avrana-party-core.socket
game=avrana-game@hello.service
gsock=avrana-game@hello.socket
out_dir=${AVRANA_BROWSER_OUT:-$repo/test-results/package-browser}
fails=0
hosts_tag='# avrana-package-browser-proof'

# ---- refuse to touch anything that is not ours -----------------------------------------------------
if [[ ! -e $marker ]]; then
    for p in /etc/avrana-party /opt/avrana-party /opt/avrana-party-games /opt/avrana-games /var/backups/avrana-party \
        /var/lib/avrana-party-core /var/lib/avrana-games /var/www/avrana-party; do
        [[ ! -e $p ]] || { echo "refusing: $p exists and this script did not create it" >&2; exit 2; }
    done
    for n in avrana-party avrana-front avrana-games; do
        ! getent passwd "$n" >/dev/null && ! getent group "$n" >/dev/null \
            || { echo "refusing: the user or group $n exists and this script did not create it" >&2; exit 2; }
    done
    for port in 80 443; do
        ! (exec 3<>/dev/tcp/127.0.0.1/$port) 2>/dev/null || { echo "refusing: something already listens on port $port" >&2; exit 2; }
    done
fi

cleanup() {
    set +e
    [[ -s "$marker.opt-mode" ]] && chmod "$(cat "$marker.opt-mode")" /opt && rm -f "$marker.opt-mode"
    if [[ -s $work/nginx.pid ]]; then kill "$(cat "$work/nginx.pid")" 2>/dev/null; sleep 1; fi
    sed -i "/$hosts_tag\$/d" /etc/hosts
    systemctl stop "$gsock" "$psock" 2>/dev/null
    systemctl stop "$game" "$party" 2>/dev/null
    systemctl disable "$gsock" "$psock" 2>/dev/null
    rm -f "$unit_dir"/sockets.target.wants/"$gsock" "$unit_dir"/sockets.target.wants/"$psock"
    rm -rf "$unit_dir"/avrana-game@.socket "$unit_dir"/avrana-game@.service "$dropin_dir" \
        "$unit_dir/$party" "$unit_dir/$psock"
    rm -rf /etc/avrana-party /opt/avrana-party /opt/avrana-party-games /opt/avrana-games /var/backups/avrana-party \
        /var/lib/avrana-party-core /var/lib/private/avrana-party-core /var/lib/avrana-games \
        /var/lib/private/avrana-games /run/avrana-games /run/avrana-party /run/avrana-install-game.lock \
        /var/www/avrana-party "$work"
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
    for p in /etc/avrana-party /opt/avrana-party /opt/avrana-party-games /opt/avrana-games /var/backups/avrana-party \
        /run/avrana-games /run/avrana-party "$work" /var/lib/avrana-games /var/lib/private/avrana-games /var/www/avrana-party \
        "$unit_dir/$party" "$unit_dir/$psock" "$unit_dir/avrana-game@.socket" "$unit_dir/avrana-game@.service" "$dropin_dir"; do
        [[ ! -e $p ]] || echo "$p"
    done
    if grep -q "$hosts_tag" /etc/hosts; then echo '/etc/hosts-line'; fi
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
        echo '--- nginx error log ---'
        tail -n 40 "$work/error.log" 2>/dev/null
        echo '--- end ---'
    fi
    cleanup
    local left
    left=$(leftovers | paste -sd' ')
    if [[ -z $left ]]; then echo 'CHECK PASS  the cleanup restored the host: no user, group, directory, unit, hosts line or nginx of this proof is left'
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
t() { local name=$1 want=$2; shift 2; set +e; "$@" >/dev/null 2>&1; local s=$?; set -e; check "$name" "$want" "$s"; }
capture() { set +e; out=$("$@" 2>&1); rc=$?; set -e; }      # sets $out and $rc
show() { local line; while IFS= read -r line; do echo "OBSERVE     $1: $line"; done <<<"$2"; }
inst() { (cd "$tree" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.install_game "$@"); }
packer() { (cd "$work" && runuser -u nobody -- env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$work/tool" python3 -m avrana.avrgame "$@"); }
prep() { "$tree/ops/prepare-native-games" "$@"; }
party_status() { curl -fsS --max-time 10 -H 'Host: party.avrana.net' http://127.0.0.1:8191/party/api/status; }
pid() { systemctl show -p ExecMainPID --value "$party"; }
wait_ready() {
    ready=1
    for _ in $(seq 1 60); do
        if systemctl is-active --quiet "$party" && party_status >/dev/null 2>&1; then ready=0; break; fi
        sleep 0.5
    done
}

# ---- DISCOVERY, HARNESS-ASSISTED -------------------------------------------------------------------------
# THE ONE PLACE TO SWAP (AVR-337): the shell's Party Home reads a static catalog.json from the web root.
# On an appliance nothing regenerates it from the installed packages yet, so this harness does, with the
# existing generator (`--packages` lists the games installed as .avrgame packages) over the real appliance
# profile and the release tree's contracts, and writes the result where nginx serves it. When the
# appliance-local effective-catalog overlay (lane B, AVR-337) exists, replace the body of this function
# with the real mechanism (or delete the calls and let the appliance do it); nothing else here depends on
# how the catalog came to be, and the browser tests only read what nginx serves at /party/catalog.json.
serve_catalog() {
    local games="$work/cat-games"
    if [[ ! -d $games ]]; then
        mkdir "$games"
        cp "$tree"/contracts/games/*.json "$games/"          # the release tree: NO contract for hello
    fi
    ( cd "$repo" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.contracts.catalog --games "$games" \
        --appliance "$appliance" --packages "$packages" --out "$web/catalog.json" )
    chmod 0644 "$web/catalog.json"
}

# ---- a. the release tree: root-owned, WITHOUT the contract of the game -------------------------------------
opt_mode=$(stat -c %a /opt); echo "$opt_mode" > "$marker.opt-mode"
chmod 0755 /opt
install -d -m 0755 /opt/avrana-party /opt/avrana-party/releases "$rel" "$rel/deploy" "$rel/deploy/party-core" "$rel/ops"
cp -r "$repo/avrana" "$repo/contracts" "$rel/"
cp -r "$repo/deploy/games" "$rel/deploy/games"
install -m 0644 "$repo/deploy/party-core/avrana-party-core.service" "$repo/deploy/party-core/avrana-party-core.socket" "$rel/deploy/party-core/"
install -m 0755 "$repo/ops/provision-game" "$rel/ops/provision-game"
install -m 0755 "$repo/ops/prepare-native-games" "$rel/ops/prepare-native-games"
install -m 0755 "$repo/ops/install-game" "$rel/ops/install-game"
rm -f "$rel/contracts/games/hello.json"
find "$rel" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R root:root /opt/avrana-party
chmod -R u=rwX,go=rX /opt/avrana-party
ln -sfn "$rel" "$tree"
t 'the Party release tree has NO contract for the game (contracts/games/hello.json is absent)' nonzero test -e "$tree/contracts/games/hello.json"
install -d -m 0755 -o root -g root "$groot"
mkdir -m 0755 "$work"

# ---- b. identities (ADR 0016 phase 1) ---------------------------------------------------------------------------
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

# ---- c. Party Core on its EARLIER unit, then ops/prepare-native-games ---------------------------------------------
sed -e '/^ExecReload=/d' -e '/^Wants=avrana-party-core\.socket$/d' \
    -e 's/^After=network\.target avrana-party-core\.socket$/After=network.target/' \
    "$repo/deploy/party-core/avrana-party-core.service" > "$work/earlier.service"
install -m 0644 "$work/earlier.service" "$unit_dir/$party"
systemctl daemon-reload
# The appliance's names and origins, HTTPS and the Secure cookie (the default) as production; the game
# origin is the registered second origin (ADR 0013, docs/runbooks/game-origin.md).
cat > "$conf" <<'JSON'
{
  "hosts": ["party.avrana.net"],
  "origins": ["https://party.avrana.net"],
  "game_origins": {"https://games.avrana.net": "*"},
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
t 'prepare-native-games kept the game_origins and packages keys of party-core.json' 0 \
    python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); assert c["game_origins"]=={"https://games.avrana.net":"*"} and c["packages"]=="/etc/avrana-party/packages.d", c' "$conf"
wait_ready
t 'Party Core was restarted onto the socket, is active and answers on loopback' 0 test "$ready" = 0
pid_before=$(pid)

# ---- d. build, UNPRIVILEGED, from the committed recipe; install ----------------------------------------------------
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
capture packer pack "$src/hello_party/avrgame.build.json" --out "$build/a.avrgame"
show 'pack (nobody)' "$out"
check 'the package builds from the committed recipe as an unprivileged user' 0 "$rc"
capture inst install "$build/a.avrgame" --grant party_roster
show 'install' "$out"
check 'install-game install exits 0' 0 "$rc"
staged=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root"])' "$record")
t 'the staged tree exists and holds the game and the bridge shim' 0 \
    test -f "$staged/hello_party/__main__.py" -a -f "$staged/web/avrana-party-bridge.js" -a -f "$staged/hello_party/web/index.html"
t 'install-game verify: every staged file matches the record' 0 inst verify hello

# ---- e. the front door: the web shell, a certificate, two names, the COMMITTED nginx site --------------------------------
install -d -m 0755 -o root -g root /var/www/avrana-party /var/www/avrana-party/web
( cd "$repo" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.web.build --out "$web" --build ci )
serve_catalog
t 'the served catalog lists the package, installed, at /games/hello/, native' 0 \
    python3 -c 'import json,sys; g={x["id"]:x for x in json.load(open(sys.argv[1]))["games"]}; h=g["hello"]; assert h["installed"] is True and h["entry"]=="/games/hello/" and h["provider"]=="native" and h["playableHere"] is True, h' "$web/catalog.json"
install -d -m 0755 "$tls"
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 1 -subj '/CN=party.avrana.net' \
    -addext 'subjectAltName=DNS:party.avrana.net,DNS:games.avrana.net' \
    -keyout "$tls/privkey.pem" -out "$tls/fullchain.pem" >/dev/null 2>&1
chmod 0600 "$tls/privkey.pem"
printf '127.0.0.1 party.avrana.net games.avrana.net %s\n' "$hosts_tag" >> /etc/hosts
cp "$repo/avrana-party.nginx" "$work/site.conf"
t 'the nginx site in use is the committed avrana-party.nginx, byte for byte' 0 cmp -s "$work/site.conf" "$repo/avrana-party.nginx"
mime=/etc/nginx/mime.types
[[ -f $mime ]] || { echo "$mime not found" >&2; exit 2; }
for d in body proxy fastcgi uwsgi scgi; do mkdir "$work/tmp-$d"; done
cat > "$work/nginx.conf" <<CONF
user www-data;
pid $work/nginx.pid;
error_log $work/error.log;
events {}
http {
  include $mime;
  default_type application/octet-stream;
  access_log $work/access.log;
  client_body_temp_path $work/tmp-body; proxy_temp_path $work/tmp-proxy; fastcgi_temp_path $work/tmp-fastcgi;
  uwsgi_temp_path $work/tmp-uwsgi; scgi_temp_path $work/tmp-scgi;
  include $work/site.conf;
}
CONF
t 'nginx accepts the committed site' 0 "$NGINX" -t -p "$work" -e "$work/error.log" -c "$work/nginx.conf"
"$NGINX" -p "$work" -e "$work/error.log" -c "$work/nginx.conf"
ready=1
for _ in $(seq 1 40); do
    if curl -fsSk --max-time 5 https://party.avrana.net/party/api/status >/dev/null 2>&1; then ready=0; break; fi
    sleep 0.5
done
t 'nginx serves Party Core over HTTPS on party.avrana.net (/party/api/status)' 0 test "$ready" = 0
t 'the game origin refuses the Party shell (games.avrana.net/party/ is nginx 404)' 0 \
    test "$(curl -sk -o /dev/null -w '%{http_code}' https://games.avrana.net/party/)" = 404
t 'the game rule never proxies a control path (games.avrana.net/games/hello/avrana/launch is nginx 404)' 0 \
    test "$(curl -sk -o /dev/null -w '%{http_code}' https://games.avrana.net/games/hello/avrana/launch)" = 404

# ---- f. the browsers: play the installed package --------------------------------------------------------------------
runuser -u "$pwuser" -- mkdir -p "$out_dir"      # created by the user who will write to it, parents included
pw() {  # pw <project> <spec>: Playwright as the unprivileged user, from the checkout
    (cd "$repo" && runuser -u "$pwuser" -- env HOME="$pwhome" PATH="$PATH" CI=1 AVRANA_PACKAGE_BROWSER_PROOF=1 \
        AVRANA_BROWSER_OUT="$out_dir/$1-${2%.spec.ts}" npx playwright test -c playwright.package.config.ts --project="$1" "$2")
}
observe_game() {  # while the browsers play: where the game process runs and as whom (it idles away afterwards)
    local gpid cwd
    for _ in $(seq 1 1200); do
        gpid=$(systemctl show -p MainPID --value "$game" 2>/dev/null || echo 0)
        if [[ ${gpid:-0} -gt 0 && -r /proc/$gpid/cwd ]]; then
            cwd=$(readlink -f "/proc/$gpid/cwd")
            echo "$cwd" > "$work/game.cwd"
            systemctl show -p DynamicUser --value "$game" > "$work/game.dyn"
            ps -o uid= -p "$gpid" | tr -d ' ' > "$work/game.uid"
            [[ $cwd == "$(readlink -f "$staged")" ]] && return 0      # the process has changed into its working directory
        fi
        sleep 0.1
    done
}
observe_game & observer=$!
set +e
pw chromium-pixel package-play.spec.ts
s_play=$?
s_webkit=0
if [[ ${AVRANA_BROWSER_WEBKIT:-} == 1 ]]; then
    pw webkit-iphone package-play.spec.ts
    s_webkit=$?
fi
set -e
kill "$observer" 2>/dev/null || true
check 'real Chromium (Pixel 7 size): admission, discovery, launch, private views, reconnect, result, home' 0 "$s_play"
if [[ ${AVRANA_BROWSER_WEBKIT:-} == 1 ]]; then check 'real WebKit (iPhone 13 size): the same' 0 "$s_webkit"; fi
for f in cwd dyn uid; do echo "OBSERVE     game process $f: $(cat "$work/game.$f" 2>&1)"; done
t 'the game process, seen while the browsers played, ran from the STAGED package tree as a DynamicUser, not root' 0 bash -c '
    test "$(cat "$1/game.cwd")" = "$(readlink -f "$2")" && test "$(cat "$1/game.dyn")" = yes && test "$(cat "$1/game.uid")" != 0' _ "$work" "$staged"
t 'the game saw the signed launch and the party accepted the result (journal)' 0 bash -c '
    journalctl --sync >/dev/null 2>&1 || true
    j=$(journalctl -u "$1" --no-pager); grep -qF "launched (" <<<"$j" && grep -qF "the party accepted the result" <<<"$j"' _ "$game"
t 'Party Core was not restarted by any of it' 0 test "$(pid)" = "$pid_before"

# ---- g. removal --------------------------------------------------------------------------------------------------------
sleep 7                                   # longer than Party Core's status cache: remove must not see the finished session as live
capture inst remove hello
show 'remove' "$out"
check 'install-game remove exits 0' 0 "$rc"
t 'nothing of the game is left (record, staged tree, key, registry entry, drop-in, socket)' 0 \
    bash -c 'for p in "$@"; do [[ -e $p || -L $p ]] && exit 1; done; exit 0' _ "$record" "$groot/hello" "$key" "$entry" "$dropin_dir" "$sock"
serve_catalog
t 'the served catalog no longer lists the game' 0 \
    python3 -c 'import json,sys; g={x["id"] for x in json.load(open(sys.argv[1]))["games"]}; assert "hello" not in g, g' "$web/catalog.json"
set +e
pw chromium-pixel package-removed.spec.ts
s_gone=$?
set -e
check 'real Chromium: after the removal the game is not in Party Home, not launchable, and its route is gone' 0 "$s_gone"
t 'Party Core was never restarted in the whole run' 0 test "$(pid)" = "$pid_before"

echo "failed checks: $fails"
[[ $fails == 0 ]]
