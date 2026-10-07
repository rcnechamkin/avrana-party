#!/usr/bin/env bash
# Install (or remove) the restricted AP-control helper on party. Owner-run, as root (AVR-298).
#
#     sudo bash ops/ap-control/install-ap-control.sh --user cody          # install
#     sudo bash ops/ap-control/install-ap-control.sh --remove             # uninstall
#          bash ops/ap-control/install-ap-control.sh --print-sudoers cody # show the rule, change nothing
#
# What it grants: the named user may run, via `sudo -n`, ONLY these exact commands:
#     /usr/local/sbin/avrana-ap-control show
#     /usr/local/sbin/avrana-ap-control restore
#     /usr/local/sbin/avrana-ap-control set-channel <36|40|44|48|149|153|157|161> [--lab]
# No wildcards, no shell, no other sudo rights. The sudoers file is validated with visudo before it
# is activated; a failed validation leaves the previous state untouched.
set -euo pipefail

HELPER_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/avrana-ap-control"
HELPER=/usr/local/sbin/avrana-ap-control
SUDOERS=/etc/sudoers.d/avrana-ap-control
CHANNELS=(36 40 44 48 149 153 157 161)

make_sudoers() {  # $1 = user
  local u="$1" c lines=()
  [[ "$u" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "invalid user name: $u" >&2; exit 2; }
  lines+=("$HELPER show" "$HELPER restore")
  for c in "${CHANNELS[@]}"; do lines+=("$HELPER set-channel $c" "$HELPER set-channel $c --lab"); done
  echo "# Managed by ops/ap-control/install-ap-control.sh (AVR-298). Exact argument vectors only."
  printf 'Cmnd_Alias AVRANA_AP_CONTROL = '
  local i
  for i in "${!lines[@]}"; do
    printf '%s' "${lines[$i]}"
    if [ "$i" -lt $(( ${#lines[@]} - 1 )) ]; then printf ', \\\n    '; fi
  done
  echo
  echo "$u ALL=(root) NOPASSWD: AVRANA_AP_CONTROL"
}

case "${1:-}" in
  --print-sudoers) make_sudoers "${2:?user required}"; exit 0;;
  --remove)
    [ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
    rm -f "$SUDOERS" "$HELPER"; echo "removed $SUDOERS and $HELPER (saved state in /var/lib/avrana-party untouched)"; exit 0;;
  --user) USER_NAME="${2:?user required}";;
  *) echo "usage: $0 --user NAME | --remove | --print-sudoers NAME" >&2; exit 2;;
esac

[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
command -v visudo >/dev/null || { echo "visudo not found" >&2; exit 1; }

echo "==> installing helper (root:root 0755)"
install -o root -g root -m 0755 "$HELPER_SRC" "$HELPER"
install -d -m 0755 /var/lib/avrana-party

echo "==> validating sudoers rule before activating it"
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
make_sudoers "$USER_NAME" > "$tmp"
visudo -cf "$tmp"
install -o root -g root -m 0440 "$tmp" "$SUDOERS"
visudo -c >/dev/null

echo "==> done. As $USER_NAME:  sudo -n $HELPER show"
