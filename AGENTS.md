# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Commands

```bash
# Install locally (production)
uv tool install . --force --python 3.11

# Editable dev install
pip install -e ".[dev]"

# Run tests
pytest

# Run a single test file
pytest tests/test_runner.py

# Run a single test
pytest tests/test_runner.py::test_run_sequential_success
```

No linter is configured in `pyproject.toml`.

## Architecture

`update-all` is a Python CLI tool that updates all package managers on a macOS or Linux developer machine in one command. Entry point: `src/update_all/cli.py` (Typer).

### Execution flow

1. **Idempotency check** (`idempotency.py`) — skip if a run happened within the last 24 hours
2. **`SudoKeepalive`** (`sudo.py`) — refreshes `sudo -v` every 60s in a daemon thread (only when `--os` flag is set)
3. **Updater catalog** (`updaters.py`) — `all_updaters()` returns 16 `Updater` dataclasses; CLI filters by `--only`/`--skip`
4. **Sequential runners** (`runner.py`) — `run_sequential()` streams output live; used for Homebrew, APT, and OS updates
5. **Parallel runner** (`runner.py`) — `run_parallel()` runs the rest concurrently via `ThreadPoolExecutor`, shows a `rich.live.Live` progress panel
6. **Notification** (`notify.py`) — `osascript` on macOS, `notify-send` on Linux

### Key design decisions

- Each updater command runs through `bash -lc <cmd>` (login shell) to pick up the user's PATH
- **Background mode** (`--background`): disables color, skips OS updates, rewrites `sudo <cmd>` → `sudo -n <cmd>` so unattended runs never hang
- `Updater.is_sequential = True` forces a tool to run in the sequential pass (before the parallel pool)
- `Updater.needs_sudo = True` participates in the `SudoKeepalive` keepalive

### Background scheduling (`agent.py`)

- **macOS**: writes a `.plist` to `~/Library/LaunchAgents/` and bootstraps it via `launchctl`
- **Linux**: writes a systemd `.service` + `.timer` to `~/.config/systemd/user/` and enables it with `systemctl --user`
- Both use `update-all --background` and log to a platform-appropriate path

### Module responsibilities

| Module | Responsibility |
|---|---|
| `cli.py` | Typer CLI, flag parsing, `--install-agent`/`--uninstall-agent`, `logs` subcommand |
| `updaters.py` | Catalog of all 16 `Updater` dataclasses |
| `runner.py` | `run_sequential` and `run_parallel` execution engines |
| `agent.py` | Background scheduler install/uninstall |
| `idempotency.py` | 24-hour sentinel at `~/.cache/update-all/last-run` |
| `notify.py` | Native OS notifications |
| `sudo.py` | `SudoKeepalive` daemon thread |
