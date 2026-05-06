"""Notification helpers for update-all."""

import subprocess
import sys


def send(title: str, message: str, *, success: bool) -> None:
    """Send a native notification via osascript (macOS) or notify-send (Linux)."""
    if sys.platform == "darwin":
        sound = "Glass" if success else "Basso"
        script = (
            "on run argv\n"
            "  display notification (item 2 of argv) "
            "with title (item 1 of argv) "
            f'sound name "{sound}"\n'
            "end run"
        )
        try:
            subprocess.run(["osascript", "-e", script, "--", title, message], check=False)
        except FileNotFoundError:
            pass
    elif sys.platform.startswith("linux"):
        try:
            subprocess.run(["notify-send", title, message], check=False)
        except FileNotFoundError:
            pass
