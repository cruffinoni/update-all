"""Shared command availability and version metadata."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass

NVM_PREFIX = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1; '


def _nvm_command_available(executable: str) -> bool:
    """Return whether an executable resolves after loading NVM."""
    result = subprocess.run(
        ["bash", "-lc", f"{NVM_PREFIX} command -v {shlex.quote(executable)}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


@dataclass(frozen=True)
class CommandSpec:
    """Describe a command that may be available on selected platforms."""

    executable: str
    version_args: tuple[str, ...] = ()
    supported_platforms: frozenset[str] | None = None
    use_login_shell: bool = False

    def available(self) -> bool:
        """Return whether this command is supported and discoverable on PATH."""
        if self.supported_platforms is not None and sys.platform not in self.supported_platforms:
            return False
        if self.use_login_shell:
            return _nvm_command_available(self.executable)
        return shutil.which(self.executable) is not None

    def version_command(self) -> list[str]:
        """Return the command used to print this tool's version."""
        command = [self.executable, *self.version_args]
        if self.use_login_shell:
            return ["bash", "-lc", f"{NVM_PREFIX}{shlex.join(command)}"]
        return command


COMMAND_SPECS = {
    "brew": CommandSpec("brew", ("--version",)),
    "apt": CommandSpec("apt"),
    "snap": CommandSpec("snap"),
    "flatpak": CommandSpec("flatpak"),
    "mas": CommandSpec("mas", supported_platforms=frozenset({"darwin"})),
    "softwareupdate": CommandSpec("softwareupdate", supported_platforms=frozenset({"darwin"})),
    "npm": CommandSpec("npm", ("-v",), use_login_shell=True),
    "pnpm": CommandSpec("pnpm", ("-v",), use_login_shell=True),
    "yarn": CommandSpec("yarn", ("-v",), use_login_shell=True),
    "pipx": CommandSpec("pipx"),
    "rustup": CommandSpec("rustup"),
    "cargo-install-update": CommandSpec("cargo-install-update"),
    "asdf": CommandSpec("asdf"),
    "mise": CommandSpec("mise"),
    "hermes": CommandSpec("hermes"),
    "claude": CommandSpec("claude", ("--version",)),
    "code": CommandSpec(
        "code",
        ("--version",),
        supported_platforms=frozenset({"darwin"}),
    ),
}


VERSION_COMMANDS = (
    COMMAND_SPECS["brew"],
    CommandSpec("node", ("-v",)),
    COMMAND_SPECS["npm"],
    COMMAND_SPECS["pnpm"],
    COMMAND_SPECS["yarn"],
    CommandSpec("rustc", ("-V",)),
    CommandSpec("go", ("version",)),
    CommandSpec("python3", ("--version",)),
    COMMAND_SPECS["code"],
    COMMAND_SPECS["claude"],
)
