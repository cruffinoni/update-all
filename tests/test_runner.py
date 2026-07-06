"""Tests for update_all.runner."""

from unittest.mock import patch, MagicMock

import pytest
from rich.console import Console

from update_all.runner import JobResult, run_sequential, run_parallel
from update_all.updaters import Updater


def _make_console() -> Console:
    return Console(quiet=True)


def _echo_updater(label: str, cmd: str = "echo hello") -> Updater:
    return Updater(
        label=label,
        description="test updater",
        check=lambda: True,
        commands=[cmd],
    )


def _skipped_updater(label: str) -> Updater:
    return Updater(
        label=label,
        description="skipped updater",
        check=lambda: False,
        commands=["echo should-not-run"],
    )


def test_job_result_succeeded_on_exit_zero():
    result = JobResult(label="X", exit_code=0, output="", duration=0.0, succeeded=True)
    assert result.succeeded is True


def test_job_result_failed_on_nonzero_exit():
    result = JobResult(label="X", exit_code=1, output="", duration=0.0, succeeded=False)
    assert result.succeeded is False


def test_run_sequential_skips_when_check_false():
    console = _make_console()
    results = run_sequential([_skipped_updater("SKIP")], console)
    assert results == []


def test_run_sequential_echo_succeeds():
    console = _make_console()
    updater = _echo_updater("ECHO", "echo hello")
    results = run_sequential([updater], console)
    assert len(results) == 1
    assert results[0].succeeded is True
    assert results[0].label == "ECHO"


def test_run_parallel_echo_succeeds():
    console = _make_console()
    updater = _echo_updater("ECHOPAR", "echo world")
    results = run_parallel([updater], max_workers=2, console=console)
    assert len(results) == 1
    assert results[0].succeeded is True
    assert "world" in results[0].output


def test_run_parallel_background_does_not_use_progress_display():
    console = _make_console()
    updater = _echo_updater("BG", "echo bg")
    with patch("update_all.runner.Progress") as mock_progress_cls:
        mock_prog = MagicMock()
        mock_prog.__enter__ = MagicMock(return_value=mock_prog)
        mock_prog.__exit__ = MagicMock(return_value=False)
        mock_prog.add_task = MagicMock(return_value=0)
        mock_prog.update = MagicMock()
        mock_progress_cls.return_value = mock_prog
        results = run_parallel([updater], max_workers=2, console=console, background=True)
        assert mock_progress_cls.call_args.kwargs.get("disable") is True
    assert len(results) == 1


def test_execute_job_calls_on_line_callback():
    from update_all.runner import _execute_job

    lines_seen: list[str] = []
    updater = Updater(
        label="CB",
        commands=["printf 'line1\\nline2\\n'"],
        check=lambda: True,
        description="",
    )
    result = _execute_job(updater, on_line=lines_seen.append)
    assert result.succeeded
    assert "line1" in lines_seen
    assert "line2" in lines_seen


def test_run_parallel_skips_when_check_false():
    console = _make_console()
    results = run_parallel([_skipped_updater("SKIPPAR")], max_workers=2, console=console)
    assert results == []


def test_run_sequential_failure_propagates():
    from update_all.updaters import Updater
    from update_all.runner import run_sequential
    from rich.console import Console
    failing_updater = Updater(
        label="FAIL",
        commands=["exit 1"],
        check=lambda: True,
        description="Fails on purpose",
    )
    results = run_sequential([failing_updater], Console(quiet=True))
    assert len(results) == 1
    assert results[0].succeeded is False
    assert results[0].exit_code != 0


def test_run_sequential_background_rewrites_sudo_for_needs_sudo_updater():
    captured: list[str] = []

    def fake_run(args, **_kwargs):
        captured.append(args[2])
        mock = MagicMock()
        mock.returncode = 0
        return mock

    updater = Updater(
        label="APT",
        commands=["sudo apt update"],
        check=lambda: True,
        needs_sudo=True,
        description="test",
    )
    with patch("update_all.runner.subprocess.run", side_effect=fake_run):
        run_sequential([updater], _make_console(), background=True)

    assert captured == ["sudo -n apt update"]


def test_run_sequential_foreground_keeps_sudo_unchanged():
    captured: list[str] = []

    def fake_run(args, **_kwargs):
        captured.append(args[2])
        mock = MagicMock()
        mock.returncode = 0
        return mock

    updater = Updater(
        label="APT",
        commands=["sudo apt update"],
        check=lambda: True,
        needs_sudo=True,
        description="test",
    )
    with patch("update_all.runner.subprocess.run", side_effect=fake_run):
        run_sequential([updater], _make_console(), background=False)

    assert captured == ["sudo apt update"]
