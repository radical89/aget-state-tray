#!/usr/bin/env bash
set -euo pipefail

systemctl --user disable --now aget-state-tray.service 2>/dev/null || true

rm -f "$HOME/.local/bin/aget-state-tray"
rm -f "$HOME/.config/systemd/user/aget-state-tray.service"

systemctl --user daemon-reload

echo "Uninstalled."
