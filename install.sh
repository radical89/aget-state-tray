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
install -m 644 "$SCRIPT_DIR/aget-state-tray.desktop" "$APP_DIR/aget-state-tray.desktop"

# Back up any existing llama-server.service before overwriting.
if [ -f "$SERVICE_DIR/llama-server.service" ]; then
    cp -a "$SERVICE_DIR/llama-server.service" \
        "$SERVICE_DIR/llama-server.service.bak.$(date +%Y%m%d-%H%M%S)"
fi
install -m 644 "$SCRIPT_DIR/llama-server.service" "$SERVICE_DIR/llama-server.service"

# Seed config only if absent (never clobber the user's edits).
if [ ! -f "$LLAMA_CONF_DIR/models.toml" ]; then
    install -m 644 "$SCRIPT_DIR/models.toml.example" "$LLAMA_CONF_DIR/models.toml"
fi
if [ ! -f "$LLAMA_CONF_DIR/current.env" ]; then
    printf 'LLAMA_MODEL=%s/models/%s\nLLAMA_ARGS=\n' "$HOME" "$GEMMA_REL" \
        > "$LLAMA_CONF_DIR/current.env"
fi

systemctl --user daemon-reload
# disable+enable moves the WantedBy symlink (v1 used default.target).
systemctl --user disable aget-state-tray.service 2>/dev/null || true
systemctl --user enable aget-state-tray.service
systemctl --user restart aget-state-tray.service

echo "Installed. Edit ~/.config/llama-server/models.toml to match your models."
echo "Check status: systemctl --user status aget-state-tray"
