"""Interactive sudo-password handling for update-all.

When a command blocks on a sudo password prompt mid-run, the ``PasswordBroker``
serializes the prompt across concurrent jobs (FIFO order), pauses the live
dashboard so it can own the terminal, shows the user a little context, reads the
password without echoing it, and caches it for the rest of the run.
"""

from __future__ import annotations

import getpass
import threading
from collections import deque
from contextlib import contextmanager
from typing import Callable, Iterator


class _FIFOLock:
    """A mutex that grants acquisition in strict arrival (FIFO) order.

    ``threading.Lock`` makes no ordering guarantee about which waiter wakes
    next; here prompts must appear in the order jobs asked for them.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._waiters: deque[threading.Event] = deque()
        self._held = False

    def acquire(self) -> None:
        with self._guard:
            if not self._held and not self._waiters:
                self._held = True
                return
            event = threading.Event()
            self._waiters.append(event)
        event.wait()

    def release(self) -> None:
        with self._guard:
            if self._waiters:
                self._waiters.popleft().set()  # hand off to the next in line
            else:
                self._held = False

    @contextmanager
    def __call__(self) -> Iterator[None]:
        self.acquire()
        try:
            yield
        finally:
            self.release()


@contextmanager
def _nullcontext() -> Iterator[None]:
    yield


class PasswordBroker:
    """Serializes sudo-password prompts across parallel jobs and caches the answer."""

    def __init__(
        self,
        *,
        pause: Callable[[], object] | None = None,
        prompt_fn: Callable[[list[str], bool], str] | None = None,
    ) -> None:
        self._lock = _FIFOLock()
        self._password: str | None = None
        self._pause = pause or _nullcontext
        self._prompt_fn = prompt_fn or self._default_prompt

    def get_password(self, context_lines: list[str], *, reprompt: bool) -> bytes:
        """Return ``<password>\\n`` bytes to write into the waiting pty.

        Only one caller prompts at a time; concurrent callers queue in FIFO
        order and reuse the cached password. ``reprompt=True`` (the previous
        attempt was rejected) invalidates the cache and re-asks.
        """
        with self._lock():
            if reprompt:
                self._password = None
            if self._password is None:
                with self._pause():
                    self._password = self._prompt_fn(context_lines, reprompt)
            return (self._password + "\n").encode()

    def has_cached_password(self) -> bool:
        """Return whether a password can be supplied without prompting the user."""
        with self._lock():
            return self._password is not None

    @staticmethod
    def _default_prompt(context_lines: list[str], reprompt: bool) -> str:
        with open("/dev/tty", "w") as tty:
            if reprompt:
                tty.write("  Sorry, try again.\n")
            for line in context_lines:
                tty.write(f"    {line}\n")
            tty.flush()
        return getpass.getpass("  sudo password: ")
