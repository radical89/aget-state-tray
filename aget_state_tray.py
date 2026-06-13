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
    except (OSError, tomllib.TOMLDecodeError, TypeError, AttributeError) as exc:
        print(f"aget-state-tray: cannot read {path}: {exc}", file=sys.stderr)
        return fallback
    return Config(models_dir, default_args, model_args, model_names)


def compose_args(config: Config, rel_path: str) -> str:
    """Full llama-server arg string: defaults followed by per-model extras."""
    extra = config.model_args.get(rel_path, "")
    return " ".join(p for p in (config.default_args.strip(), extra.strip()) if p)


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


_STATE_GLYPH = {
    VisualState.STOPPED: "",
    VisualState.TRANSITION: "…",
    VisualState.FAILED: "!",
}
_STATE_TOOLTIP = {
    VisualState.STOPPED: "llama-server · stopped — click to start",
    VisualState.TRANSITION: "llama-server · changing state…",
    VisualState.FAILED: "llama-server · failed — click to retry/stop",
}


def _get_prop(iface: QDBusInterface, name: str) -> str:
    reply = iface.call("Get", UNIT_IFACE, name)
    if reply.type() == QDBusMessage.MessageType.ReplyMessage:
        args = reply.arguments()
        if args:
            val = args[0]
            return str(val.variant()) if hasattr(val, "variant") else str(val)
    return ""


def get_unit_state(bus: QDBusConnection) -> tuple[str, str]:
    """Read (ActiveState, SubState) of llama-server.service via D-Bus.
    Returns ('', '') on error, which map_state treats as STOPPED."""
    iface = QDBusInterface(MANAGER_SERVICE, unit_object_path(UNIT_NAME),
                           PROPS_IFACE, bus)
    return _get_prop(iface, "ActiveState"), _get_prop(iface, "SubState")


def systemctl_run(verb: str) -> None:
    """Run `systemctl --user --no-block <verb> llama-server.service`.
    Non-zero exit or failure to spawn is logged to stderr (journald)."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "--no-block", verb, UNIT_NAME],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            print(f"aget-state-tray: systemctl {verb} failed: "
                  f"{result.stderr.strip()}", file=sys.stderr)
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"aget-state-tray: systemctl {verb} error: {exc}", file=sys.stderr)


def _relative_to(models_dir: Path, model_abs: str) -> str:
    """POSIX path of model_abs relative to models_dir, or bare filename if
    it lives elsewhere."""
    try:
        return Path(model_abs).relative_to(models_dir).as_posix()
    except ValueError:
        return Path(model_abs).name


class Tray(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setDesktopFileName("aget-state-tray")
        self._state = VisualState.STOPPED

        self.tray = QSystemTrayIcon()
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self._rebuild_menu)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)

        self.vram_timer = QTimer()
        self.vram_timer.setInterval(VRAM_POLL_MS)
        self.vram_timer.timeout.connect(self._update_vram)

        self.bus = QDBusConnection.sessionBus()
        if not self.bus.isConnected():
            print("aget-state-tray: session bus not connected", file=sys.stderr)
        else:
            self._subscribe()

        active, sub = get_unit_state(self.bus)
        self._apply_state(map_state(active, sub))
        self.tray.show()  # after first icon is set — avoids "No Icon set" warning

    def _subscribe(self) -> None:
        """systemd only emits per-unit PropertiesChanged signals while at least
        one client holds a Manager.Subscribe() — without this the icon is stale
        on minimal desktops. Then connect the signal handler."""
        mgr = QDBusInterface(MANAGER_SERVICE, MANAGER_PATH, MANAGER_IFACE, self.bus)
        reply = mgr.call("Subscribe")
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            print(f"aget-state-tray: Subscribe failed: {reply.errorMessage()}",
                  file=sys.stderr)
        ok = self.bus.connect(
            MANAGER_SERVICE, unit_object_path(UNIT_NAME), PROPS_IFACE,
            "PropertiesChanged", self._on_properties_changed,
        )
        if not ok:
            print("aget-state-tray: failed to connect PropertiesChanged signal",
                  file=sys.stderr)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            active, sub = get_unit_state(self.bus)
            verb = click_verb(active, sub)
            if verb:
                systemctl_run(verb)

    @pyqtSlot("QString", "QVariantMap", "QStringList")
    def _on_properties_changed(self, *args) -> None:
        active, sub = get_unit_state(self.bus)
        self._apply_state(map_state(active, sub))

    def _apply_state(self, state: VisualState) -> None:
        self._state = state
        if state == VisualState.RUNNING:
            self.tray.setToolTip("llama-server · reading VRAM…")
            self._update_vram()
            self.vram_timer.start()
        else:
            self.vram_timer.stop()
            self.tray.setIcon(make_icon(state, "AI", _STATE_GLYPH[state]))
            self.tray.setToolTip(_STATE_TOOLTIP[state])

    def _current_display_name(self) -> str:
        config = load_config(MODELS_TOML)
        model_abs = current_model(CURRENT_ENV)
        if not model_abs:
            return "no model"
        rel = _relative_to(config.models_dir, model_abs)
        return display_name(config, rel)

    def _update_vram(self) -> None:
        name = self._current_display_name()
        vram = read_vram()
        if vram:
            used, total = vram
            self.tray.setIcon(make_icon(VisualState.RUNNING, "AI", f"{used:.0f}G"))
            self.tray.setToolTip(
                f"llama-server · {name} · {used:.1f} / {total:.1f} GB — click to stop"
            )
        else:
            self.tray.setIcon(make_icon(VisualState.RUNNING, "AI"))
            self.tray.setToolTip(f"llama-server · {name} · running — click to stop")

    def _rebuild_menu(self) -> None:
        pass  # implemented in Task 10

    def _select_model(self, rel: str) -> None:
        pass  # implemented in Task 10
