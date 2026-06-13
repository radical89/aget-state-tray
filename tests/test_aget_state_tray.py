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
