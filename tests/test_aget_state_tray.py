import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from aget_state_tray import parse_vram, read_vram, make_icon, COLOR_RUNNING, COLOR_STOPPED, toggle_server, get_active_state, AgetStateTray


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_parse_vram_valid():
    result = parse_vram("14634, 16303\n")
    assert result is not None
    used, total = result
    assert used == pytest.approx(14634 / 1024, rel=1e-3)
    assert total == pytest.approx(16303 / 1024, rel=1e-3)


def test_parse_vram_empty_returns_none():
    assert parse_vram("") is None


def test_parse_vram_na_returns_none():
    assert parse_vram("[N/A], [N/A]\n") is None


def test_parse_vram_bad_format_returns_none():
    assert parse_vram("not a number\n") is None


def test_parse_vram_single_value_returns_none():
    assert parse_vram("14634\n") is None


def test_read_vram_returns_tuple():
    mock = MagicMock()
    mock.stdout = "14634, 16303\n"
    with patch("aget_state_tray.subprocess.run", return_value=mock):
        result = read_vram()
    assert result is not None
    used, total = result
    assert used == pytest.approx(14634 / 1024, rel=1e-3)


def test_read_vram_smi_missing_returns_none():
    with patch("aget_state_tray.subprocess.run", side_effect=FileNotFoundError):
        assert read_vram() is None


def test_read_vram_timeout_returns_none():
    with patch("aget_state_tray.subprocess.run",
               side_effect=subprocess.TimeoutExpired("nvidia-smi", 2)):
        assert read_vram() is None


def test_make_icon_stopped_returns_qicon(qapp):
    icon = make_icon(COLOR_STOPPED, "AI")
    assert isinstance(icon, QIcon)
    assert not icon.isNull()


def test_make_icon_running_two_line_returns_qicon(qapp):
    icon = make_icon(COLOR_RUNNING, "AI", "14G")
    assert isinstance(icon, QIcon)
    assert not icon.isNull()


def test_make_icon_no_label_returns_qicon(qapp):
    icon = make_icon(COLOR_RUNNING)
    assert isinstance(icon, QIcon)
    assert not icon.isNull()


def test_toggle_server_stop_when_running():
    with patch("aget_state_tray.subprocess.Popen") as mock_popen:
        toggle_server(is_running=True)
    mock_popen.assert_called_once_with(
        ["systemctl", "--user", "stop", "llama-server"]
    )


def test_toggle_server_start_when_stopped():
    with patch("aget_state_tray.subprocess.Popen") as mock_popen:
        toggle_server(is_running=False)
    mock_popen.assert_called_once_with(
        ["systemctl", "--user", "start", "llama-server"]
    )


def test_get_active_state_returns_string(qapp):
    from PyQt6.QtDBus import QDBusConnection, QDBusMessage
    mock_iface = MagicMock()
    mock_reply = MagicMock()
    mock_reply.type.return_value = QDBusMessage.MessageType.ReplyMessage
    mock_reply.arguments.return_value = ["active"]
    mock_iface.call.return_value = mock_reply
    with patch("aget_state_tray.QDBusInterface", return_value=mock_iface):
        result = get_active_state(QDBusConnection.sessionBus())
    assert result == "active"


def test_get_active_state_dbus_error_returns_inactive(qapp):
    from PyQt6.QtDBus import QDBusConnection, QDBusMessage
    mock_iface = MagicMock()
    mock_reply = MagicMock()
    mock_reply.type.return_value = QDBusMessage.MessageType.ErrorMessage
    mock_iface.call.return_value = mock_reply
    with patch("aget_state_tray.QDBusInterface", return_value=mock_iface):
        result = get_active_state(QDBusConnection.sessionBus())
    assert result == "inactive"


def test_apply_state_running_starts_timer(qapp):
    with patch("aget_state_tray.get_active_state", return_value="inactive"), \
         patch("aget_state_tray.QDBusConnection"):
        tray = AgetStateTray()
    with patch("aget_state_tray.read_vram", return_value=(14.3, 15.9)):
        tray._apply_state(True)
    assert tray.vram_timer.isActive()
    tray.app.quit()


def test_apply_state_stopped_stops_timer(qapp):
    with patch("aget_state_tray.get_active_state", return_value="inactive"), \
         patch("aget_state_tray.QDBusConnection"):
        tray = AgetStateTray()
    tray._apply_state(False)
    assert not tray.vram_timer.isActive()
    tray.app.quit()
