"""Helpers for detecting and tracking newer update-all releases on PyPI."""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

PYPI_URL = "https://pypi.org/pypi/update-all/json"
DECLINED_PATH = Path.home() / ".cache" / "update-all" / "declined-version"
# Set before re-exec so a stale resolver cache cannot loop prompt -> install -> relaunch.
SKIP_ENV = "UPDATE_ALL_NO_SELF_UPDATE"

_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


def latest_version(timeout: float = 2.0) -> str | None:
    """Return the latest version published on PyPI, or None if it cannot be fetched."""
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=timeout) as response:
            return str(json.load(response)["info"]["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _parse(version: str) -> tuple[int, ...] | None:
    if not _VERSION_RE.match(version):
        return None
    return tuple(int(part) for part in version.split("."))


def is_newer(candidate: str, current: str) -> bool:
    """Return True if candidate is a plain release strictly newer than current."""
    cand, cur = _parse(candidate), _parse(current)
    return cand is not None and cur is not None and cand > cur


def declined_version() -> str | None:
    try:
        return DECLINED_PATH.read_text().strip() or None
    except OSError:
        return None


def mark_declined(version: str) -> None:
    DECLINED_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DECLINED_PATH.with_suffix(".tmp")
    tmp.write_text(version)
    tmp.replace(DECLINED_PATH)
