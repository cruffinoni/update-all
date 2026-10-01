"""Bootstrap a command with a supplied PTY as its controlling terminal."""

from __future__ import annotations

import fcntl
import os
import sys
import termios

EX_TEMPFAIL = 75


def main() -> None:
    status_arg, slave_path, cmd = sys.argv[1:]
    status_fd = int(status_arg)
    os.setsid()
    slave = os.open(slave_path, os.O_RDWR)
    try:
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
    except OSError as exc:
        # EPERM here means the kernel still binds this PTY to another session;
        # the parent retries on a fresh one, so report instead of crashing.
        os.write(status_fd, str(exc.errno).encode())
        os.write(2, f"update-all: cannot make {slave_path} the controlling terminal (errno {exc.errno})\n".encode())
        os._exit(EX_TEMPFAIL)
    os.dup2(slave, 0)
    os.dup2(slave, 1)
    os.dup2(slave, 2)
    if slave > 2:
        os.close(slave)
    # Closing on exec gives the parent EOF, signalling the bootstrap succeeded.
    os.set_inheritable(status_fd, False)
    os.execvpe("bash", ["bash", "-lc", cmd], os.environ)


if __name__ == "__main__":
    main()
