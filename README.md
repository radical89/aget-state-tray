# aget-state-tray

A lightweight system tray indicator for Linux showing whether your llama.cpp inference server is running, with live VRAM usage display. Left-click to start or stop the server instantly.

| State | Icon | Meaning |
|---|---|---|
| Running | Green `AI` + VRAM (e.g. `14G`) | llama-server active, model loaded (plain green `AI` with no number if `nvidia-smi` is unavailable) |
| Stopped | Grey `AI` | llama-server stopped, VRAM free |
| Transition | Orange `AI` + `…` | Service is starting or stopping (click ignored) |
| Failed | Red `AI` + `!` | Service failed or is in a crash loop |

Built for gaming and AI workflows where you want to free GPU VRAM for games without opening a terminal. One click stops the inference server; one click starts it again.

## How it works

Uses D-Bus event subscription (not polling) to detect when `llama-server.service` starts or stops. The icon updates instantly when systemd transitions the service state. `nvidia-smi` is called on a 5-second timer only while the server is running. When stopped, no GPU calls are made so the dGPU can enter D3cold (power off) freely.

Left-click calls `systemctl --user stop` or `start` on the service, not `kill`, so systemd's `Restart=on-failure` does not fight against you. Clicks during a transition are silently ignored. The failed (red) state splits on cause: a crash loop (SubState `auto-restart`) issues `stop` to break the loop, while a cleanly failed service issues `start` to retry it.

All events and errors are written to the journal. To inspect them:

```bash
journalctl --user -u aget-state-tray -n 50 --no-pager
```

## Model picker

Right-click the tray icon to open the context menu. The menu shows:

- The current service state and VRAM usage (or loaded model name) as a disabled title line.
- A checkable list of every `.gguf` file found under `models_dir` (multimodal projector files starting with `mmproj` are excluded). The currently loaded model is checked.
- Start/Stop and Quit actions.

Selecting a model writes the new selection to `~/.config/llama-server/current.env` and restarts the service when it is running or in a crash loop, so the new model takes effect immediately. When the server is stopped the selection is staged and loads on the next start. The menu re-scans `models_dir` every time it opens, so newly downloaded models appear automatically without restarting the tray.

## Requirements

- Linux, KDE Plasma 6 (or any desktop supporting StatusNotifierItem)
- Python 3.10+ with PyQt6 (`python-pyqt6` on Arch/CachyOS, `python3-pyqt6` on Debian/Ubuntu)
- NVIDIA GPU with `nvidia-smi` in PATH (VRAM display only; the tray works without it)

## Install

```bash
git clone https://github.com/radical89/aget-state-tray.git
cd aget-state-tray
bash install.sh
```

`install.sh` copies the binary and unit files, seeds `~/.config/llama-server/models.toml` and `current.env` if they do not already exist, migrates the `WantedBy` symlink from `default.target` to `graphical-session.target`, and restarts the service. Any existing `llama-server.service` is backed up with a timestamp before being overwritten.

## Uninstall

```bash
bash uninstall.sh
```

This removes the tray binary, unit file, and desktop file. It leaves `llama-server.service` and `~/.config/llama-server/` untouched so your model configuration and the inference server are preserved.

## Configuration

### models.toml

After install, edit `~/.config/llama-server/models.toml` to point at your models directory and add any per-model arguments:

```toml
models_dir = "~/models"

[defaults]
args = "--n-gpu-layers 99 --ctx-size 16384 --cache-type-k q8_0 --cache-type-v q8_0 --host 0.0.0.0 --port 8080 --parallel 1"

[models."qwen3.6-27b-mtp/Qwen3.6-27B-IQ3_M-mtp.gguf"]
args = "--spec-type draft-mtp --spec-draft-n-max 5"

[models."qwopus-9b-mtp/Qwopus3.5-9B-Coder-MTP-Q4_K_M.gguf"]
args = "--spec-type draft-mtp --spec-draft-n-max 5"

[models."gemma-4-12b/gemma-4-12b-it-UD-Q4_K_XL.gguf"]
args = "--mmproj /home/karlos/models/gemma-4-12b/mmproj-BF16.gguf"
name = "Gemma 4 12B (vision)"
```

Keys under `[defaults]` apply to every model. Keys under `[models."rel/path.gguf"]` are appended after the defaults for that model only. The optional `name` key overrides the display label in the picker menu; without it the filename without `.gguf` is used.

The `models_dir` path supports `~` expansion. Model paths in the menu are relative to this directory. Paths inside a per-model `args` string (such as `--mmproj`) are passed to llama-server verbatim with no shell, so they must be absolute: `~` and `$HOME` are not expanded there.

### current.env

`~/.config/llama-server/current.env` is written by the tray whenever you pick a model. You can also edit it manually. The format is:

```
LLAMA_MODEL=/home/karlos/models/gemma-4-12b/gemma-4-12b-it-UD-Q4_K_XL.gguf
LLAMA_ARGS=--mmproj /home/karlos/models/gemma-4-12b/mmproj-BF16.gguf
```

`llama-server.service` reads this file via `EnvironmentFile` at start time, so the variables are available as `${LLAMA_MODEL}` and `$LLAMA_ARGS` in the `ExecStart` line:

```ini
[Service]
EnvironmentFile=-%h/.config/llama-server/current.env
ExecStart=%h/llama-mtp/build/bin/llama-server --model ${LLAMA_MODEL} $LLAMA_ARGS
```

The leading dash on `EnvironmentFile` makes it optional, so a missing `current.env` produces a clear llama-server error rather than a hard systemd failure. The `${LLAMA_MODEL}` braces force single-word expansion (paths with spaces stay intact) while bare `$LLAMA_ARGS` is word-split into separate flags.

Switching models from the tray writes the new `current.env` and issues `systemctl --user restart llama-server`, so the server picks up the change immediately.

## Tested hardware

| Machine | GPU | Kernel | Distro | Status |
|---|---|---|---|---|
| Lenovo Legion Pro 7 Gen 10 (16IAX10H) | RTX 5080 Mobile | 7.0.11-1-cachyos | CachyOS | Working |

## Troubleshooting

**Grey icon but server is running.** The D-Bus subscription may have failed. Check the journal:

```bash
journalctl --user -u aget-state-tray -n 50 --no-pager
```

Look for lines containing `Subscribe failed` or `failed to connect PropertiesChanged signal`. If the session bus is not connected you will see `session bus not connected` there too.

**Click does nothing.** Verify that `llama-server.service` exists at `~/.config/systemd/user/llama-server.service` and is a valid unit. Also check whether the click landed during a transition state (orange icon), in which case it is intentionally ignored.

**No models in the right-click menu.** Check that `models_dir` in `~/.config/llama-server/models.toml` is correct and that `.gguf` files exist under it. The tray scans recursively but skips files whose names start with `mmproj`.

**Service fails to start.** Run `journalctl --user -u llama-server -n 50 --no-pager` to see llama-server output. Common causes: `current.env` references a model path that does not exist, or the `llama-server` binary path in the unit file is wrong.

**Icon does not appear on boot.** Check that the service is enabled for the right target:

```bash
systemctl --user is-enabled aget-state-tray
```

It should report `enabled`. If not, run `systemctl --user enable aget-state-tray`. If it was previously enabled against `default.target`, re-running `install.sh` will migrate the symlink to `graphical-session.target`.

**Crash loop after login.** A crash loop (systemd SubState `auto-restart`) shows as a red icon. Left-click issues a stop to break the loop. Then check the journal for the underlying error.

**Tray gone after clicking Quit.** The tray unit is bound to the graphical session and only auto-restarts on failure, so a clean Quit leaves it stopped until your next login. Bring it back with `systemctl --user start aget-state-tray`.

## Source

See `aget_state_tray.py`.
