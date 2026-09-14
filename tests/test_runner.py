"""Tests for update_all.runner."""

import threading
from unittest.mock import patch, MagicMock

import pytest
from rich.console import Console

from update_all.responder import PromptResponder
from update_all.runner import JobDashboard, JobResult, run_sequential, run_parallel, verify_sudo_password
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

    lines_seen: list[str] = []
    updater = Updater(
        label="BREWLIKE",
        commands=['printf "Proceed? [y/N] "; read ans; echo "GOT-answer=$ans"'],
        check=lambda: True,
        description="prompting updater",
        responder=PromptResponder(),
    )
    result = _execute_job(updater, on_line=lines_seen.append)
    assert result.succeeded
    assert "GOT-answer=y" in result.output
    assert any("Proceed? [y/N]" in line and "auto-answered: y" in line for line in lines_seen)


def test_execute_job_pty_keeps_output_after_unterminated_prompt_visible():
    from update_all.runner import _execute_job

    lines_seen: list[str] = []
    updater = Updater(
        label="BREWLIKE",
        commands=['printf "Proceed? [y/N] "; read ans; printf "received=%s\\n" "$ans"'],
        check=lambda: True,
        description="prompting updater",
        responder=PromptResponder(),
    )

    result = _execute_job(updater, on_line=lines_seen.append)

    assert result.succeeded
    assert "received=y" in result.output
    assert "received=y" in lines_seen


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


def test_execute_job_pty_streams_carriage_return_progress_before_completion():
    from update_all.runner import _execute_job

    progress_seen = threading.Event()
    lines_seen: list[str] = []

    updater = Updater(
        label="APT",
        commands=["printf 'apt progress 1\\r'; sleep 0.4; printf 'apt progress 2\\r'; printf 'done\\n'"],
        check=lambda: True,
        description="apt-like updater",
        needs_sudo=True,
    )

    def on_line(line: str) -> None:
        lines_seen.append(line)
        if line == "apt progress 1":
            progress_seen.set()

    result_holder: list[object] = []
    thread = threading.Thread(target=lambda: result_holder.append(_execute_job(updater, on_line=on_line)))
    thread.start()
    assert progress_seen.wait(timeout=1.0)
    assert thread.is_alive()
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    result = result_holder[0]
    assert result.succeeded
    assert "apt progress 1\napt progress 2\ndone" in result.output
    assert lines_seen[:2] == ["apt progress 1", "apt progress 2"]


def test_execute_job_reports_command_start_marker():
    from update_all.runner import _execute_job

    commands_seen: list[str] = []
    updater = Updater(
        label="APT",
        commands=["printf 'done\\n'"],
        check=lambda: True,
        description="apt-like updater",
        needs_sudo=True,
    )

    result = _execute_job(updater, on_command=commands_seen.append)

    assert result.succeeded
    assert commands_seen == ["printf 'done\\n'"]


def test_execute_job_reports_process_pid():
    from update_all.runner import _execute_job

    pids_seen: list[int] = []
    result = _execute_job(_echo_updater("PID"), on_process_start=pids_seen.append)

    assert result.succeeded
    assert len(pids_seen) == 1
    assert pids_seen[0] > 0


def test_terminate_pty_process_stops_its_process_group():
    from update_all import runner

    proc = MagicMock()
    proc.pid = 12345
    proc.poll.return_value = None

    with patch("update_all.runner.os.killpg") as killpg:
        runner._terminate_pty_process(proc)

    killpg.assert_called_once_with(12345, runner.signal.SIGTERM)
    proc.wait.assert_called_once_with(timeout=2)


def test_execute_job_reports_cached_sudo_response():
    from update_all.password import PasswordBroker
    from update_all.runner import _execute_job

    lines_seen: list[str] = []
    broker = PasswordBroker(prompt_fn=lambda ctx, reprompt: "secret")
    broker.get_password([], reprompt=False)
    updater = Updater(
        label="APT",
        commands=[
            'printf "[sudo] password for test: "; read -s password; echo; '
            '[ "$password" = "secret" ] && echo MATCH || echo MISMATCH'
        ],
        check=lambda: True,
        needs_sudo=True,
        description="sudo updater",
    )

    result = _execute_job(updater, on_line=lines_seen.append, broker=broker)

    assert result.succeeded
    assert "MATCH" in result.output
    assert "secret" not in result.output
    assert "[sudo] password requested — supplying cached credential" in lines_seen


def test_execute_job_pty_answers_sudo_rs_password_prompt():
    from update_all.password import PasswordBroker
    from update_all.runner import _execute_job

    broker = PasswordBroker(prompt_fn=lambda ctx, reprompt: "secret")
    broker.get_password([], reprompt=False)
    updater = Updater(
        label="APT",
        commands=[
            'printf "[sudo: authenticate] Password: "; read -s password; echo; '
            '[ "$password" = "secret" ] && echo MATCH || echo MISMATCH'
        ],
        check=lambda: True,
        needs_sudo=True,
        description="sudo-rs updater",
    )

    result = _execute_job(updater, broker=broker)

    assert result.succeeded
    assert "MATCH" in result.output
    assert "secret" not in result.output


def test_run_sequential_apt_dashboard_shows_command_and_output():
    updater = Updater(
        label="APT",
        commands=["printf 'apt done\\n'"],
        check=lambda: True,
        is_sequential=True,
        needs_sudo=True,
        description="apt-like updater",
    )
    dashboard = _make_dashboard()

    results = run_sequential([updater], _make_console(), dashboard)

    assert results[0].succeeded
    assert list(dashboard._views["APT"].lines) == ["$ printf 'apt done\\n'", "apt done"]


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
        commands=[
            'printf "Password: "; read -s p; echo; '
            '[ "$p" = "hunter2" ] && echo MATCH || echo MISMATCH'
        ],
        check=lambda: True,
        needs_sudo=True,
        description="sudo updater",
    )
    result = _execute_job(updater, broker=broker)
    assert result.succeeded
    assert "MATCH" in result.output
    assert "hunter2" not in result.output


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


def test_verify_sudo_password_probes_with_sudo_dash_k_dash_v():
    from update_all import runner

    broker = MagicMock()
    fake_result = JobResult(label="SUDO", exit_code=0, output="", duration=0.0, succeeded=True)

    with patch.object(runner, "_execute_job_pty", return_value=fake_result) as pty_mock:
        result = verify_sudo_password(broker)

    assert result is fake_result
    pty_mock.assert_called_once()
    probe = pty_mock.call_args.args[0]
    assert probe.commands == ["sudo -k -v"]
    assert probe.needs_sudo is True
    assert pty_mock.call_args.kwargs["broker"] is broker


def test_execute_job_pty_retries_after_wrong_sudo_password_then_succeeds():
    from update_all.password import PasswordBroker
    from update_all.runner import _execute_job

    attempts = iter(["wrong", "correct"])
    broker = PasswordBroker(prompt_fn=lambda ctx, reprompt: next(attempts))
    lines_seen: list[str] = []
    updater = Updater(
        label="SUDO",
        commands=[
            'printf "[sudo] password for test: "; read -s p1; echo; '
            'if [ "$p1" = "correct" ]; then exit 0; fi; '
            'echo "Sorry, try again."; '
            'printf "[sudo] password for test: "; read -s p2; echo; '
            '[ "$p2" = "correct" ]'
        ],
        check=lambda: True,
        needs_sudo=True,
        description="sudo probe",
    )

    result = _execute_job(updater, on_line=lines_seen.append, broker=broker)

    assert result.succeeded
    # Exactly one rejection notice for the one wrong entry — not duplicated.
    rejections = [l for l in lines_seen if l == "[sudo] password rejected — requesting it again"]
    assert len(rejections) == 1


def test_execute_job_pty_fails_when_sudo_password_never_correct():
    from update_all.password import PasswordBroker
    from update_all.runner import _execute_job

    broker = PasswordBroker(prompt_fn=lambda ctx, reprompt: "wrong")
    updater = Updater(
        label="SUDO",
        commands=[
            'printf "[sudo] password for test: "; read -s p; echo; '
            '[ "$p" = "correct" ] || { echo "Sorry, try again."; exit 1; }'
        ],
        check=lambda: True,
        needs_sudo=True,
        description="sudo probe",
    )

    result = _execute_job(updater, broker=broker)

    assert result.succeeded is False
    assert result.exit_code != 0


def test_spawn_pty_process_disables_echo():
    import os
    import termios

    from update_all.runner import _spawn_pty_process, _terminate_pty_process

    proc, master = _spawn_pty_process("sleep 0.2")
    try:
        attrs = termios.tcgetattr(master)
        assert not (attrs[3] & termios.ECHO)
    finally:
        _terminate_pty_process(proc)
        os.close(master)


def test_execute_job_pty_does_not_leak_password_via_echo():
    from update_all.password import PasswordBroker
    from update_all.runner import _execute_job

    broker = PasswordBroker(prompt_fn=lambda ctx, reprompt: "supersecret")
    updater = Updater(
        label="OS",
        commands=[
            # Deliberately omits `-s`, unlike every other prompt test here:
            # a script that doesn't suppress its own echo is exactly what
            # exposed the leak this guards against. This is an end-to-end
            # check backed by two independent layers (pty echo disabled in
            # _spawn_pty_process, plus _redact as a backstop) — confirmed by
            # temporarily reverting _disable_echo and observing the raw
            # (pre-redaction) output actually contained the password.
            'printf "[sudo] password for test: "; read password; echo; echo done'
        ],
        check=lambda: True,
        needs_sudo=True,
        description="os updater",
    )

    result = _execute_job(updater, broker=broker)

    assert result.succeeded
    assert "supersecret" not in result.output


def test_redact_scrubs_cached_password_from_text():
    from update_all.password import PasswordBroker
    from update_all.runner import _redact

    broker = PasswordBroker(prompt_fn=lambda ctx, reprompt: "supersecret")
    broker.get_password([], reprompt=False)

    assert _redact("value=supersecret end", broker) == "value=******** end"


def test_redact_is_noop_without_cached_password():
    from update_all.password import PasswordBroker
    from update_all.runner import _redact

    broker = PasswordBroker(prompt_fn=lambda ctx, reprompt: "supersecret")

    assert _redact("hello world", broker) == "hello world"
    assert _redact("hello world", None) == "hello world"


def test_verify_sudo_password_retries_on_failure_without_rejection_text():
    from update_all.password import PasswordBroker

    broker = PasswordBroker(prompt_fn=lambda ctx, reprompt: "secret")
    calls = {"count": 0}

    def fake_execute(probe, on_line=lambda _: None, broker=None):
        calls["count"] += 1
        if calls["count"] < 3:
            return JobResult(
                label="SUDO", exit_code=1,
                output="sudo: a terminal is required to read the password",
                duration=0.0, succeeded=False,
            )
        return JobResult(label="SUDO", exit_code=0, output="", duration=0.0, succeeded=True)

    with patch("update_all.runner._execute_job_pty", side_effect=fake_execute), \
         patch("update_all.runner.time.sleep"):
        result = verify_sudo_password(broker, max_attempts=3)

    assert result.succeeded
    assert calls["count"] == 3


def test_verify_sudo_password_does_not_retry_after_genuine_rejection():
    from update_all.password import PasswordBroker

    broker = PasswordBroker(prompt_fn=lambda ctx, reprompt: "wrong")
    calls = {"count": 0}

    def fake_execute(probe, on_line=lambda _: None, broker=None):
        calls["count"] += 1
        return JobResult(
            label="SUDO", exit_code=1,
            output="Sorry, try again.\nsudo: 3 incorrect password attempts",
            duration=0.0, succeeded=False,
        )

    with patch("update_all.runner._execute_job_pty", side_effect=fake_execute), \
         patch("update_all.runner.time.sleep"):
        result = verify_sudo_password(broker, max_attempts=3)

    assert result.succeeded is False
    assert calls["count"] == 1


def test_execute_job_pty_prints_cancelling_message_on_keyboard_interrupt():
    from update_all import runner
    from update_all.runner import _execute_job

    lines_seen: list[str] = []
    updater = Updater(
        label="SUDO",
        commands=["sleep 0.1"],
        check=lambda: True,
        needs_sudo=True,
        description="",
    )

    with patch("update_all.runner.select.select", side_effect=KeyboardInterrupt), \
         patch.object(runner, "_terminate_pty_process", wraps=runner._terminate_pty_process) as terminate_mock:
        with pytest.raises(KeyboardInterrupt):
            _execute_job(updater, on_line=lines_seen.append)

    assert lines_seen == ["Cancelling…"]
    terminate_mock.assert_called_once()


def test_run_parallel_uses_bounded_wait_not_as_completed():
    from update_all import runner

    updater = _echo_updater("PARWAIT", "echo hi")

    with patch.object(runner.concurrent.futures, "as_completed") as as_completed_mock:
        run_parallel([updater], max_workers=2, console=_make_console(), dashboard=_make_dashboard())

    as_completed_mock.assert_not_called()


def test_run_parallel_propagates_keyboard_interrupt_promptly():
    from update_all import runner

    updater = _echo_updater("PARINT", "sleep 0.2")

    with patch.object(runner.concurrent.futures, "wait", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            run_parallel([updater], max_workers=2, console=_make_console(), dashboard=_make_dashboard())


def test_password_regex_matches_platform_prompts():
    from update_all.runner import _PASSWORD_RE

    assert _PASSWORD_RE.search("Password:")
    assert _PASSWORD_RE.search("Password: ")
    assert _PASSWORD_RE.search("[sudo] password for alice:")
    assert _PASSWORD_RE.search("==> Installing\n[sudo] password for bob: ")
    assert _PASSWORD_RE.search("[sudo: authenticate] Password:")
    assert _PASSWORD_RE.search("[sudo: authenticate] Password:   ")


def test_password_regex_ignores_non_prompts():
    from update_all.runner import _PASSWORD_RE

    assert not _PASSWORD_RE.search("Downloading package...")
    assert not _PASSWORD_RE.search("Proceed? [y/N] ")
    assert not _PASSWORD_RE.search("Enter your password here and press go")
    assert not _PASSWORD_RE.search("[sudo: authenticate] PIN:")


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

    class FakeProcess:
        pid = 123

        @staticmethod
        def poll():
            return 0

        @staticmethod
        def wait():
            return 0

    def fake_spawn(cmd):
        import os
        import pty

        captured.append(cmd)
        master, slave = pty.openpty()
        os.close(slave)
        return FakeProcess(), master

    updater = Updater(
        label="APT",
        commands=["sudo apt update"],
        check=lambda: True,
        needs_sudo=True,
        description="test",
    )
    with patch("update_all.runner._spawn_pty_process", side_effect=fake_spawn):
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


def test_dashboard_preserves_long_log_lines():
    dashboard = _make_dashboard()
    long_line = "x" * 120
    dashboard.register("BREW")
    dashboard.start("BREW")

    dashboard.line("BREW", long_line)

    assert list(dashboard._views["BREW"].lines) == [long_line]


def test_dashboard_shows_silent_process_details():
    from update_all import runner

    dashboard = _make_dashboard()
    dashboard.register("APT")
    dashboard.start("APT")
    dashboard.process("APT", 12345)
    dashboard._views["APT"].last_output = runner.time.monotonic() - runner._SILENCE_NOTICE_SECONDS

    rendered = "\n".join(_rendered_lines(dashboard))
    assert "pid 12345" in rendered
    assert "waiting for output" in rendered


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
