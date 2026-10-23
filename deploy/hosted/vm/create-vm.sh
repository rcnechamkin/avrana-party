#!/usr/bin/env bash
# Create the hosted staging VM on the Media host (docs/runbooks/hosted-staging.md, step 2).
# OWNER-RUN, after explicit approval, on the M700, with sudo. It changes the host in exactly these ways:
#   - defines the libvirt network filter avrana-staging-egress (avrana-staging-egress.nwfilter.xml);
#   - creates one qcow2 disk under --images (default /var/lib/libvirt/images) and one domain,
#     avrana-party-staging, on the existing "default" NAT network, with hard ceilings (vCPUs, memory,
#     a CPU quota, disk I/O weight);
#   - nothing else: no port forward, no bridge, no host firewall rule, no Docker, nginx or tunnel change.
# Undo: sudo bash deploy/hosted/vm/create-vm.sh --destroy
#
#   sudo bash deploy/hosted/vm/create-vm.sh --image debian-13-genericcloud-amd64.qcow2 \
#        --user-data user-data.yaml [--images DIR] [--disk-gb 12] [--ram-mb 2048] [--vcpus 2] [--dry-run]
#
# A member of the libvirt group may run it without sudo: everything goes through qemu:///system, and the
# disk is written to --images, which must then be writable by that user (e.g. a directory on a data drive).
# The image is Debian's official cloud image, downloaded and checksum-verified by the owner (the runbook
# gives the URL and how to check SHA512SUMS); this script never downloads anything. user-data.yaml is the
# owner's copy of cloud-init.user-data.example with the owner's SSH public key; it holds no secret.
set -Eeuo pipefail
name=avrana-party-staging
images=/var/lib/libvirt/images
here=$(cd "$(dirname "$0")" && pwd)
image='' user_data='' disk_gb=12 ram_mb=2048 vcpus=2 dry=0 destroy=0 no_kvm=0
while (($#)); do
    case $1 in
        --image) image=$2; shift 2 ;;
        --user-data) user_data=$2; shift 2 ;;
        --images) images=${2%/}; shift 2 ;;
        --no-kvm) no_kvm=1; shift ;;
        --disk-gb) disk_gb=$2; shift 2 ;;
        --ram-mb) ram_mb=$2; shift 2 ;;
        --vcpus) vcpus=$2; shift 2 ;;
        --dry-run) dry=1; shift ;;
        --destroy) destroy=1; shift ;;
        *) echo "unknown argument $1" >&2; exit 2 ;;
    esac
done
run() { echo "+ $*"; [[ $dry -eq 1 ]] || "$@"; }
V() { virsh -c qemu:///system "$@"; }

if [[ $destroy -eq 1 ]]; then
    V dominfo "$name" >/dev/null 2>&1 && { V destroy "$name" 2>/dev/null || true; run virsh -c qemu:///system undefine "$name" --remove-all-storage --snapshots-metadata --nvram; }
    V nwfilter-list | grep -q avrana-staging-egress && run virsh -c qemu:///system nwfilter-undefine avrana-staging-egress
    rm -f "$images/$name-seed.iso"
    echo "removed $name and its filter; the Media host is as before"
    exit 0
fi

if [[ $EUID -ne 0 && $dry -eq 0 ]]; then
    { V nwfilter-list >/dev/null 2>&1 && [[ -w $images ]]; } || { echo "run with sudo, or as a libvirt group member with --images naming a directory you can write (or --dry-run)" >&2; exit 1; }
fi
[[ -f $image && -f $user_data ]] || { echo '--image and --user-data must name existing files' >&2; exit 1; }
kvm=() virt=()
(( no_kvm )) && kvm=(--no-kvm) virt=(--virt-type qemu)
bash "$here/host-preflight.sh" --images "$images" "${kvm[@]}" --disk-gb "$disk_gb" --ram-mb "$ram_mb" --vcpus "$vcpus" || { echo 'host preflight is not READY; nothing was changed' >&2; exit 1; }
V dominfo "$name" >/dev/null 2>&1 && { echo "$name already exists; nothing was changed" >&2; exit 1; }

run virsh -c qemu:///system nwfilter-define "$here/avrana-staging-egress.nwfilter.xml"
run qemu-img convert -O qcow2 "$image" "$images/$name.qcow2"
run qemu-img resize "$images/$name.qcow2" "${disk_gb}G"
# The seed: cloud-localds (cloud-image-utils) when installed, otherwise virt-install's own --cloud-init,
# which attaches a temporary seed for the first boot only.
if command -v cloud-localds >/dev/null; then
    run cloud-localds "$images/$name-seed.iso" "$user_data"
    seed=(--disk "path=$images/$name-seed.iso,device=cdrom")
else
    seed=(--cloud-init "user-data=$user_data")
fi
# --cpu host-model, no host devices, no shared folders, no graphics; serial console only.
# --no-kvm (no VT-x): software emulation, same devices and filter. Once VT-x is on, change the domain's
# type to kvm (virsh edit) and restart it; the disk is unchanged.
# UEFI: Debian 13's cloud image resets in a loop right after GRUB under SeaBIOS (seen on the M700,
# QEMU 8.2, q35 and i440fx alike); under OVMF it boots.
run virt-install --connect qemu:///system --name "$name" --osinfo debian13 "${virt[@]}" --boot uefi \
    --vcpus "$vcpus" --memory "$ram_mb" --memballoon none \
    --disk "path=$images/$name.qcow2,format=qcow2,bus=virtio" \
    "${seed[@]}" \
    --network "network=default,model=virtio,filterref.filter=avrana-staging-egress" \
    --graphics none --console pty,target_type=serial --noautoconsole --import \
    --autostart
# A CPU ceiling below the vCPU count (150% of one core), and a low I/O and CPU weight, so the
# Media workload always wins contention.
run virsh -c qemu:///system schedinfo "$name" --config --live --set vcpu_quota=75000 vcpu_period=100000 cpu_shares=256
run virsh -c qemu:///system blkiotune "$name" --config --live --weight 200
echo "created $name. Next: the VM's address (virsh domifaddr $name), then provision.sh inside it (runbook step 3)."
