import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)
