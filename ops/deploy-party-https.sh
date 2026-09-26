#!/usr/bin/env bash
# One-time Pi deployment after DNS-01 issuance and candidate syntax checks.
# Keeps a root-only rollback copy and leaves eth0 management untouched.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

if [[ $# -ne 2 || $EUID -ne 0 ]]; then
    echo 'Usage (as root): deploy-party-https.sh REPO LEGO_STATE' >&2
    exit 2
fi

repo=$1
state=$2
site=/etc/nginx/sites-available/avrana-party
dns=/etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf
ap='Avrana Party Internal'
backup=/root/avrana-party-https-backups/$(date -u +%Y%m%dT%H%M%SZ)
tls=/etc/avrana-party/tls
dns_changed=no
site_changed=no
tls_changed=no
had_current=no

cmp "$repo/avrana-party.nginx" "$repo/arcade/nginx-site"
dnsmasq --test --conf-file="$repo/avrana-captive.conf"
[[ -f $state/certificates/party.avrana.net.crt && \
   -f $state/certificates/party.avrana.net.key ]] || {
    echo 'Pi-local issued certificate is missing' >&2; exit 1;
}

install -d -m 0700 "$backup"
cp -a "$site" "$backup/nginx.site"
cp -a "$dns" "$backup/dnsmasq.conf"
if [[ -d $tls ]]; then
    cp -a "$tls" "$backup/tls"
fi
if [[ -L $tls/current ]]; then
    readlink "$tls/current" > "$backup/previous-current-target"
    had_current=yes
fi
echo "Pi-only backup: $backup"

rollback() {
    set +e
    echo 'Deployment failed; restoring prior live configuration' >&2
    if [[ $site_changed == yes ]]; then
        cp -a "$backup/nginx.site" "$site"
    fi
    if [[ $tls_changed == yes ]]; then
        if [[ $had_current == yes ]]; then
            ln -s "$(cat "$backup/previous-current-target")" "$tls/.current-rollback-$$"
            mv -Tf "$tls/.current-rollback-$$" "$tls/current"
        else
            rm -f "$tls/current"
        fi
    fi
    if [[ $site_changed == yes || $tls_changed == yes ]]; then
        nginx -t && systemctl reload nginx
    fi
    if [[ $dns_changed == yes ]]; then
        cp -a "$backup/dnsmasq.conf" "$dns"
        nmcli connection down "$ap" || true
        nmcli connection up "$ap" ifname wlan0
    fi
}
trap rollback ERR

# The key and ACME account remain on the Pi, stored root-only after issuance.
install -d -m 0700 /var/lib/avrana-party /var/lib/avrana-party/lego
cp -a "$state/." /var/lib/avrana-party/lego/
chown -R root:root /var/lib/avrana-party/lego
chmod -R go-rwx /var/lib/avrana-party/lego
install -d -m 0755 /usr/local/libexec/avrana-party
install -m 0755 "$repo/ops/install-party-certificate.sh" \
    /usr/local/libexec/avrana-party/install-party-certificate.sh
install -m 0755 "$repo/ops/renew-party-certificate.sh" \
    /usr/local/libexec/avrana-party/renew-party-certificate.sh
install -m 0755 "$repo/ops/check-party-config.sh" \
    /usr/local/libexec/avrana-party/check-party-config.sh
install -m 0755 /home/cody/avrana-lab/https/package/usr/bin/lego /usr/local/bin/lego

/usr/local/libexec/avrana-party/install-party-certificate.sh \
    /var/lib/avrana-party/lego/certificates/party.avrana.net.crt \
    /var/lib/avrana-party/lego/certificates/party.avrana.net.key
tls_changed=yes

install -m 0644 "$repo/avrana-captive.conf" "$dns.next.$$"
mv -f "$dns.next.$$" "$dns"
dns_changed=yes
nmcli connection down "$ap"
nmcli connection up "$ap" ifname wlan0
[[ $(dig +short @10.42.0.1 party.avrana.net A | head -n 1) == 10.42.0.1 ]]
[[ $(dig +short @10.42.0.1 captive.apple.com A | head -n 1) == 10.42.0.1 ]]

install -m 0644 "$repo/avrana-party.nginx" "$site.next.$$"
mv -f "$site.next.$$" "$site"
site_changed=yes
nginx -t
systemctl reload nginx
cmp "$repo/avrana-party.nginx" "$site"

trap - ERR
echo "HTTPS configuration deployed; rollback backup: $backup"
