#!/usr/bin/env bash
# Install the bounded network-hardware health check + 60s timer on party (AVR-297 proves it).
# Run as root on party:
#
#     sudo bash telemetry/install-pi-health-check.sh
#
# Output: one journald line per run (`journalctl -u pi-health-check`) and /run/avrana/pi-health.json
# (volatile, world-readable; `avrana.pi-health/v0`). It observes and logs only: nothing here restarts a
# service or reboots the appliance. Re-running is safe.
set -euo pipefail

BIN_DIR="/opt/avrana-telemetry"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then echo "run as root (sudo)" >&2; exit 1; fi

echo "==> installing check to ${BIN_DIR}"
install -d "$BIN_DIR"
install -m 0755 "$SCRIPT_DIR/pi-health-check.py" "$BIN_DIR/pi-health-check.py"

echo "==> installing systemd service + timer"
install -m 0644 "$SCRIPT_DIR/pi-health-check.service" /etc/systemd/system/pi-health-check.service
install -m 0644 "$SCRIPT_DIR/pi-health-check.timer"   /etc/systemd/system/pi-health-check.timer
systemd-analyze verify /etc/systemd/system/pi-health-check.service /etc/systemd/system/pi-health-check.timer
systemctl daemon-reload
systemctl enable --now pi-health-check.timer

echo "==> one run now:"
systemctl start pi-health-check.service
journalctl -u pi-health-check -n 3 --no-pager
echo
echo "State file: /run/avrana/pi-health.json"
