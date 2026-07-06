"""Scheduler install/uninstall for automatic update-all runs.

On macOS installs a LaunchAgent that fires every hour (StartInterval=3600).
On Linux installs a systemd user timer that fires every hour (OnUnitActiveSec=1h).
The idempotency check in update_all ensures at most one run per 12-hour window.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

PLIST_LABEL = "com.user.update-all"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.user.update-all.plist"

SERVICE_NAME = "update-all.service"
SERVICE_PATH = Path.home() / ".config" / "systemd" / "user" / "update-all.service"
TIMER_NAME = "update-all.timer"
TIMER_PATH = Path.home() / ".config" / "systemd" / "user" / "update-all.timer"

if sys.platform == "darwin":
    LOG_PATH = Path.home() / "Library" / "Logs" / "update-all.log"
else:
    LOG_PATH = Path.home() / ".local" / "share" / "update-all" / "update-all.log"


def _launch_path() -> str:
    """Build a PATH string for the LaunchAgent that covers common tool locations."""
    home = Path.home()
    dirs = [
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        str(home / ".cargo" / "bin"),
        str(home / ".local" / "bin"),
        str(home / ".pyenv" / "shims"),
        str(home / "go" / "bin"),
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    return ":".join(dirs)


def _systemd_path() -> str:
    """Build a PATH string for the systemd user service covering common tool locations."""
    home = Path.home()
    dirs = [
        "/home/linuxbrew/.linuxbrew/bin",
        "/home/linuxbrew/.linuxbrew/sbin",
        str(home / ".cargo" / "bin"),
        str(home / ".local" / "bin"),
        str(home / ".pyenv" / "shims"),
        str(home / "go" / "bin"),
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    return ":".join(dirs)


def install(console: Console) -> None:
    """Install the scheduler appropriate for the current platform."""
    if sys.platform == "darwin":
        _install_macos(console)
    else:
        _install_linux(console)


def uninstall(console: Console) -> None:
    """Uninstall the scheduler appropriate for the current platform."""
    if sys.platform == "darwin":
        _uninstall_macos(console)
    else:
        _uninstall_linux(console)


def _install_macos(console: Console) -> None:
    binary_path = shutil.which("update-all")
    if binary_path is None:
        binary_path = str(Path(sys.argv[0]).resolve())
        console.print("[yellow]Warning: 'update-all' not found in PATH; falling back to current executable.[/yellow]")

    plist: dict[str, Any] = {
        "Label": PLIST_LABEL,
        "ProgramArguments": [binary_path, "--background"],
        "RunAtLoad": True,
        "StartInterval": 3600,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
        "EnvironmentVariables": {
            "PATH": _launch_path(),
        },
    }

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    with PLIST_PATH.open("wb") as f:
        plistlib.dump(plist, f)

    domain = f"gui/{os.getuid()}"
    load_result = subprocess.run(["launchctl", "bootstrap", domain, str(PLIST_PATH)], check=False)
    if load_result.returncode == 5:
        # EALREADY — service is already loaded; plist was updated in place, re-enable it
        subprocess.run(["launchctl", "bootout", domain, str(PLIST_PATH)], check=False)
        load_result = subprocess.run(["launchctl", "bootstrap", domain, str(PLIST_PATH)], check=False)
    if load_result.returncode != 0:
        console.print(f"[red][ERR][/red] launchctl bootstrap failed (exit {load_result.returncode})")
        return

    console.print(f"[green]LaunchAgent installed: {PLIST_PATH}[/green]")
    console.print(
        "[yellow]Warning: Check ~/Library/Logs/update-all.log after first automatic run "
        "to verify PATH is correct for your setup.[/yellow]"
    )


def _uninstall_macos(console: Console) -> None:
    if not PLIST_PATH.exists():
        console.print("[yellow]Warning: LaunchAgent plist not found; nothing to uninstall.[/yellow]")
        return

    domain = f"gui/{os.getuid()}"
    unload_result = subprocess.run(["launchctl", "bootout", domain, str(PLIST_PATH)], check=False)
    if unload_result.returncode != 0:
        console.print(
            f"[yellow][WARN][/yellow] launchctl bootout failed (exit {unload_result.returncode}) — "
            "plist not deleted. The agent may still be loaded until next reboot."
        )
        return
    PLIST_PATH.unlink(missing_ok=True)

    console.print(f"[green]LaunchAgent uninstalled: {PLIST_PATH}[/green]")


def _install_linux(console: Console) -> None:
    binary_path = shutil.which("update-all")
    if binary_path is None:
        binary_path = str(Path(sys.argv[0]).resolve())
        console.print("[yellow]Warning: 'update-all' not found in PATH; falling back to current executable.[/yellow]")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    service_content = (
        "[Unit]\n"
        "Description=update-all automatic updater\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={binary_path} --background\n"
        f"StandardOutput=append:{LOG_PATH}\n"
        f"StandardError=append:{LOG_PATH}\n"
        f'Environment="PATH={_systemd_path()}"\n'
    )
    timer_content = (
        "[Unit]\n"
        "Description=Run update-all every hour\n"
        "\n"
        "[Timer]\n"
        "OnBootSec=5min\n"
        "OnUnitActiveSec=1h\n"
        "Persistent=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )

    SERVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SERVICE_PATH.write_text(service_content)
    TIMER_PATH.write_text(timer_content)

    reload_result = subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    if reload_result.returncode != 0:
        console.print(f"[red][ERR][/red] systemctl daemon-reload failed (exit {reload_result.returncode})")
        return

    enable_result = subprocess.run(["systemctl", "--user", "enable", "--now", TIMER_NAME], check=False)
    if enable_result.returncode != 0:
        console.print(f"[red][ERR][/red] systemctl enable failed (exit {enable_result.returncode})")
        return

    console.print(f"[green]systemd timer installed: {TIMER_PATH}[/green]")
    console.print(
        f"[yellow]Warning: Check {LOG_PATH} after first automatic run "
        "to verify PATH is correct for your setup.[/yellow]"
    )


def _uninstall_linux(console: Console) -> None:
    if not TIMER_PATH.exists() and not SERVICE_PATH.exists():
        console.print("[yellow]Warning: systemd unit files not found; nothing to uninstall.[/yellow]")
        return

    stop_result = subprocess.run(["systemctl", "--user", "disable", "--now", TIMER_NAME], check=False)
    if stop_result.returncode != 0:
        console.print(
            f"[yellow][WARN][/yellow] systemctl disable failed (exit {stop_result.returncode}) — "
            "unit files not deleted."
        )
        return

    TIMER_PATH.unlink(missing_ok=True)
    SERVICE_PATH.unlink(missing_ok=True)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)

    console.print(f"[green]systemd timer uninstalled: {TIMER_PATH}[/green]")
