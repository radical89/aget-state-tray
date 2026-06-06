#!/usr/bin/env python3
"""aget-state-tray — llama-server state indicator for the system tray."""

import subprocess
import sys

from PyQt6.QtCore import Qt, QRect, QTimer
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


def main() -> None:
    pass


if __name__ == "__main__":
    main()
