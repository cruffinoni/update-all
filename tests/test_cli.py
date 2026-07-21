"""Tests for the update_all.cli logs subcommand and summary helpers."""

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
from rich.console import Console
from typer.testing import CliRunner

import update_all.agent as agent_module
from update_all.cli import _extract_notes, _print_versions, app
from update_all import __version__
from update_all.runner import JobResult
from update_all.updaters import Updater

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


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"update-all {__version__}" in result.output


def test_help_includes_update_command():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "update" in result.output


def test_update_uses_uv_to_install_latest_pypi_package():
    with patch("update_all.cli.shutil.which", return_value="/usr/bin/uv"), \
         patch("update_all.cli.subprocess.run", return_value=CompletedProcess([], 0)) as run:
        result = runner.invoke(app, ["update"])

    assert result.exit_code == 0
    run.assert_called_once_with(
        ["/usr/bin/uv", "tool", "install", "update-all@latest", "--force"],
        check=False,
    )
    assert "updated successfully" in result.output


def test_update_requires_uv():
    with patch("update_all.cli.shutil.which", return_value=None), \
         patch("update_all.cli.subprocess.run") as run:
        result = runner.invoke(app, ["update"])

    assert result.exit_code == 1
    assert "uv is required" in result.output
    run.assert_not_called()


def test_update_propagates_uv_failure():
    with patch("update_all.cli.shutil.which", return_value="/usr/bin/uv"), \
         patch("update_all.cli.subprocess.run", return_value=CompletedProcess([], 7)):
        result = runner.invoke(app, ["update"])

    assert result.exit_code == 7


def test_update_does_not_run_normal_update_flow():
    with patch("update_all.cli.shutil.which", return_value="/usr/bin/uv"), \
         patch("update_all.cli.subprocess.run", return_value=CompletedProcess([], 0)), \
         patch("update_all.cli.all_updaters") as all_updaters, \
         patch("update_all.cli.idempotency.already_ran_today") as already_ran:
        result = runner.invoke(app, ["update"])

    assert result.exit_code == 0
    all_updaters.assert_not_called()
    already_ran.assert_not_called()


def test_run_excludes_os_updaters_without_os_flag():
    apt = Updater(
        label="APT",
        commands=["sudo apt update"],
        check=lambda: True,
        is_sequential=True,
        requires_os=True,
        needs_sudo=True,
    )
    npm = Updater(label="NPM", commands=["npm update -g"], check=lambda: True)

    with patch("update_all.cli.all_updaters", return_value=[apt, npm]), \
         patch("update_all.cli.run_sequential", return_value=[]) as run_sequential, \
         patch("update_all.cli.run_parallel", return_value=[]) as run_parallel, \
         patch("update_all.cli.idempotency.mark_ran_today"), \
         patch("update_all.cli.notify.send"), \
         patch("update_all.cli._print_versions"):
        result = runner.invoke(app, ["--force", "--no-colors"])

    assert result.exit_code == 0
    run_sequential.assert_not_called()
    assert [updater.label for updater in run_parallel.call_args.args[0]] == ["NPM"]


def test_print_versions_skips_code_on_linux_even_when_on_path():
    def which(name):
        return "/usr/bin/code" if name == "code" else None

    with patch("update_all.commands.sys.platform", "linux"), \
         patch("update_all.commands.shutil.which", side_effect=which), \
         patch("update_all.commands.subprocess.run", return_value=CompletedProcess([], 1)), \
         patch("update_all.cli.subprocess") as cli_subprocess:
        _print_versions(Console())

    cli_subprocess.run.assert_not_called()


def test_print_versions_skips_claude_when_not_installed():
    with patch("update_all.commands.shutil.which", return_value=None), \
         patch("update_all.commands.subprocess.run", return_value=CompletedProcess([], 1)), \
         patch("update_all.cli.subprocess") as cli_subprocess:
        _print_versions(Console())

    cli_subprocess.run.assert_not_called()


def test_print_versions_probes_code_on_macos_when_available():
    def which(name):
        return "/usr/local/bin/code" if name == "code" else None

    result = type("Result", (), {"stdout": "1.2.3\n", "stderr": ""})()
    with patch("update_all.commands.sys.platform", "darwin"), \
         patch("update_all.commands.shutil.which", side_effect=which), \
         patch("update_all.commands.subprocess.run", return_value=CompletedProcess([], 1)), \
         patch("update_all.cli.subprocess") as cli_subprocess:
        cli_subprocess.run.return_value = result
        _print_versions(Console())

    cli_subprocess.run.assert_called_once_with(
        ["code", "--version"], capture_output=True, text=True, check=False, timeout=5
    )



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


def test_extract_notes_does_not_truncate_long_error_line():
    error_line = "error: " + ("details " * 20)
    result = JobResult(
        label="CARGO", exit_code=1,
        output=f"Updating registry\n{error_line}\naborting",
        duration=5.0, succeeded=False,
    )

    assert _extract_notes(result) == error_line.strip()
