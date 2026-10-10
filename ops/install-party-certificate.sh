#!/usr/bin/env bash
# Install a DNS-01-issued certificate on the Party Pi without copying its key
# to another machine. Run as root after placing this script on the Pi.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

if [[ $# -ne 2 || $EUID -ne 0 ]]; then
    echo 'Usage (as root): install-party-certificate.sh FULLCHAIN_PEM PRIVATE_KEY_PEM' >&2
    exit 2
fi

certificate=$1
private_key=$2
tls_dir=/etc/avrana-party/tls
release=$(date -u +%Y%m%dT%H%M%SZ)-$$
release_dir=$tls_dir/releases/$release
current=$tls_dir/current

[[ -f $certificate && -f $private_key ]] || { echo 'Certificate or key is missing' >&2; exit 1; }
openssl x509 -in "$certificate" -noout -checkhost party.avrana.net >/dev/null
# The game origin (ADR 0013, AVR-319): the certificate should also name games.avrana.net. An
# appliance that still has the one-name certificate is not broken by this (nginx loads it, only a
# browser refuses the game host), so this says so and goes on, unless the caller requires the name
# (AVRANA_REQUIRE_GAME_NAME=1, as the two-name issuance in docs/runbooks/game-origin.md does).
if ! openssl x509 -in "$certificate" -noout -checkhost games.avrana.net | grep -q 'does match'; then
    if [[ ${AVRANA_REQUIRE_GAME_NAME:-} == 1 ]]; then
        echo 'Certificate does not name games.avrana.net' >&2
        exit 1
    fi
    echo 'Note: this certificate does not name games.avrana.net (the game origin needs the two-name certificate: docs/runbooks/game-origin.md)' >&2
fi
openssl x509 -in "$certificate" -noout -checkend 86400 >/dev/null
openssl verify -purpose sslserver -CApath /etc/ssl/certs -untrusted "$certificate" "$certificate" >/dev/null
cert_pub=$(openssl x509 -in "$certificate" -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum)
key_pub=$(openssl pkey -in "$private_key" -pubout -outform DER | sha256sum)
[[ $cert_pub == "$key_pub" ]] || { echo 'Certificate and private key do not match' >&2; exit 1; }
if [[ -f $current/fullchain.pem && -f $current/privkey.pem ]] && \
   cmp -s "$certificate" "$current/fullchain.pem" && \
   cmp -s "$private_key" "$current/privkey.pem"; then
    echo 'Certificate is already installed'
    exit 0
fi

# A failed renewal must leave the last working certificate and nginx active.
install -d -m 0700 "$tls_dir" "$tls_dir/releases" "$release_dir"
install -m 0644 "$certificate" "$release_dir/fullchain.pem"
install -m 0600 "$private_key" "$release_dir/privkey.pem"
if [[ -L $current ]]; then
    old_target=$(readlink "$current")
else
    old_target=
fi
next_link=$tls_dir/.current-next-$$
ln -s "releases/$release" "$next_link"
mv -Tf "$next_link" "$current"

rollback() {
    if [[ -n $old_target ]]; then
        ln -s "$old_target" "$next_link"
        mv -Tf "$next_link" "$current"
    else
        rm -f "$current"
    fi
}

if ! nginx -t; then
    rollback
    echo 'nginx validation failed; previous certificate restored' >&2
    exit 1
fi
if ! systemctl reload nginx; then
    rollback
    systemctl reload nginx || true
    echo 'nginx reload failed; previous certificate restored' >&2
    exit 1
fi
echo "Installed certificate release $release"
