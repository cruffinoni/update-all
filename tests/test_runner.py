"""Tests for update_all.runner."""

from unittest.mock import patch, MagicMock

import pytest
from rich.console import Console

from update_all.responder import PromptResponder
from update_all.runner import JobDashboard, JobResult, run_sequential, run_parallel
from update_all.updaters import Updater


def _make_console() -> Console:
    return Console(quiet=True)


def _make_dashboard() -> JobDashboard:
    return JobDashboard(Console(quiet=True), disabled=True)


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
    results = run_sequential([_skipped_updater("SKIP")], console, _make_dashboard())
    assert results == []


def test_run_sequential_echo_succeeds():
    console = _make_console()
    updater = _echo_updater("ECHO", "echo hello")
    results = run_sequential([updater], console, _make_dashboard())
    assert len(results) == 1
    assert results[0].succeeded is True
    assert results[0].label == "ECHO"


def test_run_parallel_echo_succeeds():
    console = _make_console()
    updater = _echo_updater("ECHOPAR", "echo world")
    results = run_parallel([updater], max_workers=2, console=console, dashboard=_make_dashboard())
    assert len(results) == 1
    assert results[0].succeeded is True
    assert "world" in results[0].output


def test_run_parallel_background_does_not_use_progress_display():
    console = _make_console()
    updater = _echo_updater("BG", "echo bg")
    dashboard = JobDashboard(console, disabled=True)
    results = run_parallel([updater], max_workers=2, console=console, dashboard=dashboard, background=True)
    assert dashboard._disabled is True
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


def test_execute_job_pty_auto_answers_prompt():
    from update_all.runner import _execute_job

    updater = Updater(
        label="BREWLIKE",
        commands=['printf "Proceed? [y/N] "; read ans; echo "GOT-answer=$ans"'],
        check=lambda: True,
        description="prompting updater",
        responder=PromptResponder(),
    )
    result = _execute_job(updater)
    assert result.succeeded
    assert "GOT-answer=y" in result.output


def test_execute_job_pty_answers_newline_terminated_prompt():
    # Brew prints the question on its own line, then blocks on a separate read.
    from update_all.runner import _execute_job

    updater = Updater(
        label="BREWLIKE",
        commands=['echo "==> Do you want to proceed with the upgrade?"; read ans; echo "GOT-answer=$ans"'],
        check=lambda: True,
        description="prompting updater",
        responder=PromptResponder(),
    )
    result = _execute_job(updater)
    assert result.succeeded
    assert "GOT-answer=y" in result.output


def test_execute_job_pty_no_spurious_answer_on_silent_gap():
    # A non-prompt line followed by a silent pause must not trigger an answer.
    from update_all.runner import _execute_job

    updater = Updater(
        label="BREWLIKE",
        commands=['echo "==> Pouring bottle"; sleep 0.4; echo done'],
        check=lambda: True,
        description="",
        responder=PromptResponder(),
    )
    result = _execute_job(updater)
    assert result.succeeded
    assert result.output == "==> Pouring bottle\ndone"


def test_execute_job_pty_streams_lines():
    from update_all.runner import _execute_job

    lines_seen: list[str] = []
    updater = Updater(
        label="BREWLIKE",
        commands=["printf 'line1\\nline2\\n'"],
        check=lambda: True,
        description="",
        responder=PromptResponder(),
    )
    result = _execute_job(updater, on_line=lines_seen.append)
    assert result.succeeded
    assert "line1" in lines_seen
    assert "line2" in lines_seen


def test_execute_job_without_responder_uses_pipe_path():
    from update_all import runner

    updater = Updater(
        label="NOPTY",
        commands=["echo hi"],
        check=lambda: True,
        description="",
    )
    with patch.object(runner, "_execute_job_pty") as pty_mock:
        result = runner._execute_job(updater)
    pty_mock.assert_not_called()
    assert result.succeeded


def test_needs_sudo_updater_uses_pty_path():
    from update_all import runner

    updater = Updater(
        label="APT",
        commands=["echo hi"],
        check=lambda: True,
        needs_sudo=True,
        description="",
    )
    with patch.object(runner, "_execute_job_pty") as pty_mock:
        runner._execute_job(updater)
    pty_mock.assert_called_once()


def test_execute_job_pty_answers_password_prompt():
    from update_all.password import PasswordBroker
    from update_all.runner import _execute_job

    broker = PasswordBroker(prompt_fn=lambda ctx, reprompt: "hunter2")
    updater = Updater(
        label="APT",
        commands=['printf "Password: "; read -s p; echo; echo "GOT=$p"'],
        check=lambda: True,
        needs_sudo=True,
        description="sudo updater",
    )
    result = _execute_job(updater, broker=broker)
    assert result.succeeded
    assert "GOT=hunter2" in result.output


def test_execute_job_pty_password_prompt_gets_context_lines():
    from update_all.password import PasswordBroker
    from update_all.runner import _execute_job

    seen_context: list[list[str]] = []

    def prompt(ctx, reprompt):
        seen_context.append(ctx)
        return "pw"

    broker = PasswordBroker(prompt_fn=prompt)
    updater = Updater(
        label="APT",
        commands=['echo "==> Installing foo"; printf "Password: "; read -s p; echo; echo done'],
        check=lambda: True,
        needs_sudo=True,
        description="",
    )
    result = _execute_job(updater, broker=broker)
    assert result.succeeded
    assert seen_context and "==> Installing foo" in seen_context[0]


def test_password_regex_matches_platform_prompts():
    from update_all.runner import _PASSWORD_RE

    assert _PASSWORD_RE.search("Password:")
    assert _PASSWORD_RE.search("Password: ")
    assert _PASSWORD_RE.search("[sudo] password for alice:")
    assert _PASSWORD_RE.search("==> Installing\n[sudo] password for bob: ")


def test_password_regex_ignores_non_prompts():
    from update_all.runner import _PASSWORD_RE

    assert not _PASSWORD_RE.search("Downloading package...")
    assert not _PASSWORD_RE.search("Proceed? [y/N] ")
    assert not _PASSWORD_RE.search("Enter your password here and press go")


def test_run_parallel_skips_when_check_false():
    console = _make_console()
    results = run_parallel([_skipped_updater("SKIPPAR")], max_workers=2, console=console, dashboard=_make_dashboard())
    assert results == []


def test_run_sequential_failure_propagates():
    failing_updater = Updater(
        label="FAIL",
        commands=["exit 1"],
        check=lambda: True,
        description="Fails on purpose",
    )
    results = run_sequential([failing_updater], Console(quiet=True), _make_dashboard())
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
        run_sequential([updater], _make_console(), _make_dashboard(), background=True)

    assert captured == ["sudo -n apt update"]


def test_run_sequential_foreground_keeps_sudo_unchanged():
    captured: list[str] = []

    def fake_popen(args, **_kwargs):
        captured.append(args[2])
        mock = MagicMock()
        mock.stdout = iter([])
        mock.returncode = 0
        mock.wait.return_value = 0
        return mock

    updater = Updater(
        label="APT",
        commands=["sudo apt update"],
        check=lambda: True,
        needs_sudo=True,
        description="test",
    )
    with patch("update_all.runner.subprocess.Popen", side_effect=fake_popen):
        run_sequential([updater], _make_console(), _make_dashboard(), background=False)

    assert captured == ["sudo apt update"]


def _rendered_lines(dashboard: JobDashboard) -> list[str]:
    from rich.console import Console

    console = Console(width=120, file=None)
    with console.capture() as cap:
        console.print(dashboard.__rich__())
    return cap.get().splitlines()


def test_dashboard_window_rolls_to_last_five_lines():
    from update_all.runner import _WINDOW

    dashboard = _make_dashboard()
    dashboard.register("BREW")
    dashboard.start("BREW")
    for i in range(7):
        dashboard.line("BREW", f"line-{i}")

    view = dashboard._views["BREW"]
    assert list(view.lines) == [f"line-{i}" for i in range(2, 7)]
    assert len(view.lines) == _WINDOW


def test_dashboard_running_job_reserves_five_log_slots():
    from update_all.runner import _WINDOW

    dashboard = _make_dashboard()
    dashboard.register("BREW")
    dashboard.start("BREW")
    dashboard.line("BREW", "only-one")

    # 1 header + _WINDOW log slots (blank-padded when fewer than _WINDOW lines).
    lines = _rendered_lines(dashboard)
    assert len(lines) == 1 + _WINDOW
    assert "only-one" in lines[1]


def test_dashboard_complete_collapses_to_summary():
    dashboard = _make_dashboard()
    dashboard.register("BREW")
    dashboard.start("BREW")
    result = JobResult(label="BREW", exit_code=0, output="hello", duration=1.0, succeeded=True)
    dashboard.complete("BREW", result)

    view = dashboard._views["BREW"]
    assert view.state == "done"
    assert view.note

    # A finished job renders as a single line, not a 6-line block.
    lines = _rendered_lines(dashboard)
    assert len(lines) == 1
    assert "BREW" in lines[0]


def test_dashboard_complete_marks_failure():
    dashboard = _make_dashboard()
    dashboard.register("BREW")
    dashboard.start("BREW")
    result = JobResult(label="BREW", exit_code=1, output="boom", duration=1.0, succeeded=False)
    dashboard.complete("BREW", result)

    assert dashboard._views["BREW"].state == "fail"
