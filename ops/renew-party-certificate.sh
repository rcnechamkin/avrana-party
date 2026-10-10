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

# What this script guarantees, whatever lego version the appliance has (the repository does not
# record it): the names it asks lego for are decided here, from the certificate that is installed
# now. An appliance whose installed certificate does not name games.avrana.net renews exactly as
# before (one --domains). One that does asks for both names and tells the installer to refuse a
# renewal that comes back without the second, so a lego that renews one name only cannot replace a
# two-name certificate: the installer stops before changing anything and `current` stays as it is.
# A name is never added here: that is a new issuance (docs/runbooks/game-origin.md).
lego=/usr/local/bin/lego
state=/var/lib/avrana-party/lego
current=/etc/avrana-party/tls/current
domains=(--domains party.avrana.net)
if openssl x509 -in "$current/fullchain.pem" -noout -checkhost games.avrana.net 2>/dev/null | grep -q 'does match'; then
    domains+=(--domains games.avrana.net)
    export AVRANA_REQUIRE_GAME_NAME=1
fi
"$lego" --accept-tos --email "$ACME_EMAIL" --dns cloudflare     "${domains[@]}" --path "$state" renew --days 30

"$(dirname "$0")/install-party-certificate.sh"     "$state/certificates/party.avrana.net.crt"     "$state/certificates/party.avrana.net.key"
openssl x509 -in "$state/certificates/party.avrana.net.crt" -noout -ext subjectAltName | tail -n +2 | sed 's/^ *//' || true
