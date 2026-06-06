# aget-state-tray

A lightweight system tray indicator for Linux showing whether your llama.cpp inference server is running, with live VRAM usage display. Left-click to start or stop the server instantly.

| State | Icon | Meaning |
|---|---|---|
| Running | Green `AI` + `14G` | llama-server active, VRAM in use |
| Stopped | Grey `AI` | llama-server stopped, VRAM free |

Built for gaming/AI workflows where you want to free GPU VRAM for games without opening a terminal — one click stops the inference server, one click starts it again.

## How it works

Uses **D-Bus event subscription** (not polling) to detect when `llama-server.service` starts or stops. The icon updates instantly when systemd transitions the service state. `nvidia-smi` is called on a 5-second timer *only while the server is running* — when stopped, no GPU calls are made so the dGPU can enter D3cold (power off) freely.

Left-click calls `systemctl --user stop/start llama-server` — not `kill` — so systemd's `Restart=on-failure` doesn't fight against you.

## Requirements

- Linux, KDE Plasma 6 (or any desktop supporting StatusNotifierItem)
- Python 3.10+
- PyQt6 — `python-pyqt6` (Arch/CachyOS) or `python3-pyqt6` (Debian/Ubuntu)
- `llama-server.service` set up as a systemd user service
- NVIDIA GPU with `nvidia-smi` in PATH

## Install

```bash
git clone https://github.com/radical89/aget-state-tray.git
cd aget-state-tray
bash install.sh
```

The tray icon will appear within a few seconds.

## Uninstall

```bash
bash uninstall.sh
```

## llama-server.service setup

The tray expects `~/.config/systemd/user/llama-server.service`. Example unit for llama.cpp with MTP speculative decoding:

```ini
[Unit]
Description=llama.cpp server (Qwen3.6-27B MTP)
After=network.target

[Service]
ExecStart=/home/user/llama-mtp/build/bin/llama-server \
    --model /home/user/models/qwen3.6-27b-mtp/model.gguf \
    --n-gpu-layers 99 \
    --ctx-size 16384 \
    --spec-type draft-mtp \
    --spec-draft-n-max 5 \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    --host 0.0.0.0 \
    --port 8080 \
    --parallel 1
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

Enable it:
```bash
systemctl --user enable --now llama-server
```

## Source

`aget_state_tray.py`:

```python
#!/usr/bin/env python3
"""aget-state-tray — llama-server state indicator for the system tray."""

import subprocess
import sys

from PyQt6.QtCore import Qt, QObject, QRect, QTimer, pyqtSlot
from PyQt6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

UNIT_SERVICE = "org.freedesktop.systemd1"
UNIT_PATH = "/org/freedesktop/systemd1/unit/llama_2dserver_2eservice"
UNIT_IFACE = "org.freedesktop.systemd1.Unit"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

ICON_SIZE = 22
COLOR_RUNNING = QColor("#4CAF50")
COLOR_STOPPED = QColor("#888888")
VRAM_POLL_MS = 5_000


def parse_vram(output: str) -> tuple[float, float] | None:
    """Parse nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits output.
    Returns (used_gb, total_gb) or None on any failure."""
    try:
        line = output.strip().splitlines()[0] if output.strip() else ""
        if not line:
            return None
        parts = line.split(",")
        if len(parts) != 2:
            return None
        used = float(parts[0].strip())
        total = float(parts[1].strip())
        return used / 1024, total / 1024
    except (ValueError, IndexError):
        return None


def read_vram() -> tuple[float, float] | None:
    """Query nvidia-smi for VRAM usage. Returns (used_gb, total_gb) or None."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2,
        )
        return parse_vram(result.stdout)
    except (subprocess.SubprocessError, OSError):
        return None


def make_icon(color: QColor, top: str = "", bottom: str = "") -> QIcon:
    """Draw a 22×22 rounded-rect icon with optional two-line centred white label."""
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(color)
    painter.setPen(QColor(0, 0, 0, 60))
    painter.drawRoundedRect(1, 1, ICON_SIZE - 2, ICON_SIZE - 2, 4, 4)
    if top or bottom:
        painter.setPen(QColor("white"))
        font = QFont()
        font.setPixelSize(7)
        font.setBold(True)
        painter.setFont(font)
        if top and bottom:
            painter.drawText(QRect(0, 2, ICON_SIZE, 10),
                             Qt.AlignmentFlag.AlignHCenter, top)
            painter.drawText(QRect(0, 11, ICON_SIZE, 10),
                             Qt.AlignmentFlag.AlignHCenter, bottom)
        else:
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, top or bottom)
    painter.end()
    return QIcon(pixmap)


def toggle_server(is_running: bool) -> None:
    """Start or stop llama-server.service via systemctl --user."""
    action = "stop" if is_running else "start"
    subprocess.Popen(["systemctl", "--user", action, "llama-server"])


def get_active_state(bus: QDBusConnection) -> str:
    """Read the current ActiveState of llama-server.service from systemd D-Bus.
    Returns 'active', 'inactive', 'activating', 'deactivating', or 'inactive' on error."""
    iface = QDBusInterface(UNIT_SERVICE, UNIT_PATH, PROPS_IFACE, bus)
    reply = iface.call("Get", UNIT_IFACE, "ActiveState")
    if reply.type() == QDBusMessage.MessageType.ReplyMessage:
        args = reply.arguments()
        if args:
            val = args[0]
            return str(val.variant()) if hasattr(val, "variant") else str(val)
    return "inactive"


class AgetStateTray(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self._is_running = False

        self.tray = QSystemTrayIcon()
        menu = QMenu()
        menu.addAction("Quit", self.app.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

        self.vram_timer = QTimer()
        self.vram_timer.setInterval(VRAM_POLL_MS)
        self.vram_timer.timeout.connect(self._update_vram)

        bus = QDBusConnection.sessionBus()
        bus.connect(
            UNIT_SERVICE, UNIT_PATH, PROPS_IFACE,
            "PropertiesChanged", self._on_properties_changed,
        )
        self._apply_state(get_active_state(bus) == "active")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            toggle_server(self._is_running)

    @pyqtSlot("QString", "QVariantMap", "QStringList")
    def _on_properties_changed(self, *args) -> None:
        # Re-read authoritative state rather than parsing the variant dict.
        # Fires only on actual systemd transitions — not a polling call.
        state = get_active_state(QDBusConnection.sessionBus())
        self._apply_state(state == "active")

    def _apply_state(self, is_running: bool) -> None:
        self._is_running = is_running
        if is_running:
            self.tray.setIcon(make_icon(COLOR_RUNNING, "AI", "..."))
            self.tray.setToolTip("llama-server · reading VRAM…")
            self._update_vram()
            self.vram_timer.start()
        else:
            self.vram_timer.stop()
            self.tray.setIcon(make_icon(COLOR_STOPPED, "AI"))
            self.tray.setToolTip("llama-server · stopped — click to start")

    def _update_vram(self) -> None:
        vram = read_vram()
        if vram:
            used, total = vram
            self.tray.setIcon(make_icon(COLOR_RUNNING, "AI", f"{used:.0f}G"))
            self.tray.setToolTip(
                f"llama-server · {used:.1f} GB / {total:.1f} GB VRAM — click to stop"
            )
        else:
            self.tray.setIcon(make_icon(COLOR_RUNNING, "AI"))
            self.tray.setToolTip("llama-server · running — click to stop")

    def run(self) -> int:
        return self.app.exec()


def main() -> None:
    tray = AgetStateTray()
    sys.exit(tray.run())


if __name__ == "__main__":
    main()
```

## Tested hardware

| Machine | GPU | Kernel | Distro | Status |
|---|---|---|---|---|
| Lenovo Legion Pro 7 Gen 10 (16IAX10H) | RTX 5080 Mobile | 7.0.11-1-cachyos | CachyOS | ✅ Working |

## Troubleshooting

**Grey icon but server is running:** D-Bus subscription may have failed. Check `journalctl --user -u aget-state-tray` for errors.

**Click does nothing:** Verify `llama-server.service` exists at `~/.config/systemd/user/llama-server.service` and is a valid unit.

**Service won't start:** Run `journalctl --user -u aget-state-tray` for details. Ensure PyQt6 is installed (`python3 -c "import PyQt6"`). Also verify CUDA libraries are present if your llama-server build requires them (`ldconfig -p | grep cudart`).

**Icon doesn't appear on boot:** Check `systemctl --user is-enabled aget-state-tray` — should return `enabled`. If not, run `systemctl --user enable aget-state-tray`.
