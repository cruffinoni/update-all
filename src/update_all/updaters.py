"""Catalog of system updaters run by update-all."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from update_all.responder import PromptResponder

# nvm hooks into interactive shells only, so a bare `bash -lc` never sees it.
# Sourcing nvm.sh puts the active node/npm/pnpm/yarn on PATH for these commands.
_NVM = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1; '


def _tool_available(name: str) -> bool:
    """True if ``name`` resolves in a login shell with nvm sourced."""
    result = subprocess.run(
        ["bash", "-lc", f"{_NVM} command -v {name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


@dataclass
class Updater:
    """Represents a single upgrade step with its precondition check."""

    label: str
    commands: list[str]
    check: Callable[[], bool]
    is_sequential: bool = False
    needs_sudo: bool = False
    description: str = ""
    error_lines: int = 20
    responder: PromptResponder | None = None


def _yarn_v1_present() -> bool:
    if not _tool_available("yarn"):
        return False
    try:
        result = subprocess.run(
            ["bash", "-lc", f"{_NVM} yarn --version"], capture_output=True, text=True, check=False
        )
        major = int(result.stdout.strip().split(".")[0])
        return major == 1
    except (ValueError, IndexError):
        return False


def _cargo_install_update_present() -> bool:
    return shutil.which("cargo-install-update") is not None


def _brew_commands() -> list[str]:
    base = ["brew update", "brew upgrade"]
    if sys.platform == "darwin":
        base.append("brew upgrade --cask --greedy")
    base += ["brew autoremove", "brew cleanup --prune=all", "brew doctor || true"]
    return base


def all_updaters() -> list[Updater]:
    """Return the full catalog of updaters in execution order."""
    return [
        Updater(
            label="BREW",
            description="Homebrew formulae & casks",
            check=lambda: shutil.which("brew") is not None,
            is_sequential=True,
            commands=_brew_commands(),
            error_lines=30,
            responder=PromptResponder(),
        ),
        Updater(
            label="APT",
            description="APT system packages",
            check=lambda: shutil.which("apt") is not None,
            is_sequential=True,
            needs_sudo=True,
            commands=[
                "sudo apt update",
                "sudo apt full-upgrade -y",
                "sudo apt autoremove -y",
                "sudo apt clean",
            ],
            error_lines=20,
        ),
        Updater(
            label="SNAP",
            description="Snap packages",
            check=lambda: shutil.which("snap") is not None,
            needs_sudo=True,
            commands=["sudo snap refresh"],
            error_lines=15,
        ),
        Updater(
            label="FLATPAK",
            description="Flatpak packages",
            check=lambda: shutil.which("flatpak") is not None,
            commands=["flatpak update -y"],
            error_lines=15,
        ),
        Updater(
            label="MAS",
            description="Mac App Store",
            check=lambda: shutil.which("mas") is not None,
            commands=["mas upgrade"],
            error_lines=10,
        ),
        Updater(
            label="NPM",
            description="npm global packages",
            check=lambda: _tool_available("npm"),
            commands=[f"{_NVM} npm update -g"],
            error_lines=20,
        ),
        Updater(
            label="PNPM",
            description="pnpm global packages",
            check=lambda: _tool_available("pnpm"),
            commands=[f"{_NVM} pnpm update -g"],
            error_lines=10,
        ),
        Updater(
            label="YARN",
            description="Yarn global packages",
            check=_yarn_v1_present,
            commands=[f"{_NVM} yarn global upgrade"],
            error_lines=15,
        ),
        Updater(
            label="PIPX",
            description="pipx packages",
            check=lambda: shutil.which("pipx") is not None,
            commands=["pipx upgrade-all --include-injected"],
            error_lines=25,
        ),
        Updater(
            label="RUST",
            description="Rust toolchain (rustup)",
            check=lambda: shutil.which("rustup") is not None,
            commands=["rustup self update && rustup update"],
            error_lines=15,
        ),
        Updater(
            label="CARGO",
            description="Cargo-installed binaries",
            check=_cargo_install_update_present,
            commands=["cargo install-update -a"],
            error_lines=30,
        ),
        Updater(
            label="ASDF",
            description="asdf plugins",
            check=lambda: shutil.which("asdf") is not None,
            commands=["asdf update && asdf plugin-update --all"],
            error_lines=15,
        ),
        Updater(
            label="MISE",
            description="mise toolchain",
            check=lambda: shutil.which("mise") is not None,
            commands=["mise self-update -y && mise upgrade -y"],
            error_lines=10,
        ),
        Updater(
            label="VSCODE",
            description="VS Code extensions",
            check=lambda: shutil.which("code") is not None,
            commands=[
                'code --list-extensions | while read -r ext; do [ -n "$ext" ] && code --install-extension "$ext" --force; done'
            ],
            error_lines=15,
        ),
        Updater(
            label="CLAUDE",
            description="Claude CLI",
            check=lambda: shutil.which("claude") is not None,
            commands=["claude update"],
            error_lines=10,
        ),
        Updater(
            label="OMZ",
            description="Oh My Zsh",
            check=lambda: Path.home().joinpath(".oh-my-zsh").is_dir(),
            commands=[
                'RUNZSH=no CHSH=no KEEP_ZSHRC=yes env ZSH="$HOME/.oh-my-zsh" sh "$HOME/.oh-my-zsh/tools/upgrade.sh" || git -C "$HOME/.oh-my-zsh" pull --rebase --autostash'
            ],
            error_lines=15,
        ),
    ]
