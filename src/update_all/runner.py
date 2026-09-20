"""Sequential and parallel job runners for update-all."""

from __future__ import annotations

import concurrent.futures
import os
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from rich.console import Console, Group
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from update_all.password import PasswordBroker
from update_all.updaters import Updater

_WINDOW = 5
_SILENCE_NOTICE_SECONDS = 10

# ANSI SGR/cursor escapes, stripped before matching password prompts.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# A sudo password prompt at the end of the current output tail.
_PASSWORD_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:password:|\[sudo\] password for .+?:|\[sudo: authenticate\] password:)[ \t]*\Z",
    re.IGNORECASE,
)
# Emitted by sudo after a rejected attempt → re-prompt with a fresh password.
_PW_FAIL_RE = re.compile(r"sorry, try again\.|authentication fail(?:ure|ed)", re.IGNORECASE)


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h} h {m} min" if m else f"{h} h"
    if m:
        return f"{m} min {sec} s" if sec else f"{m} min"
    return f"{sec} s"


@dataclass
class JobResult:
    """Result of a single updater job execution."""

    label: str
    exit_code: int
    output: str
    duration: float
    succeeded: bool
    description: str = ""
    error_lines: int = 20


def _disable_echo(fd: int) -> None:
    """Turn off local echo on the pty.

    update-all never has a live human typing into this pty — it always
    injects bytes itself (sudo passwords, y/N answers) via ``os.write``. With
    echo on, the line discipline reflects those injected bytes straight back
    into the output stream we capture and may display or log, including a
    plaintext sudo password. Only ``ECHO`` is cleared; canonical line
    buffering is untouched.
    """
    attrs = termios.tcgetattr(fd)
    attrs[3] &= ~termios.ECHO  # lflag
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def _spawn_pty_process(cmd: str) -> tuple[subprocess.Popen[bytes], int]:
    """Run ``cmd`` with the PTY as its controlling terminal.

    Redirecting stdin/stdout/stderr alone is insufficient for sudo: it opens
    ``/dev/tty`` for authentication. A small bootstrap process makes the slave
    its controlling terminal, keeping the prompt in the stream we supervise
    without forking from the parallel worker threads.
    """
    master, slave = pty.openpty()
    _disable_echo(slave)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "update_all.pty_exec", os.ttyname(slave), cmd],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
    except Exception:
        os.close(master)
        raise
    finally:
        os.close(slave)
    return proc, master


def _terminate_pty_process(proc: subprocess.Popen[bytes]) -> None:
    """Stop the controlling-PTY session after an interrupted runner."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        proc.wait()


def _completion_note(result: JobResult) -> str:
    """One-line summary shown in the progress row after completion."""
    from update_all.cli import _extract_notes  # lazy to avoid circular import at module load
    try:
        return _extract_notes(result)
    except Exception:
        pass
    if not result.succeeded:
        for line in result.output.splitlines():
            line = line.strip()
            if line and ("error" in line.lower() or "fatal" in line.lower() or "failed" in line.lower()):
                return line
    lines = [l for l in result.output.splitlines() if l.strip()]
    return lines[-1] if lines else "—"


@dataclass
class JobView:
    """Live view state for a single updater in the dashboard."""

    label: str
    state: str = "pending"  # pending | running | done | fail
    start: float = 0.0
    duration: float = 0.0
    lines: deque = field(default_factory=lambda: deque(maxlen=_WINDOW))
    note: str = ""
    pid: int | None = None
    last_output: float = 0.0


class JobDashboard:
    """Live multi-line dashboard: a header per job plus a rolling 5-line log while running."""

    def __init__(self, console: Console, *, disabled: bool = False) -> None:
        self._console = console
        self._disabled = disabled
        self._views: dict[str, JobView] = {}
        self._spinner = Spinner("dots")
        self._live = Live(
            self,
            console=console,
            refresh_per_second=12,
            transient=False,
            vertical_overflow="crop",
        )

    def register(self, label: str) -> None:
        self._views[label] = JobView(label=label)

    def start(self, label: str) -> None:
        view = self._views.get(label) or JobView(label=label)
        view.state = "running"
        view.start = time.monotonic()
        view.last_output = view.start
        self._views[label] = view

    def line(self, label: str, text: str) -> None:
        view = self._views.get(label)
        if view is not None:
            view.lines.append(text)
            view.last_output = time.monotonic()

    def process(self, label: str, pid: int) -> None:
        """Record the process that is executing a dashboard command."""
        view = self._views.get(label)
        if view is not None:
            view.pid = pid
            view.last_output = time.monotonic()

    def complete(self, label: str, result: JobResult) -> None:
        view = self._views.get(label) or JobView(label=label)
        view.state = "done" if result.succeeded else "fail"
        view.duration = result.duration
        view.note = _completion_note(result)
        self._views[label] = view

    def __enter__(self) -> "JobDashboard":
        if not self._disabled:
            self._live.start()
        return self

    def __exit__(self, *_: object) -> None:
        if not self._disabled:
            self._live.stop()

    @contextmanager
    def pause(self) -> Iterator[None]:
        """Temporarily stop the live display so another consumer can own the terminal."""
        if self._disabled:
            yield
            return
        self._live.stop()
        try:
            yield
        finally:
            self._live.start()

    def __rich__(self) -> Group:
        now = time.monotonic()
        rows: list[Text] = []
        for view in self._views.values():
            if view.state == "pending":
                rows.append(Text(f"  {view.label}", style="dim"))
            elif view.state == "running":
                details: list[tuple[str, str]] = [(fmt_duration(now - view.start), "dim")]
                if view.pid is not None:
                    details.append((f"  ·  pid {view.pid}", "dim"))
                silence = now - view.last_output
                if view.pid is not None and silence >= _SILENCE_NOTICE_SECONDS:
                    details.append((f"  ·  waiting for output ({fmt_duration(silence)})", "yellow"))
                rows.append(
                    Text.assemble(
                        self._spinner.render(now),
                        f" {view.label:<8} ",
                        *details,
                    )
                )
                lines = list(view.lines)
                lines += [""] * (_WINDOW - len(lines))
                for entry in lines:
                    rows.append(Text(f"    {entry}", style="dim"))
            else:
                icon = "[green]✓[/green]" if view.state == "done" else "[red]✗[/red]"
                rows.append(
                    Text.from_markup(
                        f"{icon} {view.label:<8} [dim]{fmt_duration(view.duration)}  {view.note}[/dim]"
                    )
                )
        return Group(*rows)


def run_sequential(
    updaters: list[Updater],
    console: Console,
    dashboard: JobDashboard,
    *,
    background: bool = False,
    broker: PasswordBroker | None = None,
) -> list[JobResult]:
    """Run updaters sequentially, streaming output directly to the terminal."""
    results: list[JobResult] = []

    for updater in updaters:
        if not updater.check():
            continue

        if background:
            exit_code = 0
            start = time.monotonic()
            for cmd in updater.commands:
                if updater.needs_sudo:
                    cmd = cmd.replace("sudo ", "sudo -n ", 1)
                proc = subprocess.run(["bash", "-lc", cmd], capture_output=False, check=False)
                if exit_code == 0 and proc.returncode != 0:
                    exit_code = proc.returncode
            duration = time.monotonic() - start
            results.append(
                JobResult(
                    label=updater.label,
                    exit_code=exit_code,
                    output="",
                    duration=duration,
                    succeeded=exit_code == 0,
                    error_lines=0,
                )
            )
            continue

        label = updater.label
        dashboard.register(label)
        dashboard.start(label)
        result = _execute_job(
            updater,
            on_line=lambda l, lbl=label: dashboard.line(lbl, l),
            on_command=lambda cmd, lbl=label: dashboard.line(lbl, f"$ {cmd}"),
            on_process_start=lambda pid, lbl=label: dashboard.process(lbl, pid),
            broker=broker,
        )
        dashboard.complete(label, result)
        results.append(result)

    return results


def _execute_job(
    updater: Updater,
    on_line: Callable[[str], None] = lambda _: None,
    broker: PasswordBroker | None = None,
    on_command: Callable[[str], None] = lambda _: None,
    on_process_start: Callable[[int], None] = lambda _: None,
) -> JobResult:
    """Execute all commands for a single updater, streaming output line-by-line."""
    if updater.responder is not None or updater.needs_sudo:
        return _execute_job_pty(
            updater,
            on_line=on_line,
            on_command=on_command,
            on_process_start=on_process_start,
            broker=broker,
        )

    output_parts: list[str] = []
    exit_code = 0
    start = time.monotonic()

    for cmd in updater.commands:
        on_command(cmd)
        proc = subprocess.Popen(
            ["bash", "-lc", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        on_process_start(proc.pid)
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip()
            output_parts.append(line)
            on_line(line)
        command_exit_code = proc.wait()
        if exit_code == 0 and command_exit_code != 0:
            exit_code = command_exit_code

    duration = time.monotonic() - start
    return JobResult(
        label=updater.label,
        exit_code=exit_code,
        output="\n".join(output_parts),
        duration=duration,
        succeeded=exit_code == 0,
        description=updater.description,
        error_lines=updater.error_lines,
    )


def _redact(text: str, broker: PasswordBroker | None) -> str:
    """Scrub the broker's cached sudo password out of captured output.

    A second, independent line of defense alongside disabling pty echo —
    in case some tool echoes back what it was fed regardless of terminal
    settings, the password should never end up in ``JobResult.output`` or
    anything printed/logged from it.
    """
    password = broker.peek_password() if broker is not None else None
    return text.replace(password, "********") if password else text


def _execute_job_pty(
    updater: Updater,
    on_line: Callable[[str], None] = lambda _: None,
    broker: PasswordBroker | None = None,
    on_command: Callable[[str], None] = lambda _: None,
    on_process_start: Callable[[int], None] = lambda _: None,
) -> JobResult:
    """Execute an updater under a pty, auto-answering interactive prompts.

    The command runs against a pseudo-terminal so it prompts as usual. A
    ``[y/N]`` question is auto-confirmed by the updater's responder; a sudo
    ``Password:`` prompt is handed to ``broker`` so the user can type it
    (serialized across parallel jobs). Both un-terminated prompts and
    newline-terminated prompts that then block on a read are handled.
    """
    output_parts: list[str] = []
    exit_code = 0
    start = time.monotonic()

    for cmd in updater.commands:
        on_command(cmd)
        proc, master = _spawn_pty_process(cmd)
        on_process_start(proc.pid)

        pending = ""  # text since the last newline — the prompt candidate
        pending_shown = False  # prompt text already surfaced before its delimiter
        last_line = ""  # last non-empty flushed line, for newline-terminated prompts
        answered = False  # guard so a single prompt is answered once

        def _answer(candidate: str, *, already_displayed: bool = False) -> bool:
            nonlocal answered, pending, pending_shown
            if answered or not candidate.strip():
                return False
            if broker is not None and _PASSWORD_RE.search(_ANSI_RE.sub("", candidate)):
                reprompt = bool(_PW_FAIL_RE.search("\n".join(output_parts[-3:])))
                context = [ln for ln in output_parts[-2:] if ln.strip()]
                if reprompt:
                    on_line("[sudo] password rejected — requesting it again")
                elif broker.has_cached_password():
                    on_line("[sudo] password requested — supplying cached credential")
                else:
                    on_line("[sudo] password requested — waiting for user input")
                os.write(master, broker.get_password(context, reprompt=reprompt))
                answered = True
                return True
            if updater.responder is None:
                return False
            response = updater.responder.response_for(candidate)
            if response is None:
                return False
            answer = response.decode("utf-8", "replace").strip() or "input"
            if not already_displayed:
                # The prompt has no delimiter, so it is still in ``pending``.
                # Record it as a completed output item before the answer can
                # cause the child to emit its next line; otherwise that line
                # gets merged into the prompt and hidden by ``pending_shown``.
                output_parts.append(_redact(candidate.rstrip("\r"), broker))
                pending = ""
            if already_displayed:
                on_line(f"    auto-answered: {answer}")
            else:
                on_line(f"{candidate.rstrip()} [auto-answered: {answer}]")
                pending_shown = False
            os.write(master, response)
            answered = True
            return True

        def _flush_output() -> None:
            """Emit complete newline or carriage-return-delimited output."""
            nonlocal pending, pending_shown, last_line
            while True:
                delimiters = [idx for idx in (pending.find("\n"), pending.find("\r")) if idx >= 0]
                if not delimiters:
                    return
                index = min(delimiters)
                delimiter = pending[index]
                line = pending[:index]
                pending = pending[index + 1 :]
                if delimiter == "\r" and pending.startswith("\n"):
                    pending = pending[1:]
                line = _redact(line.rstrip("\r"), broker)
                output_parts.append(line)
                if not pending_shown:
                    on_line(line)
                pending_shown = False
                if line.strip():
                    last_line = line

        try:
            while True:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break  # pty slave closed → process finished
                    if not chunk:
                        break
                    answered = False  # new output → a fresh prompt may follow
                    pending += chunk.decode("utf-8", "replace")
                    _flush_output()
                    # Prompt left on an un-terminated line (no newline yet).
                    if pending:
                        _answer(pending)
                elif proc.poll() is not None:
                    break
                else:
                    # Process is alive but idle — likely blocked on a read after
                    # printing a newline-terminated prompt. Answer the last line.
                    _answer(pending or last_line, already_displayed=not bool(pending))
        except KeyboardInterrupt:
            # Acknowledge immediately — the teardown below can take up to a
            # couple of seconds, and with no feedback in that window it looks
            # like the interrupt was ignored, inviting a second Ctrl+C.
            on_line("Cancelling…")
            _terminate_pty_process(proc)
            raise
        except BaseException:
            _terminate_pty_process(proc)
            raise
        finally:
            os.close(master)

        if pending:
            tail = _redact(pending.rstrip("\r"), broker)
            output_parts.append(tail)
            if not pending_shown:
                on_line(tail)
        command_exit_code = proc.wait()
        if exit_code == 0 and command_exit_code != 0:
            exit_code = command_exit_code

    duration = time.monotonic() - start
    return JobResult(
        label=updater.label,
        exit_code=exit_code,
        output="\n".join(output_parts),
        duration=duration,
        succeeded=exit_code == 0,
        description=updater.description,
        error_lines=updater.error_lines,
    )


def verify_sudo_password(
    broker: PasswordBroker,
    on_line: Callable[[str], None] = lambda _: None,
    max_attempts: int = 3,
) -> JobResult:
    """Confirm the password broker will hand out to real jobs is valid.

    Runs `sudo -k -v` through the same pty-answering path used for real
    updater commands, so a wrong password is caught once, up front,
    instead of surfacing later as an unrelated-looking failure in every
    job that happens to need sudo. `-k` discards any cached timestamp so
    an already-valid ambient credential can't mask a wrong password
    typed here.

    If a run fails without sudo ever having actually rejected a password
    (no ``_PW_FAIL_RE`` match anywhere in the output — e.g. a transient
    bootstrap hiccup rather than a real "wrong password"), retry a few
    times automatically instead of surfacing a bare failure that would
    otherwise require the user to relaunch the whole CLI. A genuine
    rejection is never retried beyond what sudo itself already allowed.
    """
    probe = Updater(
        label="SUDO",
        description="verify sudo credentials",
        check=lambda: True,
        needs_sudo=True,
        commands=["sudo -k -v"],
    )
    result = _execute_job_pty(probe, on_line=on_line, broker=broker)
    attempt = 1
    while not result.succeeded and attempt < max_attempts and not _PW_FAIL_RE.search(result.output):
        attempt += 1
        on_line(f"[sudo] verification failed unexpectedly — retrying ({attempt}/{max_attempts})…")
        time.sleep(0.5)
        result = _execute_job_pty(probe, on_line=on_line, broker=broker)
    return result


def run_parallel(
    updaters: list[Updater],
    max_workers: int,
    console: Console,
    dashboard: JobDashboard,
    *,
    background: bool = False,
    broker: PasswordBroker | None = None,
) -> list[JobResult]:
    """Run updaters in parallel, showing per-job live progress rows."""
    active_updaters: list[Updater] = []

    for updater in updaters:
        if updater.check():
            active_updaters.append(updater)

    if not active_updaters:
        return []

    results: list[JobResult] = []

    for updater in active_updaters:
        dashboard.register(updater.label)

    def _make_job_runner(updater: Updater) -> Callable[[], JobResult]:
        label = updater.label

        def _run() -> JobResult:
            dashboard.start(label)
            result = _execute_job(
                updater,
                on_line=lambda l: dashboard.line(label, l),
                on_command=lambda cmd: dashboard.line(label, f"$ {cmd}"),
                on_process_start=lambda pid: dashboard.process(label, pid),
                broker=broker,
            )
            dashboard.complete(label, result)
            return result

        return _run

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_make_job_runner(u)): u for u in active_updaters}
        # A plain `as_completed(futures)` parks the main thread in an
        # unbounded wait; Python only checks for pending signals on the main
        # thread, so if a worker blocks on a password prompt, Ctrl+C is
        # swallowed indefinitely. Polling with a short timeout gives the
        # interpreter loop — and SIGINT — a chance to run periodically.
        pending = set(futures)
        while pending:
            done, pending = concurrent.futures.wait(pending, timeout=0.2, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                results.append(future.result())

    order = {u.label: i for i, u in enumerate(active_updaters)}
    results.sort(key=lambda r: order[r.label])

    return results
