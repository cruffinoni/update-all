# update-all

`update-all` is a macOS and Linux CLI that updates the package managers and developer tools installed on your machine. It skips tools that are not installed, runs independent updates in parallel, and keeps system updates in a sequential pass. Some updaters require sudo depending on the packages being updated.

## Install

Install the latest GitHub Release binary:

```bash
curl -fsSL https://raw.githubusercontent.com/cruffinoni/update-all/main/install.sh | bash
```

The installer supports macOS and Linux on amd64 and arm64. Binaries and SHA-256 checksums are published on [GitHub Releases](https://github.com/cruffinoni/update-all/releases).

Build from a checkout:

```bash
go build -o update-all ./cmd/update-all
```

## Update

Run the built-in updater to fetch and verify the matching GitHub Release binary:

```bash
update-all update
```

In an interactive run, `update-all` asks before installing a newer release. Declining a version suppresses that prompt until a newer release is available. Use `update-all update` to update immediately.

## Usage

```bash
update-all
update-all --os
update-all --only BREW,NPM
update-all --skip CLAUDE
update-all --jobs 4
update-all update
```

| Option | Description |
| --- | --- |
| `--os` | Include macOS or Linux system updates; sudo may be required depending on the packages updated. |
| `--only LABELS` | Run only the comma-separated updater labels. |
| `--skip LABELS` | Skip the comma-separated updater labels. |
| `--jobs N` | Set the maximum number of parallel workers. |
| `--uninstall-agent` | Remove a scheduler installed by an earlier version. |
| `--version`, `-v` | Show the CLI version. |
| `update` | Update `update-all` from GitHub Releases. |

Use `update-all --help` for help and `update-all completion` to generate shell completion scripts. Options can also be set with environment variables using the `UPDATE_ALL_` prefix, for example `UPDATE_ALL_JOBS=4`. Explicit command-line flags take precedence. There is no config file.

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
| `TAILSCALE` | Tailscale | `sudo tailscale update` |
| `HERMES` | Hermes Agent CLI | `hermes update` |
| `CLAUDE` | Claude CLI | `claude update` |
| `OMZ` | Oh My Zsh | Run Oh My Zsh's upgrade script, falling back to `git pull --rebase --autostash` |

With `--os`, macOS runs `sudo softwareupdate -l` and `sudo softwareupdate -ia --verbose`. Linux runs `sudo apt full-upgrade -y` and `sudo apt autoremove -y`.

## Development

The CLI uses Cobra and Viper. The application is under `cmd/update-all` and responsibility-specific packages are under `internal/`.

```bash
go test ./...
go build ./cmd/update-all
```
