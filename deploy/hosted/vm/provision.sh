#!/usr/bin/env bash
# Prepare the hosted staging VM for its first ops/deploy.sh (docs/runbooks/hosted-staging.md, step 3).
# OWNER-RUN, inside the VM, with sudo, from the operator's Party checkout:
#
#   sudo bash ~/avrana-party/deploy/hosted/vm/provision.sh [--dry-run]
#
# Idempotent: run again, it changes nothing that is in place. It sets up what ops/deploy.sh and the
# appliance's units expect, with the same identities as the Pi (ADR 0016 phase 1):
#   - groups avrana-front and avrana-games; system user avrana-party; www-data in avrana-front;
#   - /etc/avrana-party (0755), its game-keys (0700 avrana-party), games.d and packages.d (0755 root),
#     /var/lib/avrana-party, /var/backups/avrana-party;
#   - /etc/avrana-party/party-core.json from deploy/hosted/party-core.hosted.json, only if absent (an
#     edited config is never replaced) and /etc/avrana-party/deploy-profile = "hosted";
#   - Party Core's units and the native-game templates from this checkout's deploy/;
#   - journald size caps (deploy/journald/avrana-journald.conf), the VM firewall (avrana-staging.nft);
#   - nginx: the distribution's default site disabled; deploy.sh installs and enables the Party site.
# It never creates, reads or prints a secret (game keys: provision-game; the tunnel credential: cloudflared),
# never installs cloudflared, and never starts Party Core (the first deploy does, from a code release).
set -Eeuo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH
checkout=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../.." && pwd)
dry=0
[[ ${1:-} == --dry-run ]] && dry=1
run() { echo "+ $*"; [[ $dry -eq 1 ]] || "$@"; }
[[ $EUID -eq 0 || $dry -eq 1 ]] || { echo 'run with sudo (or --dry-run)' >&2; exit 1; }
[[ -f $checkout/deploy/hosted/party-core.hosted.json ]] || { echo "$checkout is not an avrana-party checkout with deploy/hosted" >&2; exit 1; }
if [[ -e /etc/avrana-party/deploy-profile && $(tr -d '[:space:]' < /etc/avrana-party/deploy-profile) != hosted ]]; then
    echo 'this machine declares another deploy profile; refusing' >&2; exit 1
fi
if systemctl list-unit-files 2>/dev/null | grep -qE '^(hostapd|avranaparty-arcade)\.service'; then
    echo 'this looks like an appliance (hostapd or the arcade unit is installed); refusing' >&2; exit 1
fi

for pkg in nginx python3 git curl nftables; do
    dpkg -s "$pkg" >/dev/null 2>&1 || run apt-get install -y "$pkg"
done

for group in avrana-front avrana-games; do
    getent group "$group" >/dev/null || run groupadd --system "$group"
done
id avrana-party >/dev/null 2>&1 \
    || run useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin avrana-party
run usermod -a -G avrana-front avrana-party
run usermod -a -G avrana-front www-data

run install -d -m 0755 -o root -g root /etc/avrana-party /etc/avrana-party/games.d /etc/avrana-party/packages.d \
    /var/lib/avrana-party /var/backups/avrana-party
run install -d -m 0700 -o avrana-party -g avrana-party /etc/avrana-party/game-keys
if [[ ! -e /etc/avrana-party/party-core.json ]]; then
    run install -m 0644 -o root -g root "$checkout/deploy/hosted/party-core.hosted.json" /etc/avrana-party/party-core.json
else
    echo "keep /etc/avrana-party/party-core.json (exists; compare with deploy/hosted/party-core.hosted.json yourself)"
fi
[[ $dry -eq 1 ]] || printf 'hosted\n' > /etc/avrana-party/deploy-profile
echo "+ /etc/avrana-party/deploy-profile = hosted"

run install -m 0644 "$checkout/deploy/party-core/avrana-party-core.service" "$checkout/deploy/party-core/avrana-party-core.socket" \
    "$checkout/deploy/games/avrana-game@.service" "$checkout/deploy/games/avrana-game@.socket" \
    "$checkout/deploy/hosted/avrana-gate.service" /etc/systemd/system/
run install -d -m 0755 /etc/systemd/journald.conf.d
run install -m 0644 "$checkout/deploy/journald/avrana-journald.conf" /etc/systemd/journald.conf.d/avrana.conf
run install -m 0644 "$checkout/deploy/hosted/vm/avrana-staging.nft" /etc/nftables.conf
run nft -c -f /etc/nftables.conf
run systemctl daemon-reload
run systemctl restart systemd-journald
run systemctl enable --now nftables
run systemctl enable --now avrana-party-core.socket
run systemctl enable avrana-party-core.service
# The password gate starts once a password is set (sudo python3 -m avrana.ops.hosted_gate set).
run systemctl enable avrana-gate.service
# The site this checkout renders, so nginx passes `nginx -t` before the first deploy (which compares it
# with the deployed commit's copy and installs that one).
[[ -e /etc/nginx/sites-available/avrana-party ]] \
    || run install -m 0644 "$checkout/deploy/hosted/avrana-party.hosted.nginx" /etc/nginx/sites-available/avrana-party
[[ -e /etc/nginx/sites-enabled/avrana-party ]] || run ln -s /etc/nginx/sites-available/avrana-party /etc/nginx/sites-enabled/avrana-party
[[ -L /etc/nginx/sites-enabled/default ]] && run rm /etc/nginx/sites-enabled/default
run nginx -t
run systemctl reload-or-restart nginx
echo 'provisioned. Next: the first deployment (runbook step 4): sudo bash ~/avrana-party/ops/deploy.sh --party <sha> --games <sha>'
