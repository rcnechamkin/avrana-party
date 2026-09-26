#!/usr/bin/env bash
# Root-only renewal job. The Cloudflare token is stored only on the Pi.
set -euo pipefail
umask 077

credentials=/etc/avrana-party/cloudflare.env
[[ -r $credentials ]] || { echo 'Cloudflare credential file is missing' >&2; exit 1; }
# shellcheck source=/dev/null
source "$credentials"
[[ -n ${CF_DNS_API_TOKEN:-} ]] || { echo 'CF_DNS_API_TOKEN is missing' >&2; exit 1; }
[[ -n ${ACME_EMAIL:-} ]] || { echo 'ACME_EMAIL is missing' >&2; exit 1; }
export CF_DNS_API_TOKEN

lego=/usr/local/bin/lego
state=/var/lib/avrana-party/lego
"$lego" --accept-tos --email "$ACME_EMAIL" --dns cloudflare \
    --domains party.avrana.net --path "$state" renew --days 30

"$(dirname "$0")/install-party-certificate.sh" \
    "$state/certificates/party.avrana.net.crt" \
    "$state/certificates/party.avrana.net.key"
