import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from aget_state_tray import parse_vram


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
