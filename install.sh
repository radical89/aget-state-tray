#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
SERVICE_DIR="$HOME/.config/systemd/user"

mkdir -p "$BIN_DIR" "$SERVICE_DIR"

install -m 755 "$SCRIPT_DIR/aget_state_tray.py" "$BIN_DIR/aget-state-tray"
install -m 644 "$SCRIPT_DIR/aget-state-tray.service" "$SERVICE_DIR/aget-state-tray.service"

systemctl --user daemon-reload
systemctl --user enable --now aget-state-tray.service

echo "Installed. The tray icon should appear within a few seconds."
echo "To check status: systemctl --user status aget-state-tray"
