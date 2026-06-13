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
