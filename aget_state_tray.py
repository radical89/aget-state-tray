#!/usr/bin/env python3
"""aget-state-tray — llama-server state indicator with model picker."""

import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PyQt6.QtCore import Qt, QObject, QRect, QTimer, pyqtSlot
from PyQt6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
from PyQt6.QtGui import QActionGroup, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

UNIT_NAME = "llama-server.service"
MANAGER_SERVICE = "org.freedesktop.systemd1"
MANAGER_PATH = "/org/freedesktop/systemd1"
MANAGER_IFACE = "org.freedesktop.systemd1.Manager"
UNIT_IFACE = "org.freedesktop.systemd1.Unit"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

CONFIG_DIR = Path.home() / ".config" / "llama-server"
MODELS_TOML = CONFIG_DIR / "models.toml"
CURRENT_ENV = CONFIG_DIR / "current.env"

ICON_SIZE = 64
VRAM_POLL_MS = 5_000


class VisualState(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    TRANSITION = "transition"
    FAILED = "failed"


def unit_object_path(unit_name: str) -> str:
    """Escape a systemd unit name into its D-Bus object path.
    Each non-alphanumeric char becomes _<2-digit-lowercase-hex>."""
    escaped = "".join(c if c.isalnum() else f"_{ord(c):02x}" for c in unit_name)
    return f"/org/freedesktop/systemd1/unit/{escaped}"


def map_state(active: str, sub: str) -> VisualState:
    """Collapse systemd (ActiveState, SubState) into a visual state.
    'activating' with SubState 'auto-restart' is a crash loop, shown as FAILED."""
    if active == "active":
        return VisualState.RUNNING
    if active == "failed":
        return VisualState.FAILED
    if active == "activating" and sub == "auto-restart":
        return VisualState.FAILED
    if active in ("activating", "deactivating", "reloading"):
        return VisualState.TRANSITION
    return VisualState.STOPPED


def click_verb(active: str, sub: str) -> str | None:
    """The systemctl verb a left-click should run, or None to ignore the click.
    Takes raw (active, sub) because FAILED splits on SubState: a crash loop
    (auto-restart) is stopped, a clean failure is (re)started."""
    state = map_state(active, sub)
    if state == VisualState.RUNNING:
        return "stop"
    if state == VisualState.STOPPED:
        return "start"
    if state == VisualState.TRANSITION:
        return None
    return "stop" if sub == "auto-restart" else "start"
