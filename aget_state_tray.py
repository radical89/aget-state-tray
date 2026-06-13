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


def discover_models(models_dir: Path) -> list[str]:
    """Return sorted POSIX-relative paths of *.gguf files under models_dir,
    excluding multimodal projector files (mmproj*). Missing dir -> []."""
    if not models_dir.is_dir():
        return []
    found = [
        p.relative_to(models_dir).as_posix()
        for p in models_dir.rglob("*.gguf")
        if not p.name.startswith("mmproj")
    ]
    return sorted(found)


@dataclass
class Config:
    models_dir: Path
    default_args: str = ""
    model_args: dict[str, str] = field(default_factory=dict)
    model_names: dict[str, str] = field(default_factory=dict)


def load_config(path: Path) -> Config:
    """Parse models.toml. On any read/parse error, log and return a Config
    pointing at ~/models with empty defaults (the app stays usable)."""
    fallback = Config(models_dir=Path(os.path.expanduser("~/models")))
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"aget-state-tray: cannot read {path}: {exc}", file=sys.stderr)
        return fallback
    models_dir = Path(os.path.expanduser(data.get("models_dir", "~/models")))
    default_args = data.get("defaults", {}).get("args", "")
    model_args: dict[str, str] = {}
    model_names: dict[str, str] = {}
    for rel, entry in data.get("models", {}).items():
        if isinstance(entry, dict):
            if "args" in entry:
                model_args[rel] = entry["args"]
            if "name" in entry:
                model_names[rel] = entry["name"]
    return Config(models_dir, default_args, model_args, model_names)


def compose_args(config: Config, rel_path: str) -> str:
    """Full llama-server arg string: defaults followed by per-model extras."""
    extra = config.model_args.get(rel_path, "")
    return f"{config.default_args} {extra}".strip()


def display_name(config: Config, rel_path: str) -> str:
    """Menu label: explicit name override, else filename without .gguf."""
    return config.model_names.get(rel_path) or Path(rel_path).name.removesuffix(".gguf")


def render_env(model_abs: str, args: str) -> str:
    """Render the EnvironmentFile systemd reads at service start."""
    return f"LLAMA_MODEL={model_abs}\nLLAMA_ARGS={args}\n"


def parse_env(text: str) -> tuple[str, str]:
    """Extract (model, args) from a current.env body. Missing keys -> ''."""
    model = ""
    args = ""
    for line in text.splitlines():
        if line.startswith("LLAMA_MODEL="):
            model = line[len("LLAMA_MODEL="):]
        elif line.startswith("LLAMA_ARGS="):
            args = line[len("LLAMA_ARGS="):]
    return model, args


def write_env(path: Path, model_abs: str, args: str) -> None:
    """Atomically write current.env (temp file + rename), creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(render_env(model_abs, args))
    tmp.replace(path)


def current_model(path: Path) -> str:
    """The currently selected absolute model path, or '' if unreadable."""
    try:
        model, _ = parse_env(path.read_text())
        return model
    except OSError:
        return ""


def parse_vram(output: str) -> tuple[float, float] | None:
    """Parse 'used, total' (MiB) from nvidia-smi CSV; return (used_gb, total_gb)."""
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
    except ValueError:
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


STATE_COLOR = {
    VisualState.RUNNING: QColor("#4CAF50"),
    VisualState.STOPPED: QColor("#888888"),
    VisualState.TRANSITION: QColor("#FF9800"),
    VisualState.FAILED: QColor("#F44336"),
}


def make_icon(state: VisualState, top: str = "", bottom: str = "") -> QIcon:
    """Draw a 64x64 rounded-rect icon coloured per state, with up to two
    centred white text lines. Rendered large so HiDPI hosts downscale cleanly."""
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(STATE_COLOR[state])
    painter.setPen(QColor(0, 0, 0, 60))
    painter.drawRoundedRect(2, 2, ICON_SIZE - 4, ICON_SIZE - 4, 12, 12)
    if top or bottom:
        painter.setPen(QColor("white"))
        font = QFont()
        font.setBold(True)
        if top and bottom:
            font.setPixelSize(20)
            painter.setFont(font)
            painter.drawText(QRect(0, 6, ICON_SIZE, 28),
                             Qt.AlignmentFlag.AlignHCenter, top)
            painter.drawText(QRect(0, 32, ICON_SIZE, 28),
                             Qt.AlignmentFlag.AlignHCenter, bottom)
        else:
            font.setPixelSize(28)
            painter.setFont(font)
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, top or bottom)
    painter.end()
    return QIcon(pixmap)
