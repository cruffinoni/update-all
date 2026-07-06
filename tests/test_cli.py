"""Tests for the update_all.cli logs subcommand and summary helpers."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

import update_all.agent as agent_module
from update_all.cli import _extract_notes, app
from update_all.runner import JobResult

runner = CliRunner()


@pytest.fixture(autouse=True)
def patch_log_path(monkeypatch, tmp_path):
    log_path = tmp_path / "update-all.log"
    monkeypatch.setattr(agent_module, "LOG_PATH", log_path)
    return log_path


def test_logs_no_file_macos():
    with patch("update_all.cli.sys") as mock_sys:
        mock_sys.platform = "darwin"
        result = runner.invoke(app, ["logs"])
    assert result.exit_code == 1
    assert "LaunchAgent" in result.output
    assert "--install-agent" in result.output


def test_logs_no_file_linux():
    with patch("update_all.cli.sys") as mock_sys:
        mock_sys.platform = "linux"
        result = runner.invoke(app, ["logs"])
    assert result.exit_code == 1
    assert "systemd timer" in result.output
    assert "--install-agent" in result.output


def test_logs_empty_file(patch_log_path):
    patch_log_path.write_text("")
    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0
    assert "log file is empty" in result.output


def test_logs_with_content(patch_log_path):
    patch_log_path.write_text("brew update\nbrew upgrade\n")
    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0
    assert "brew update" in result.output
    assert "brew upgrade" in result.output


def test_extract_notes_no_output_returns_dash():
    result = JobResult(label="BREW", exit_code=0, output="", duration=10.0, succeeded=True)
    assert _extract_notes(result) == "—"


def test_extract_notes_apt_parses_upgraded_count():
    result = JobResult(
        label="APT", exit_code=0,
        output="3 upgraded, 0 newly installed", duration=5.0, succeeded=True,
    )
    assert _extract_notes(result) == "3 upgraded"


def test_extract_notes_npm_parses_changed_count():
    result = JobResult(
        label="NPM", exit_code=0,
        output="changed 3 packages in 5s", duration=5.0, succeeded=True,
    )
    assert _extract_notes(result) == "3 packages changed"


def test_extract_notes_fallback_counts_lines():
    result = JobResult(
        label="VSCODE", exit_code=0,
        output="Installing ms-python\nInstalled ms-python",
        duration=8.0, succeeded=True,
    )
    assert _extract_notes(result) == "2 lines"


def test_extract_notes_brew_formulae_and_casks():
    result = JobResult(
        label="BREW", exit_code=0,
        output="Upgrading 3 formulae\nUpgrading 1 cask", duration=60.0, succeeded=True,
    )
    assert _extract_notes(result) == "3 formulae, 1 cask"


def test_extract_notes_pipx_counts_upgraded():
    result = JobResult(
        label="PIPX", exit_code=0,
        output="upgraded ruff\nupgraded black\nskipped mypy",
        duration=10.0, succeeded=True,
    )
    assert _extract_notes(result) == "2 packages upgraded"


def test_extract_notes_failed_job_shows_error_line():
    result = JobResult(
        label="CARGO", exit_code=1,
        output="Updating registry\nerror: crate 'foo' not found\naborting",
        duration=5.0, succeeded=False,
    )
    notes = _extract_notes(result)
    assert "error:" in notes
