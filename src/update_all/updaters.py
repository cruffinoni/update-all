"""Catalog of system updaters run by update-all."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from update_all.commands import COMMAND_SPECS, NVM_PREFIX
from update_all.responder import PromptResponder

def _tool_available(name: str) -> bool:
    """True if an NVM-managed tool resolves in a login shell."""
    return COMMAND_SPECS[name].available()


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
            ["bash", "-lc", f"{NVM_PREFIX} yarn --version"], capture_output=True, text=True, check=False
        )
        major = int(result.stdout.strip().split(".")[0])
        return major == 1
    except (ValueError, IndexError):
        return False


def _cargo_install_update_present() -> bool:
    return COMMAND_SPECS["cargo-install-update"].available()


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
            check=COMMAND_SPECS["brew"].available,
            is_sequential=True,
            commands=_brew_commands(),
            error_lines=30,
            responder=PromptResponder(),
        ),
        Updater(
            label="APT",
            description="APT system packages",
            check=COMMAND_SPECS["apt"].available,
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
            check=COMMAND_SPECS["snap"].available,
            needs_sudo=True,
            commands=["sudo snap refresh"],
            error_lines=15,
        ),
        Updater(
            label="FLATPAK",
            description="Flatpak packages",
            check=COMMAND_SPECS["flatpak"].available,
            commands=["flatpak update -y"],
            error_lines=15,
        ),
        Updater(
            label="MAS",
            description="Mac App Store",
            check=COMMAND_SPECS["mas"].available,
            commands=["mas upgrade"],
            error_lines=10,
        ),
        Updater(
            label="NPM",
            description="npm global packages",
            check=lambda: _tool_available("npm"),
            commands=[f"{NVM_PREFIX} npm update -g"],
            error_lines=20,
        ),
        Updater(
            label="PNPM",
            description="pnpm global packages",
            check=lambda: _tool_available("pnpm"),
            commands=[f"{NVM_PREFIX} pnpm update -g"],
            error_lines=10,
        ),
        Updater(
            label="YARN",
            description="Yarn global packages",
            check=_yarn_v1_present,
            commands=[f"{NVM_PREFIX} yarn global upgrade"],
            error_lines=15,
        ),
        Updater(
            label="PIPX",
            description="pipx packages",
            check=COMMAND_SPECS["pipx"].available,
            commands=["pipx upgrade-all --include-injected"],
            error_lines=25,
        ),
        Updater(
            label="RUST",
            description="Rust toolchain (rustup)",
            check=COMMAND_SPECS["rustup"].available,
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
            check=COMMAND_SPECS["asdf"].available,
            commands=["asdf update && asdf plugin-update --all"],
            error_lines=15,
        ),
        Updater(
            label="MISE",
            description="mise toolchain",
            check=COMMAND_SPECS["mise"].available,
            commands=["mise self-update -y && mise upgrade -y"],
            error_lines=10,
        ),
        Updater(
            label="HERMES",
            description="Hermes Agent CLI",
            check=COMMAND_SPECS["hermes"].available,
            commands=["hermes update"],
            error_lines=15,
        ),
        Updater(
            label="CLAUDE",
            description="Claude CLI",
            check=COMMAND_SPECS["claude"].available,
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
