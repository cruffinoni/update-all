"""End-to-end tests for the installed update-all command."""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import re
import select
import stat
import subprocess
import sys
import termios
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _environment(tmp_path: Path, *commands: tuple[str, str]) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, script in commands:
        _write_executable(fake_bin / name, script)

    home = tmp_path / "home"
    home.mkdir()
    path = f"{fake_bin}:/usr/bin:/bin"
    (home / ".bash_profile").write_text(f"export PATH={path}\n")

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": path,
            "PYTHONPATH": str(PROJECT_ROOT / "src"),
            "TERM": "xterm-256color",
            "LC_ALL": "C",
        }
    )
    return env


def _run_cli(
    env: dict[str, str],
    *args: str,
    password: str | None = None,
) -> subprocess.CompletedProcess[str]:
    master, slave = pty.openpty()

    def set_controlling_tty() -> None:
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    process = subprocess.Popen(
        [sys.executable, "-c", "from update_all.cli import main; raise SystemExit(main())", *args],
        cwd=PROJECT_ROOT,
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
        preexec_fn=set_controlling_tty,
    )
    os.close(slave)

    output: list[bytes] = []
    password_sent = False
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], min(0.1, deadline - time.monotonic()))
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    raise
                if chunk:
                    output.append(chunk)
                    if password is not None and not password_sent:
                        captured = b"".join(output).decode("utf-8", "replace")
                        if "sudo password:" in captured:
                            os.write(master, (password + "\n").encode())
                            password_sent = True
            elif process.poll() is not None:
                break
        else:
            process.kill()
            process.wait()
            raise TimeoutError("update-all E2E process timed out")
        returncode = process.wait(timeout=15)
    finally:
        os.close(master)

    return subprocess.CompletedProcess(
        process.args,
        returncode,
        stdout=b"".join(output).decode("utf-8", "replace"),
        stderr="",
    )


def _visible_output(output: str) -> str:
    """Remove terminal styling/control sequences while retaining rendered text."""
    return ANSI_ESCAPE.sub("", output).replace("\r", "")


def test_e2e_apt_streams_progress_and_reports_success(tmp_path: Path):
    env = _environment(
        tmp_path,
        (
            "sudo",
            """#!/bin/sh
if [ "$1" = "-v" ]; then
    exit 0
fi
printf '[sudo] password for test: ' >/dev/tty
read password </dev/tty
[ "$password" = "test-password" ] || exit 1
exec "$@"
""",
        ),
        (
            "apt",
            """#!/bin/sh
case "$1" in
    update)
        printf 'apt progress 1\\r'
        sleep 0.2
        printf 'apt progress 2\\r'
        printf 'Fetched package lists\\n'
        sleep 0.4
        ;;
    full-upgrade)
        printf '3 upgraded, 0 newly installed\\n'
        sleep 0.2
        ;;
    autoremove)
        printf 'No packages to remove\\n'
        ;;
    clean)
        printf 'Cleaned package cache\\n'
        ;;
esac
""",
        ),
        ("notify-send", "#!/bin/sh\nexit 0\n"),
    )

    result = _run_cli(
        env,
        "--only",
        "APT",
        "--os",
        "--force",
        "--no-colors",
        password="test-password",
    )
    output = _visible_output(result.stdout)

    assert result.returncode == 0, output + result.stderr
    assert output.count("sudo password:") == 1
    assert "$ sudo apt update" in output
    assert "[sudo] password requested — supplying cached credential" in output
    assert "apt progress 1" in output
    assert "apt progress 2" in output
    assert "$ sudo apt full-upgrade -y" in output
    assert "3 upgraded" in output
    assert "2 succeeded" in output


def test_e2e_brew_prompt_is_visible_and_auto_confirmed(tmp_path: Path):
    env = _environment(
        tmp_path,
        (
            "brew",
            """#!/bin/sh
case "$1" in
    --version)
        printf 'Homebrew 0.0.0\\n'
        ;;
    update)
        printf 'brew update complete\\n'
        ;;
    upgrade)
        printf 'Proceed? [y/N] '
        read answer
        printf 'received=%s\\n' "$answer"
        sleep 0.4
        ;;
    autoremove)
        printf 'brew autoremove complete\\n'
        ;;
    cleanup)
        printf 'brew cleanup complete\\n'
        ;;
    doctor)
        printf 'Your system is ready to brew.\\n'
        ;;
esac
""",
        ),
        ("notify-send", "#!/bin/sh\nexit 0\n"),
    )

    result = _run_cli(env, "--only", "BREW", "--force", "--no-colors")
    output = _visible_output(result.stdout)

    assert result.returncode == 0, output + result.stderr
    assert "Proceed? [y/N]" in output
    assert "auto-answered: y" in output
    assert "received=y" in output
    assert "1 succeeded" in output
