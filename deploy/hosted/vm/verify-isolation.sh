#!/usr/bin/env bash
# Prove, by trying, that the hosted staging VM cannot reach the Media host, its management interfaces
# or the LAN, and can reach what it needs (docs/runbooks/hosted-staging.md, steps 3 and 6). Run INSIDE
# the VM. A probe is a real TCP connection attempt with a deadline:
#   connected      the target answered: the VM can reach it              -> FAIL for a forbidden target
#   refused/reset  the packet reached a host that said no: not isolated  -> FAIL for a forbidden target
#   timed out      nothing came back: the packet was dropped              -> PASS for a forbidden target
#
#   bash verify-isolation.sh                 # both layers in place (the normal state)
#   sudo bash verify-isolation.sh --host-layer-only
#       the VM's own nftables is set aside for the run and put back after (trap), so what is measured
#       is the host-side libvirt filter alone: the boundary that root inside the VM cannot lift.
#
# Targets: every port the Media host listens on that matters (SSH, nginx, Jellyfin, Home Assistant,
# Authentik, Plex, Docker-published apps, libvirt's own DNS on TCP is allowed), on both the libvirt
# gateway address and the host's LAN address; the LAN router and the Pi; the link-local metadata address.
# Exit 0 only when every forbidden probe timed out and every required one connected.
set -uo pipefail
GATEWAY=${AVRANA_STAGING_GATEWAY:-192.168.122.1}
MEDIA_LAN=${AVRANA_MEDIA_LAN:-10.0.0.218}
LAN_ROUTER=${AVRANA_LAN_ROUTER:-10.0.0.1}
PI=${AVRANA_PI_LAN:-10.0.0.142}
DEADLINE=${AVRANA_PROBE_SECONDS:-4}
MEDIA_PORTS=(22 80 443 3000 5055 8080 8083 8092 8096 8123 8197 9000 13378 25600 32400)
host_only=0 fail=0
[[ ${1:-} == --host-layer-only ]] && host_only=1

probe() {   # probe HOST PORT -> connected | refused | timeout
    local out rc
    out=$(timeout "$((DEADLINE + 1))" bash -c "exec 3<>/dev/tcp/$1/$2" 2>&1); rc=$?
    if [[ $rc -eq 0 ]]; then echo connected
    elif [[ $rc -eq 124 || $out == *"timed out"* ]]; then echo timeout
    elif [[ $out == *"refused"* || $out == *"reset"* || $out == *"No route"* || $out == *"unreachable"* ]]; then
        # "No route"/"unreachable" may be a local nftables reject or an ICMP from far away; both mean a decision
        # was made by something that saw the packet. Count only a silent drop as isolation.
        echo refused
    else echo timeout
    fi
}
forbid() { local r; r=$(probe "$1" "$2")
    if [[ $r == timeout ]]; then printf 'PASS  blocked   %-22s %s\n' "$1:$2" "$3"
    else printf 'FAIL  %-9s %-22s %s\n' "$r" "$1:$2" "$3"; fail=1; fi; }
need() { local r; r=$(probe "$1" "$2")
    if [[ $r == connected ]]; then printf 'PASS  reached   %-22s %s\n' "$1:$2" "$3"
    else printf 'FAIL  %-9s %-22s %s (required)\n' "$r" "$1:$2" "$3"; fail=1; fi; }

if [[ $host_only -eq 1 ]]; then
    [[ $EUID -eq 0 ]] || { echo '--host-layer-only needs sudo (it sets the VM firewall aside)' >&2; exit 2; }
    saved=$(mktemp)
    nft list ruleset > "$saved"
    trap 'nft -f "$saved" && echo "VM firewall restored"; rm -f "$saved"' EXIT
    nft flush ruleset
    echo 'VM firewall set aside: measuring the host-side filter alone'
fi

echo "== forbidden: the Media host on its libvirt gateway address ($GATEWAY)"
for port in "${MEDIA_PORTS[@]}"; do forbid "$GATEWAY" "$port" 'Media host'; done
echo "== forbidden: the Media host on the LAN ($MEDIA_LAN)"
for port in "${MEDIA_PORTS[@]}"; do forbid "$MEDIA_LAN" "$port" 'Media host'; done
echo '== forbidden: the LAN and management addresses'
forbid "$LAN_ROUTER" 80 'LAN router admin'
forbid "$LAN_ROUTER" 443 'LAN router admin'
forbid "$PI" 22 'the Pi appliance'
forbid "$PI" 443 'the Pi appliance'
forbid 169.254.169.254 80 'link-local metadata'
forbid 172.17.0.1 2375 'a Docker bridge'

echo '== required'
if getent hosts region1.v2.argotunnel.com >/dev/null; then printf 'PASS  resolved  %-22s %s\n' 'DNS' 'through the libvirt gateway'
else printf 'FAIL  %-9s %-22s %s\n' 'no-answer' 'DNS' 'name resolution (required)'; fail=1; fi
need region1.v2.argotunnel.com 7844 'Cloudflare tunnel edge'
need deb.debian.org 443 'Debian packages'
need github.com 443 'GitHub (deploy fetch)'

echo
if (( fail )); then echo 'isolation: FAIL'; exit 1; fi
echo "isolation: PASS ($([[ $host_only -eq 1 ]] && echo 'host-side filter alone' || echo 'both layers'))"
