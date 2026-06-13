#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
SERVICE_DIR="$HOME/.config/systemd/user"
APP_DIR="$HOME/.local/share/applications"
LLAMA_CONF_DIR="$HOME/.config/llama-server"
GEMMA_REL="gemma-4-12b/gemma-4-12b-it-UD-Q4_K_XL.gguf"

mkdir -p "$BIN_DIR" "$SERVICE_DIR" "$APP_DIR" "$LLAMA_CONF_DIR"

install -m 755 "$SCRIPT_DIR/aget_state_tray.py" "$BIN_DIR/aget-state-tray"
install -m 644 "$SCRIPT_DIR/aget-state-tray.service" "$SERVICE_DIR/aget-state-tray.service"
# Expand the %h placeholder in the desktop file's Exec to a real absolute path
# (Desktop Entry Exec has no valid home-dir field code).
sed "s|%h|$HOME|g" "$SCRIPT_DIR/aget-state-tray.desktop" > "$APP_DIR/aget-state-tray.desktop"
chmod 644 "$APP_DIR/aget-state-tray.desktop"

# Seed config before installing the llama unit, so the unit never sees a missing
# current.env even momentarily (EnvironmentFile is also marked optional with a
# leading dash as a second line of defence).
if [ ! -f "$LLAMA_CONF_DIR/models.toml" ]; then
    install -m 644 "$SCRIPT_DIR/models.toml.example" "$LLAMA_CONF_DIR/models.toml"
fi
if [ ! -f "$LLAMA_CONF_DIR/current.env" ]; then
    printf 'LLAMA_MODEL=%s/models/%s\nLLAMA_ARGS=\n' "$HOME" "$GEMMA_REL" \
        > "$LLAMA_CONF_DIR/current.env"
fi

# Back up any existing llama-server.service before overwriting.
if [ -f "$SERVICE_DIR/llama-server.service" ]; then
    cp -a "$SERVICE_DIR/llama-server.service" \
        "$SERVICE_DIR/llama-server.service.bak.$(date +%Y%m%d-%H%M%S)"
fi
install -m 644 "$SCRIPT_DIR/llama-server.service" "$SERVICE_DIR/llama-server.service"

systemctl --user daemon-reload
# disable+enable moves the WantedBy symlink (v1 used default.target).
systemctl --user disable aget-state-tray.service 2>/dev/null || true
systemctl --user enable aget-state-tray.service
systemctl --user restart aget-state-tray.service

echo "Installed. Edit ~/.config/llama-server/models.toml to match your models."
echo "Check status: systemctl --user status aget-state-tray"
