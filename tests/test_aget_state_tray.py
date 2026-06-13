import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aget_state_tray import unit_object_path


def test_unit_object_path_escapes_dash_and_dot():
    assert unit_object_path("llama-server.service") == (
        "/org/freedesktop/systemd1/unit/llama_2dserver_2eservice"
    )


from aget_state_tray import map_state, VisualState


@pytest.mark.parametrize("active,sub,expected", [
    ("active", "running", VisualState.RUNNING),
    ("inactive", "dead", VisualState.STOPPED),
    ("", "", VisualState.STOPPED),
    ("activating", "start", VisualState.TRANSITION),
    ("deactivating", "stop", VisualState.TRANSITION),
    ("reloading", "reload", VisualState.TRANSITION),
    ("failed", "failed", VisualState.FAILED),
    ("activating", "auto-restart", VisualState.FAILED),
])
def test_map_state(active, sub, expected):
    assert map_state(active, sub) == expected


from aget_state_tray import click_verb


@pytest.mark.parametrize("active,sub,expected", [
    ("active", "running", "stop"),
    ("inactive", "dead", "start"),
    ("activating", "start", None),         # transition: ignore clicks
    ("deactivating", "stop", None),
    ("activating", "auto-restart", "stop"),  # crash loop: kill it
    ("failed", "failed", "start"),           # clean failure: retry
])
def test_click_verb(active, sub, expected):
    assert click_verb(active, sub) == expected


from aget_state_tray import discover_models


def test_discover_models_finds_gguf_excludes_mmproj(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "model-q4.gguf").touch()
    (tmp_path / "a" / "mmproj-BF16.gguf").touch()
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "other.gguf").touch()
    (tmp_path / "notes.txt").touch()
    assert discover_models(tmp_path) == ["a/model-q4.gguf", "b/other.gguf"]


def test_discover_models_missing_dir_returns_empty(tmp_path):
    assert discover_models(tmp_path / "nope") == []


def test_discover_models_empty_dir_returns_empty(tmp_path):
    assert discover_models(tmp_path) == []


from aget_state_tray import load_config, compose_args, display_name, Config

SAMPLE_TOML = '''
models_dir = "~/models"

[defaults]
args = "--n-gpu-layers 99 --ctx-size 16384"

[models."qwen/q.gguf"]
args = "--spec-type draft-mtp"

[models."gem/g.gguf"]
args = "--mmproj /x/mmproj.gguf"
name = "Gemma (vision)"
'''


def test_load_config_parses_defaults_and_models(tmp_path):
    f = tmp_path / "models.toml"
    f.write_text(SAMPLE_TOML)
    cfg = load_config(f)
    assert cfg.models_dir == Path(os.path.expanduser("~/models"))
    assert cfg.default_args == "--n-gpu-layers 99 --ctx-size 16384"
    assert cfg.model_args["qwen/q.gguf"] == "--spec-type draft-mtp"
    assert cfg.model_names["gem/g.gguf"] == "Gemma (vision)"


def test_load_config_missing_file_returns_default(tmp_path):
    cfg = load_config(tmp_path / "absent.toml")
    assert isinstance(cfg, Config)
    assert cfg.default_args == ""


def test_load_config_malformed_returns_default(tmp_path):
    f = tmp_path / "bad.toml"
    f.write_text("this is = = not toml")
    cfg = load_config(f)
    assert cfg.default_args == ""


def test_load_config_wrong_types_return_default(tmp_path):
    # Valid TOML, wrong shapes: must fall back rather than crash on startup.
    f = tmp_path / "wrong.toml"
    f.write_text('models_dir = 42\ndefaults = "not a table"\n')
    cfg = load_config(f)
    assert cfg.models_dir == Path(os.path.expanduser("~/models"))
    assert cfg.default_args == ""


def test_compose_args_empty_defaults_and_extras_returns_empty(tmp_path):
    cfg = Config(models_dir=tmp_path)
    assert compose_args(cfg, "x.gguf") == ""


def test_compose_args_appends_per_model_to_defaults(tmp_path):
    f = tmp_path / "models.toml"
    f.write_text(SAMPLE_TOML)
    cfg = load_config(f)
    assert compose_args(cfg, "qwen/q.gguf") == (
        "--n-gpu-layers 99 --ctx-size 16384 --spec-type draft-mtp"
    )


def test_compose_args_unlisted_model_gets_defaults_only(tmp_path):
    f = tmp_path / "models.toml"
    f.write_text(SAMPLE_TOML)
    cfg = load_config(f)
    assert compose_args(cfg, "unknown/x.gguf") == "--n-gpu-layers 99 --ctx-size 16384"


def test_display_name_override_and_fallback(tmp_path):
    f = tmp_path / "models.toml"
    f.write_text(SAMPLE_TOML)
    cfg = load_config(f)
    assert display_name(cfg, "gem/g.gguf") == "Gemma (vision)"
    assert display_name(cfg, "qwen/q.gguf") == "q"


from aget_state_tray import render_env, parse_env, write_env, current_model


def test_env_round_trip():
    text = render_env("/m/model.gguf", "--ctx-size 16384 --port 8080")
    model, args = parse_env(text)
    assert model == "/m/model.gguf"
    assert args == "--ctx-size 16384 --port 8080"


def test_parse_env_ignores_blank_and_unknown_lines():
    model, args = parse_env("# comment\nLLAMA_MODEL=/x.gguf\n\nFOO=bar\nLLAMA_ARGS=--a\n")
    assert model == "/x.gguf"
    assert args == "--a"


def test_write_env_creates_dir_and_file(tmp_path):
    target = tmp_path / "sub" / "current.env"
    write_env(target, "/m/x.gguf", "--port 8080")
    assert target.exists()
    assert current_model(target) == "/m/x.gguf"


def test_current_model_missing_file_returns_empty(tmp_path):
    assert current_model(tmp_path / "absent.env") == ""


from aget_state_tray import parse_vram, read_vram


def test_parse_vram_valid():
    used, total = parse_vram("14634, 16303\n")
    assert used == pytest.approx(14634 / 1024, rel=1e-3)
    assert total == pytest.approx(16303 / 1024, rel=1e-3)


@pytest.mark.parametrize("text", ["", "[N/A], [N/A]\n", "not a number\n", "14634\n"])
def test_parse_vram_bad_returns_none(text):
    assert parse_vram(text) is None


def test_read_vram_returns_tuple():
    mock = MagicMock()
    mock.stdout = "14634, 16303\n"
    with patch("aget_state_tray.subprocess.run", return_value=mock):
        assert read_vram() is not None


def test_read_vram_smi_missing_returns_none():
    with patch("aget_state_tray.subprocess.run", side_effect=FileNotFoundError):
        assert read_vram() is None


def test_read_vram_timeout_returns_none():
    with patch("aget_state_tray.subprocess.run",
               side_effect=subprocess.TimeoutExpired("nvidia-smi", 2)):
        assert read_vram() is None


from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from aget_state_tray import make_icon


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.mark.parametrize("state", list(VisualState))
def test_make_icon_each_state_non_null(qapp, state):
    icon = make_icon(state, "AI", "!")
    assert isinstance(icon, QIcon)
    assert not icon.isNull()


def test_make_icon_single_line(qapp):
    assert not make_icon(VisualState.STOPPED, "AI").isNull()


def test_make_icon_no_label(qapp):
    assert not make_icon(VisualState.RUNNING).isNull()


from aget_state_tray import get_unit_state, systemctl_run, Tray


def test_get_unit_state_reads_active_and_sub(qapp):
    from PyQt6.QtDBus import QDBusConnection, QDBusMessage

    def make_reply(value):
        r = MagicMock()
        r.type.return_value = QDBusMessage.MessageType.ReplyMessage
        r.arguments.return_value = [value]
        return r

    mock_iface = MagicMock()
    mock_iface.call.side_effect = [make_reply("active"), make_reply("running")]
    with patch("aget_state_tray.QDBusInterface", return_value=mock_iface):
        active, sub = get_unit_state(QDBusConnection.sessionBus())
    assert (active, sub) == ("active", "running")


def test_get_unit_state_dbus_error_returns_empty(qapp):
    from PyQt6.QtDBus import QDBusConnection, QDBusMessage
    mock_iface = MagicMock()
    err = MagicMock()
    err.type.return_value = QDBusMessage.MessageType.ErrorMessage
    mock_iface.call.return_value = err
    with patch("aget_state_tray.QDBusInterface", return_value=mock_iface):
        assert get_unit_state(QDBusConnection.sessionBus()) == ("", "")


def test_systemctl_run_invokes_no_block():
    with patch("aget_state_tray.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr="")
        systemctl_run("stop")
    run.assert_called_once_with(
        ["systemctl", "--user", "--no-block", "stop", "llama-server.service"],
        capture_output=True, text=True, timeout=5,
    )


def _make_tray(qapp):
    with patch("aget_state_tray.get_unit_state", return_value=("inactive", "dead")), \
         patch.object(Tray, "_subscribe"), \
         patch("aget_state_tray.QDBusConnection"):
        return Tray()


def test_tray_running_starts_timer(qapp):
    tray = _make_tray(qapp)
    with patch("aget_state_tray.read_vram", return_value=(14.3, 15.9)), \
         patch("aget_state_tray.Tray._current_display_name", return_value="m"):
        tray._apply_state(VisualState.RUNNING)
    assert tray.vram_timer.isActive()
    tray.app.quit()


def test_tray_stopped_stops_timer(qapp):
    tray = _make_tray(qapp)
    tray._apply_state(VisualState.STOPPED)
    assert not tray.vram_timer.isActive()
    tray.app.quit()


def test_tray_click_running_issues_stop(qapp):
    from PyQt6.QtWidgets import QSystemTrayIcon
    tray = _make_tray(qapp)
    with patch("aget_state_tray.get_unit_state", return_value=("active", "running")), \
         patch("aget_state_tray.systemctl_run") as run:
        tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
    run.assert_called_once_with("stop")
    tray.app.quit()


def test_tray_click_transition_ignored(qapp):
    from PyQt6.QtWidgets import QSystemTrayIcon
    tray = _make_tray(qapp)
    with patch("aget_state_tray.get_unit_state", return_value=("activating", "start")), \
         patch("aget_state_tray.systemctl_run") as run:
        tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
    run.assert_not_called()
    tray.app.quit()
