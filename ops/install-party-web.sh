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
# Only committed files are used: the commit is exported with `git archive` and built from there,
# so ignored or untracked files (and the checkout's working tree) never reach the web root.
# One exception, by the owner's decision (AVR-306): game covers, which are never committed. They
# are read from one folder ($AVRANA_COVERS_DIR, default /srv/avrana/covers, beside the owner's
# ROM), and only what avrana/web/covers.py passes is copied: plain image files named for a game,
# of bounded size, never a link. A missing folder or a bad file never fails an install.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH

dest=${AVRANA_WEB_ROOT:-/var/www/avrana-party/web}
covers=${AVRANA_COVERS_DIR:-/srv/avrana/covers}
[[ $covers == /* ]] || covers=$PWD/$covers      # the build runs in another directory
keep=5
mode=install
kill_flag=()
case ${1:-} in
    --rollback) mode=rollback; shift ;;
    --kill) kill_flag=(--no-service-worker); shift ;;
esac

# AVR-337 (EXPERIMENTAL): when .avrgame packages are installed the appliance serves an effective catalog
# (the release catalog plus their rows) instead of the release's own. It is derived from the release,
# so it is regenerated here whenever "current" moves, a new release or a rollback. Does nothing when no
# package is installed and no overlay exists. A failure never fails the install; the overlay is removed (here too,
# in case the tool itself could not start), so the release catalog is served until the owner re-runs it.
refresh_catalog() {
    local tree overlay=${AVRANA_CATALOG_OVERLAY:-/var/lib/avrana-party/catalog/catalog.json}
    local records=${AVRANA_PACKAGE_RECORDS:-/etc/avrana-party/packages.d}
    [[ -e $overlay || -n $(ls -A "$records" 2>/dev/null) ]] || return 0
    tree=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)
    (cd "$tree" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.catalog_overlay refresh --base "$1/catalog.json" --out-dir "$(dirname "$overlay")" --records-dir "$records") ||
        { rm -f "$overlay" 2>/dev/null    # fail toward the release: never leave an overlay built from the previous release
          if [[ -e $overlay ]]; then
              echo "WARNING: the effective catalog could NOT be regenerated for this release AND the old overlay could NOT be removed (not root?): phones may be served a STALE catalog. Run: sudo rm $overlay && sudo ops/catalog-overlay refresh" >&2
          else
              echo "WARNING: the effective catalog could NOT be regenerated for this release; the overlay was removed, so the release catalog is served and installed .avrgame packages have no tile. Run: sudo ops/catalog-overlay refresh" >&2
          fi; }
}

switch_to() {
    ln -sfn "$1" "$dest/current.new"
    mv -Tf "$dest/current.new" "$dest/current"
    echo "current -> $1"
    refresh_catalog "$1"
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
if [[ -e $release ]]; then
    release=$release-$$  # two installs in the same second
fi

install -d -m 0755 "$dest" "$dest/releases"
work=$(mktemp -d "$dest/releases/.build.XXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir "$work/src"
git -C "$checkout" archive --format=tar "$commit" avrana web/party | tar -x -C "$work/src"
(cd "$work/src" && PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.web.build \
    --out "$work/out" --commit "$commit" --covers "$covers" "${kill_flag[@]}")
chmod -R u=rwX,go=rX "$work/out"
if [[ $EUID -eq 0 ]]; then
    chown -R root:root "$work/out"
fi
[[ ! -e $release ]] || { echo "$release already exists" >&2; exit 1; }
mv -T "$work/out" "$release"
switch_to "$release"

# Keep the newest $keep releases, never the one "current" points to.
now=$(readlink -f "$dest/current")
find "$dest/releases" -mindepth 1 -maxdepth 1 -type d ! -name '.*' | sort -r | tail -n +$((keep + 1)) |
    while IFS= read -r old; do
        [[ $(readlink -f "$old") == "$now" ]] || rm -rf -- "$old"
    done
