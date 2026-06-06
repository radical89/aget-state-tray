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


def main() -> None:
    pass


if __name__ == "__main__":
    main()
