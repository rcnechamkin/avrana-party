#!/usr/bin/env bash
# Install the lightweight Pi-specific telemetry sampler + its 60s timer on party.
# Run as root on party:
#
#     sudo bash telemetry/install-pi-throttle-check.sh
#
# Output: /var/log/avrana/pi-throttle.jsonl (JSON lines), rotated by
# /etc/logrotate.d/avrana-telemetry (AVR-30). This complements Beszel; it does not replace it.
# Re-running it is safe: it only (re)installs files and re-enables the timer.
set -euo pipefail

BIN_DIR="/opt/avrana-telemetry"
LOG_DIR="/var/log/avrana"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then echo "run as root (sudo)" >&2; exit 1; fi

echo "==> installing sampler to ${BIN_DIR}"
install -d "$BIN_DIR" "$LOG_DIR"
install -m 0755 "$SCRIPT_DIR/pi-throttle-check.sh" "$BIN_DIR/pi-throttle-check.sh"

echo "==> installing log rotation (AVR-30: weekly or 10 MB, 8 compressed generations)"
install -m 0644 "$SCRIPT_DIR/avrana-telemetry.logrotate" /etc/logrotate.d/avrana-telemetry

echo "==> installing systemd timer"
install -m 0644 "$SCRIPT_DIR/pi-throttle-check.service" /etc/systemd/system/pi-throttle-check.service
install -m 0644 "$SCRIPT_DIR/pi-throttle-check.timer"   /etc/systemd/system/pi-throttle-check.timer
systemctl daemon-reload
systemctl enable --now pi-throttle-check.timer

echo "==> a single sample now:"
"$BIN_DIR/pi-throttle-check.sh" --label install-check
echo
echo "Timer active. Log: ${LOG_DIR}/pi-throttle.jsonl"
echo "For a baseline snapshot at 1s resolution, e.g.:"
echo "  sudo $BIN_DIR/pi-throttle-check.sh --interval 1 --count 60 --label idle --append $LOG_DIR/baseline.jsonl"
