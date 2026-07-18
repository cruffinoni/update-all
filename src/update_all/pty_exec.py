"""Bootstrap a command with a supplied PTY as its controlling terminal."""

from __future__ import annotations

import fcntl
import os
import sys
import termios


def main() -> None:
    slave_path, cmd = sys.argv[1:]
    os.setsid()
    slave = os.open(slave_path, os.O_RDWR)
    fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
    os.dup2(slave, 0)
    os.dup2(slave, 1)
    os.dup2(slave, 2)
    if slave > 2:
        os.close(slave)
    os.execvpe("bash", ["bash", "-lc", cmd], os.environ)


if __name__ == "__main__":
    main()
