"""Tests for update_all.self_update helpers."""

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

import update_all.self_update as self_update


@pytest.fixture(autouse=True)
def declined_path(monkeypatch, tmp_path):
    path = tmp_path / "declined-version"
    monkeypatch.setattr(self_update, "DECLINED_PATH", path)
    return path


@pytest.mark.parametrize(
    ("candidate", "current", "expected"),
    [
        ("2.0.10", "2.0.9", True),
        ("2.1.0", "2.0.10", True),
        ("3.0", "2.9.9", True),
        ("2.0.10", "2.0.10", False),
        ("2.0.9", "2.0.10", False),
        ("2.1.0rc1", "2.0.10", False),
        ("garbage", "2.0.10", False),
    ],
)
def test_is_newer(candidate, current, expected):
    assert self_update.is_newer(candidate, current) is expected


def test_latest_version_reads_pypi_payload():
    payload = io.BytesIO(json.dumps({"info": {"version": "2.1.0"}}).encode())
    with patch("update_all.self_update.urllib.request.urlopen", return_value=payload) as urlopen:
        assert self_update.latest_version() == "2.1.0"
    assert urlopen.call_args.args[0] == self_update.PYPI_URL


def test_latest_version_returns_none_on_network_error():
    with patch(
        "update_all.self_update.urllib.request.urlopen",
        side_effect=urllib.error.URLError("offline"),
    ):
        assert self_update.latest_version() is None


def test_latest_version_returns_none_on_bad_json():
    with patch("update_all.self_update.urllib.request.urlopen", return_value=io.BytesIO(b"not json")):
        assert self_update.latest_version() is None


def test_latest_version_returns_none_on_missing_key():
    with patch("update_all.self_update.urllib.request.urlopen", return_value=io.BytesIO(b"{}")):
        assert self_update.latest_version() is None


def test_declined_version_absent():
    assert self_update.declined_version() is None


def test_mark_declined_round_trip(declined_path):
    self_update.mark_declined("2.1.0")
    assert declined_path.read_text() == "2.1.0"
    assert self_update.declined_version() == "2.1.0"
