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
