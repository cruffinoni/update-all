"""Idempotency helpers for update-all.

Tracks whether the tool has already run within the last 24 hours using a sentinel file.
"""

import time
from pathlib import Path

SENTINEL = Path.home() / ".cache" / "update-all" / "last-run"
THRESHOLD_SECONDS = 24 * 3600


def _now() -> float:
    return time.time()


def last_ran_at() -> float | None:
    """Return the Unix timestamp of the last run, or None if unavailable."""
    try:
        return float(SENTINEL.read_text().strip())
    except (OSError, ValueError):
        return None


def already_ran_today() -> bool:
    """Return True if the sentinel file records a run within the last 24 hours."""
    stored = last_ran_at()
    return stored is not None and (_now() - stored) < THRESHOLD_SECONDS


def mark_ran_today() -> None:
    """Write the current Unix timestamp to the sentinel file atomically."""
    SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    tmp = SENTINEL.with_suffix(".tmp")
    tmp.write_text(str(_now()))
    tmp.replace(SENTINEL)
