#!/bin/bash
# Install CANARY systemd timer for the current user.
# Usage: ./deploy/install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$SYSTEMD_DIR"

cp "$SCRIPT_DIR/canary.service" "$SYSTEMD_DIR/canary.service"
cp "$SCRIPT_DIR/canary.timer" "$SYSTEMD_DIR/canary.timer"

systemctl --user daemon-reload
systemctl --user enable canary.timer
systemctl --user start canary.timer

echo "CANARY timer installed and started."
echo "Check status: systemctl --user status canary.timer"
echo "View logs:    journalctl --user -u canary.service"
