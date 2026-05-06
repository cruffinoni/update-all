"""Tests for the update_all.cli logs subcommand."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import update_all.agent as agent_module
from update_all.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def patch_log_path(monkeypatch, tmp_path):
    log_path = tmp_path / "update-all.log"
    monkeypatch.setattr(agent_module, "LOG_PATH", log_path)
    return log_path


def test_logs_no_file():
    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 1
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
