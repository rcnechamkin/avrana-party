#!/usr/bin/env bash
# Syntax-check candidate configs without touching live services or TLS state.
# Run on the Pi with nginx, dnsmasq and openssl installed.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

repo=${1:-.}
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
umask 077

# This throwaway leaf is only a parser input for nginx -t, never served to guests.
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -nodes -days 1 -subj /CN=party.avrana.net \
    -keyout "$scratch/test.key" -out "$scratch/test.crt" >/dev/null 2>&1
sed \
    -e "s#/etc/avrana-party/tls/current/fullchain.pem#$scratch/test.crt#g" \
    -e "s#/etc/avrana-party/tls/current/privkey.pem#$scratch/test.key#g" \
    -e 's/listen 80 default_server;/listen 18080 default_server;/' \
    -e 's/listen \[::\]:80 default_server;/listen [::]:18080 default_server;/' \
    -e 's/listen 443 ssl;/listen 18443 ssl;/' \
    -e 's/listen \[::\]:443 ssl;/listen [::]:18443 ssl;/' \
    "$repo/avrana-party.nginx" > "$scratch/site.conf"
cat > "$scratch/nginx.conf" <<EOF
pid $scratch/nginx.pid;
error_log $scratch/error.log;
events {}
http { access_log $scratch/access.log; include $scratch/site.conf; }
EOF
nginx -t -c "$scratch/nginx.conf"
dnsmasq --test --conf-file="$repo/avrana-captive.conf"
cmp "$repo/avrana-party.nginx" "$repo/arcade/nginx-site"
