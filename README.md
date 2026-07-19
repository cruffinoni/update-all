# update-all

`update-all` is a small macOS and Linux CLI that updates the package managers and developer tools installed on your machine.

It skips tools that are not installed, runs independent updates in parallel, and keeps system updates in a sequential pass.

## Install

Production install with `uv`:

```bash
uv tool install update-all@latest --force --python 3.11
```

Editable development install:

```bash
pip install -e ".[dev]"
```

## Usage

```bash
update-all
update-all --os
update-all --only BREW,NPM
update-all --skip CLAUDE
update-all --jobs 4
update-all --force
update-all update
update-all logs
```

Useful options:

| Option | Description |
| --- | --- |
| `--os` | Include macOS or Linux system updates. |
| `--only LABELS` | Run only the comma-separated updater labels. |
| `--skip LABELS` | Skip the comma-separated updater labels. |
| `--jobs N` | Set the maximum number of parallel workers. |
| `--force` | Ignore the once-per-day idempotency check. |
| `--background` | Run without interactive output, skip OS updates, and log to a file. |
| `--install-agent` | Install a LaunchAgent on macOS or a systemd timer on Linux. |
| `--uninstall-agent` | Remove the background scheduler. |
| `update` | Update `update-all` itself from PyPI using `uv`. |
| `logs` | Display the latest background-run log. |

## Updates performed

Each updater runs only when its tool is available.

| Label | Tool | Commands |
| --- | --- | --- |
| `BREW` | Homebrew formulae and casks | `brew update`; `brew upgrade`; macOS: `brew upgrade --cask --greedy`; `brew autoremove`; `brew cleanup --prune=all`; `brew doctor` |
| `APT` | APT system packages | `sudo apt update`; `sudo apt full-upgrade -y`; `sudo apt autoremove -y`; `sudo apt clean` |
| `SNAP` | Snap packages | `sudo snap refresh` |
| `FLATPAK` | Flatpak packages | `flatpak update -y` |
| `MAS` | Mac App Store | `mas upgrade` |
| `NPM` | Global npm packages | `npm update -g` |
| `PNPM` | Global pnpm packages | `pnpm update -g` |
| `YARN` | Global Yarn v1 packages | `yarn global upgrade` |
| `PIPX` | pipx packages | `pipx upgrade-all --include-injected` |
| `RUST` | Rust toolchain | `rustup self update && rustup update` |
| `CARGO` | Cargo-installed binaries | `cargo install-update -a` |
| `ASDF` | asdf plugins | `asdf update && asdf plugin-update --all` |
| `MISE` | mise toolchain | `mise self-update -y && mise upgrade -y` |
| `HERMES` | Hermes Agent CLI | `hermes update` |
| `CLAUDE` | Claude CLI | `claude update` |
| `OMZ` | Oh My Zsh | Run Oh My Zsh's upgrade script, falling back to `git pull --rebase --autostash` |

With `--os`, the additional system commands are:

- macOS: `sudo softwareupdate -l` and `sudo softwareupdate -ia --verbose`
- Linux: `sudo apt full-upgrade -y` and `sudo apt autoremove -y`
