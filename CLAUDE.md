# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```sh
# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_updaters.py

# Run a single test
pytest tests/test_updaters.py::test_brew_is_only_sequential

# Run the CLI
update-all --help
update-all --only BREW,NPM
update-all --skip OMZ --jobs 4
update-all --force         # override daily idempotency guard
update-all --background    # log-only mode, no OS updates
```

## Architecture

The project is a macOS package manager updater with a daily idempotency guard. It runs update commands across all installed tools on the machine.

**Execution flow:**
1. `cli.py` parses flags, builds the updater list from `updaters.py`, splits it into sequential vs parallel groups
2. Sequential updaters run first via `runner.run_sequential()` (streams output live)
3. Parallel updaters run concurrently via `runner.run_parallel()` (captures output, shows live spinner, prints at end)
4. macOS `softwareupdate` runs last if `--os` was passed (requires sudo, uses `sudo.SudoKeepalive` to keep credentials valid)
5. On success, `idempotency.mark_ran_today()` writes today's ISO date to `~/.cache/update-all/last-run`

**Key types:**
- `Updater` (`updaters.py`): dataclass holding a `label`, `commands` (shell strings), a `check` callable (returns bool — whether the tool is present), `is_sequential` flag, and `description`
- `JobResult` (`runner.py`): dataclass with `label`, `exit_code`, `output`, `duration`, `succeeded`

**Updater catalog** (`updaters.py::all_updaters`): BREW (sequential), MAS, NPM, PNPM, YARN, PIPX, RUST, CARGO, ASDF, MISE, VSCODE, CLAUDE, OMZ. BREW is the only sequential updater; all others run in parallel.

**LaunchAgent** (`agent.py`): installs a plist under `~/Library/LaunchAgents/` that runs `update-all --background` every hour. The daily idempotency check ensures it only does real work once per day.

All shell commands run under `bash -lc` to pick up the user's full login PATH.
