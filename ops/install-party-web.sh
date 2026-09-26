#!/usr/bin/env bash
# Install, roll back or switch off the Full Mode web shell served at https://party.avrana.net/party/.
# Pi only, run by the owner:
#
#   sudo bash ops/install-party-web.sh /home/cody/avrana-party          # build + switch "current"
#   sudo bash ops/install-party-web.sh --rollback                       # previous release
#   sudo bash ops/install-party-web.sh --kill /home/cody/avrana-party   # remove offline copies from phones
#
# Static files only: no service, port or reload. nginx serves $dest/current (see the /party/
# locations in avrana-party.nginx, which must be deployed once, owner-approved). Each release is a
# new directory; "current" switches atomically; the five newest releases are kept for rollback.
# The build runs from the given clean checkout without writing into it.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

dest=${AVRANA_WEB_ROOT:-/var/www/avrana-party/web}
keep=5
mode=install
kill_flag=()
case ${1:-} in
    --rollback) mode=rollback; shift ;;
    --kill) kill_flag=(--no-service-worker); shift ;;
esac

switch_to() {
    ln -sfn "$1" "$dest/current.new"
    mv -Tf "$dest/current.new" "$dest/current"
    echo "current -> $1"
}

if [[ $mode == rollback ]]; then
    [[ -L $dest/current ]] || { echo "no current release in $dest" >&2; exit 1; }
    now=$(readlink -f "$dest/current")
    previous=''
    while IFS= read -r dir; do
        [[ $(readlink -f "$dir") == "$now" ]] && break
        previous=$dir
    done < <(find "$dest/releases" -mindepth 1 -maxdepth 1 -type d ! -name '.*' | sort)
    [[ -n $previous ]] || { echo 'no older release to roll back to' >&2; exit 1; }
    switch_to "$previous"
    exit 0
fi

if [[ $# -ne 1 ]]; then
    echo 'Usage: install-party-web.sh [--kill] CHECKOUT | --rollback' >&2
    exit 2
fi
checkout=$(cd "$1" && pwd)
if [[ -n $(git -C "$checkout" status --porcelain) && ${AVRANA_ALLOW_DIRTY:-0} != 1 ]]; then
    echo "$checkout has uncommitted changes; deploy only a clean, reviewed commit" >&2
    exit 1
fi
commit=$(git -C "$checkout" rev-parse HEAD)
stamp=$(date -u +%Y%m%dT%H%M%SZ)
release=$dest/releases/$stamp-${commit:0:12}

install -d -m 0755 "$dest" "$dest/releases"
work=$(mktemp -d "$dest/releases/.build.XXXXXX")
trap 'rm -rf "$work"' EXIT
(cd "$checkout" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.web.build \
    --out "$work/out" --commit "$commit" "${kill_flag[@]}")
chmod -R u=rwX,go=rX "$work/out"
if [[ $EUID -eq 0 ]]; then
    chown -R root:root "$work/out"
fi
mv "$work/out" "$release"
switch_to "$release"

# Keep the newest $keep releases, never the one "current" points to.
now=$(readlink -f "$dest/current")
find "$dest/releases" -mindepth 1 -maxdepth 1 -type d ! -name '.*' | sort -r | tail -n +$((keep + 1)) |
    while IFS= read -r old; do
        [[ $(readlink -f "$old") == "$now" ]] || rm -rf -- "$old"
    done
