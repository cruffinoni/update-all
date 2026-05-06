"""Tests for update_all.idempotency."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time

import update_all.idempotency as idempotency_module
from update_all.idempotency import already_ran_today, mark_ran_today

BASE_TIME = 1_700_000_000.0
BASE_TIME_STR = "2023-11-14 22:13:20"


@pytest.fixture(autouse=True)
def patch_sentinel(monkeypatch, tmp_path):
    sentinel = tmp_path / "last-run"
    monkeypatch.setattr(idempotency_module, "SENTINEL", sentinel)
    return sentinel


def test_already_ran_today_no_sentinel():
    assert already_ran_today() is False


def test_already_ran_today_recent(patch_sentinel):
    patch_sentinel.write_text(str(BASE_TIME - 3600))
    with freeze_time(BASE_TIME_STR):
        assert already_ran_today() is True


def test_already_ran_today_stale(patch_sentinel):
    patch_sentinel.write_text(str(BASE_TIME - 13 * 3600))
    with freeze_time(BASE_TIME_STR):
        assert already_ran_today() is False


def test_already_ran_today_boundary(patch_sentinel):
    patch_sentinel.write_text(str(BASE_TIME - 12 * 3600))
    with freeze_time(BASE_TIME_STR):
        assert already_ran_today() is False


def test_already_ran_today_corrupt_sentinel(patch_sentinel):
    patch_sentinel.write_text("not-a-float")
    assert already_ran_today() is False


def test_already_ran_today_oserror(monkeypatch):
    mock_path = MagicMock(spec=Path)
    mock_path.read_text.side_effect = OSError("permission denied")
    monkeypatch.setattr(idempotency_module, "SENTINEL", mock_path)
    assert already_ran_today() is False


def test_mark_ran_today_creates_sentinel(patch_sentinel):
    with freeze_time(BASE_TIME_STR):
        mark_ran_today()
    assert patch_sentinel.exists()
    assert float(patch_sentinel.read_text().strip()) == BASE_TIME


def test_mark_ran_today_creates_parent_dirs(tmp_path, monkeypatch):
    deep_sentinel = tmp_path / "a" / "b" / "c" / "last-run"
    monkeypatch.setattr(idempotency_module, "SENTINEL", deep_sentinel)
    mark_ran_today()
    assert deep_sentinel.exists()
    assert float(deep_sentinel.read_text().strip()) > 0


def test_mark_ran_today_atomic_no_tmp_leftover(patch_sentinel):
    mark_ran_today()
    assert not patch_sentinel.with_suffix(".tmp").exists()
    assert patch_sentinel.exists()
