#!/usr/bin/env bash
# Install the Beszel agent on party as a systemd service, pinned to the version
# of the hub running on avrana (0.18.7). No Docker. Run as root on party:
#
#     sudo bash telemetry/install-beszel-agent.sh
#
# After it finishes: in the hub UI (http://10.0.0.218:8093) click "Add System",
# name it "party", host 10.0.0.142 (eth0 since 2026-09-24), port 45876. The hub then connects out to the
# agent using the public key below (the hub keeps the private half).
set -euo pipefail

VERSION="0.18.7"
ARCH="arm64"
SHA256="0134256068937cab74b7f26e37007a4b5bf3d52cd40496a8b8b0ebbbb1a6f02f"
URL="https://github.com/henrygd/beszel/releases/download/v${VERSION}/beszel-agent_linux_${ARCH}.tar.gz"

# Hub public key (safe to store: it is the PUBLIC half; the private key stays on
# avrana). Override with KEY=... in the environment if the hub is ever re-keyed.
KEY="${KEY:-ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGZTUVj/fl+QTA0lYxW8mrxP0yrLoM4mqLFSA/Ontz8w}"
LISTEN_PORT="${LISTEN_PORT:-45876}"

BIN_DIR="/opt/beszel-agent"
ENV_FILE="/etc/beszel-agent.env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then echo "run as root (sudo)" >&2; exit 1; fi

echo "==> creating 'beszel' system user (if missing)"
id beszel >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin beszel

echo "==> downloading beszel-agent ${VERSION} (${ARCH})"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
curl -fsSL -o "$tmp/agent.tgz" "$URL"

echo "==> verifying checksum"
echo "${SHA256}  ${tmp}/agent.tgz" | sha256sum -c -

echo "==> installing binary to ${BIN_DIR}"
install -d "$BIN_DIR"
tar -xzf "$tmp/agent.tgz" -C "$tmp" beszel-agent
install -m 0755 "$tmp/beszel-agent" "$BIN_DIR/beszel-agent"

echo "==> writing ${ENV_FILE}"
umask 077
cat >"$ENV_FILE" <<EOF
KEY="${KEY}"
LISTEN=${LISTEN_PORT}
EOF

echo "==> installing systemd unit"
install -m 0644 "$SCRIPT_DIR/beszel-agent.service" /etc/systemd/system/beszel-agent.service
systemctl daemon-reload
systemctl enable --now beszel-agent.service

echo "==> status"
systemctl --no-pager --full status beszel-agent.service | head -n 12 || true
echo
echo "Agent listening on :${LISTEN_PORT}. Next: add system 'party' (10.0.0.142:${LISTEN_PORT}, eth0) in the hub UI."
