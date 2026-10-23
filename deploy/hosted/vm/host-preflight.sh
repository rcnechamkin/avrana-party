#!/usr/bin/env bash
# Read-only checks on the Media host (M700) before the hosted staging VM is created
# (docs/runbooks/hosted-staging.md, step 1). Changes nothing: no package, network, VM, file or unit.
# Run as the operator (no sudo needed); prints one line per check and READY/NOT_READY.
#
#   bash deploy/hosted/vm/host-preflight.sh [--images DIR] [--disk-gb 12] [--ram-mb 2048] [--vcpus 2]
set -uo pipefail
disk_gb=12 ram_mb=2048 vcpus=2 pool=/var/lib/libvirt/images no_kvm=0
while (($#)); do
    case $1 in
        --images) pool=${2%/}; shift 2 ;;
        --no-kvm) no_kvm=1; shift ;;
        --disk-gb) disk_gb=$2; shift 2 ;;
        --ram-mb) ram_mb=$2; shift 2 ;;
        --vcpus) vcpus=$2; shift 2 ;;
        *) echo "unknown argument $1" >&2; exit 2 ;;
    esac
done
fail=0
say() { printf '%-5s %-26s %s\n' "$1" "$2" "$3"; [[ $1 == FAIL ]] && fail=1; return 0; }

free_gb=$(df -BG --output=avail "$(test -d "$pool" && echo "$pool" || echo /)" | tail -1 | tr -dc 0-9)
used_pct=$(df --output=pcent / | tail -1 | tr -dc 0-9)
# The VM's disk is thin (qcow2) but may fill to disk_gb; one snapshot can add up to as much again
# in the worst case. Keep 15 GB free for Media on top of that.
need=$((disk_gb * 2 + 15))
if (( free_gb >= need )); then say PASS disk "${free_gb} GB free under $pool (needs ${need}: VM ${disk_gb} + snapshot ${disk_gb} + 15 reserve); / ${used_pct}% used"
else say FAIL disk "${free_gb} GB free under $pool; needs ${need} (VM ${disk_gb} + snapshot ${disk_gb} + 15 reserve)"; fi

avail_mb=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
if (( avail_mb >= ram_mb + 4096 )); then say PASS memory "${avail_mb} MB available; VM ceiling ${ram_mb} MB leaves $((avail_mb - ram_mb)) MB"
else say FAIL memory "${avail_mb} MB available; ${ram_mb} MB + 4096 reserve does not fit"; fi

cores=$(nproc)
if (( vcpus < cores )); then say PASS cpu "${cores} cores; VM gets ${vcpus} vCPUs (and a CPU quota, see create-vm.sh)"
else say FAIL cpu "${cores} cores; ${vcpus} vCPUs would be every core"; fi

if [[ -r /dev/kvm ]] || [[ -e /dev/kvm ]]; then say PASS kvm "/dev/kvm present"
elif (( no_kvm )); then say WARN kvm "/dev/kvm missing: the VM runs emulated (--no-kvm), slower; enable VT-x in firmware to switch"
else say FAIL kvm "/dev/kvm missing: no hardware virtualization (enable VT-x in firmware, or --no-kvm to run emulated)"; fi
if command -v virsh >/dev/null && command -v virt-install >/dev/null; then say PASS libvirt-tools "virsh and virt-install installed"
elif command -v virsh >/dev/null; then say FAIL libvirt-tools "virsh present, virt-install missing (package virtinst: an owner-approved install)"
else say FAIL libvirt-tools "virsh missing"; fi

net=$(virsh -c qemu:///system net-info default 2>/dev/null | awk '/Active:/ {print $2}')
if [[ $net == yes ]]; then say PASS libvirt-net "default NAT network active ($(virsh -c qemu:///system net-dumpxml default 2>/dev/null | grep -o "address='[0-9.]*'" | head -1))"
else say FAIL libvirt-net "default network not active or not readable as $(id -un)"; fi

if virsh -c qemu:///system dominfo avrana-party-staging >/dev/null 2>&1; then say FAIL vm-name "a domain named avrana-party-staging already exists"
else say PASS vm-name "no domain named avrana-party-staging"; fi
if virsh -c qemu:///system nwfilter-list 2>/dev/null | grep -q avrana-staging-egress; then say INFO nwfilter "avrana-staging-egress already defined"
else say PASS nwfilter "avrana-staging-egress not yet defined"; fi

# The tunnels on this host belong to Media; the staging tunnel runs inside the VM, never here.
for unit in cloudflared cloudflared-avrana; do
    say INFO "tunnel:$unit" "$(systemctl is-active "$unit" 2>/dev/null) (Media; never touched)"
done
if command -v ss >/dev/null && ss -ltn | grep -q ':8080 .*0.0.0.0\|\*:8080'; then
    say INFO host-8080 "the host listens on :8080; the VM's nginx uses its own loopback, so no clash"
fi

echo
if (( fail )); then echo 'host preflight: NOT_READY'; exit 1; fi
echo 'host preflight: READY'
