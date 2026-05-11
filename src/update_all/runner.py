"""Sequential and parallel job runners for update-all."""

from __future__ import annotations

import concurrent.futures
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console
from rich.live import Live
from rich.text import Text

from update_all.updaters import Updater


@dataclass
class JobResult:
    """Result of a single updater job execution."""

    label: str
    exit_code: int
    output: str
    duration: float
    succeeded: bool


def run_sequential(
    updaters: list[Updater],
    console: Console,
    *,
    background: bool = False,
) -> list[JobResult]:
    """Run updaters sequentially, streaming output directly to the terminal."""
    results: list[JobResult] = []

    for updater in updaters:
        if not updater.check():
            console.print(f"[yellow][WARN][/yellow] {updater.label} not found — skipping")
            continue

        console.rule(f"[bold]{updater.label}[/bold] {updater.description}")

        exit_code = 0
        start = time.monotonic()

        for cmd in updater.commands:
            if background and updater.needs_sudo:
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
            )
        )

    return results


def _execute_job(updater: Updater) -> JobResult:
    """Execute all commands for a single updater, capturing combined output."""
    output_parts: list[str] = []
    exit_code = 0
    start = time.monotonic()

    for cmd in updater.commands:
        proc = subprocess.run(
            ["bash", "-lc", cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.stdout:
            output_parts.append(proc.stdout)
        if proc.stderr:
            output_parts.append(proc.stderr)
        if exit_code == 0 and proc.returncode != 0:
            exit_code = proc.returncode

    duration = time.monotonic() - start
    return JobResult(
        label=updater.label,
        exit_code=exit_code,
        output="".join(output_parts),
        duration=duration,
        succeeded=exit_code == 0,
    )


def run_parallel(
    updaters: list[Updater],
    max_workers: int,
    console: Console,
    *,
    background: bool = False,
) -> list[JobResult]:
    """Run updaters in parallel with captured output, showing live progress."""
    active_updaters: list[Updater] = []

    for updater in updaters:
        if updater.check():
            active_updaters.append(updater)
        else:
            console.print(f"[yellow][WARN][/yellow] {updater.label} not found — skipping")

    if not active_updaters:
        return []

    state: dict[str, str] = {u.label: "queued" for u in active_updaters}
    lock = threading.Lock()
    results: list[JobResult] = []

    def make_panel() -> Text:
        with lock:
            running = [k for k, v in state.items() if v == "running"]
            done = [k for k, v in state.items() if v == "done"]
            failed = [k for k, v in state.items() if v == "failed"]
        n_done = len(done) + len(failed)
        n_total = len(active_updaters)
        parts = []
        if running:
            parts.append(f"Running: {' '.join(running)}")
        parts.append(f"({n_done}/{n_total} done  ok:{len(done)}  fail:{len(failed)})")
        return Text("[PAR] " + " ".join(parts))

    def _make_job_runner(updater: Updater) -> Callable[[], JobResult]:
        def _run() -> JobResult:
            with lock:
                state[updater.label] = "running"
            return _execute_job(updater)
        return _run

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_make_job_runner(u)): u for u in active_updaters}
        if background:
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        else:
            with Live(make_panel(), console=console, refresh_per_second=4, transient=True) as live:
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    with lock:
                        state[result.label] = "done" if result.succeeded else "failed"
                    live.update(make_panel())
                    results.append(result)

    order = {u.label: i for i, u in enumerate(active_updaters)}
    results.sort(key=lambda r: order[r.label])

    for result in results:
        console.rule(f"[bold]{result.label}[/bold]")
        if result.output.strip():
            console.print(result.output.rstrip())
        else:
            console.print("[dim](no output)[/dim]")
        if result.succeeded:
            console.print(f"[green][OK][/green] {result.label} done ({result.duration:.1f}s)")
        else:
            console.print(f"[yellow][WARN][/yellow] {result.label} failed (exit {result.exit_code})")

    return results
