"""Sudo keepalive helper for update-all.

Maintains a live sudo timestamp in a background thread so long-running
update operations are not interrupted by credential expiry.
"""

import subprocess
import threading


class SudoKeepalive:
    """Keeps the sudo timestamp alive by running sudo -v at a regular interval."""

    def __init__(self, interval: float = 60) -> None:
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Refresh the sudo timestamp synchronously, then start the background keepalive thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        subprocess.run(["sudo", "-v"], check=True)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the background thread to exit and wait for it to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self) -> "SudoKeepalive":
        """Start the keepalive and return self for use as a context manager."""
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        """Stop the keepalive when exiting the context."""
        self.stop()

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            # Never prompt from the daemon thread: Rich's live dashboard owns
            # the terminal, and a hidden sudo prompt would make updates appear
            # hung. The foreground updater PTY handles any visible re-prompt.
            subprocess.run(["sudo", "-n", "-v"], check=False)
