"""Sequential and parallel job runners for update-all."""

from __future__ import annotations

import concurrent.futures
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TaskID, TextColumn, TimeElapsedColumn

from update_all.updaters import Updater


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
            console.print(f"[yellow]⚠[/yellow] {updater.description or updater.label} not found — skipping")
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


def _execute_job(
    updater: Updater,
    on_line: Callable[[str], None] = lambda _: None,
) -> JobResult:
    """Execute all commands for a single updater, streaming output line-by-line."""
    output_parts: list[str] = []
    exit_code = 0
    start = time.monotonic()

    for cmd in updater.commands:
        proc = subprocess.Popen(
            ["bash", "-lc", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip()
            output_parts.append(line)
            on_line(line)
        proc.wait()
        if exit_code == 0 and proc.returncode != 0:
            exit_code = proc.returncode

    duration = time.monotonic() - start
    return JobResult(
        label=updater.label,
        exit_code=exit_code,
        output="\n".join(output_parts),
        duration=duration,
        succeeded=exit_code == 0,
        description=updater.description,
    )


def run_parallel(
    updaters: list[Updater],
    max_workers: int,
    console: Console,
    *,
    background: bool = False,
) -> list[JobResult]:
    """Run updaters in parallel, showing per-job live progress rows."""
    active_updaters: list[Updater] = []

    for updater in updaters:
        if updater.check():
            active_updaters.append(updater)
        else:
            console.print(f"[yellow]⚠[/yellow] {updater.description or updater.label} not found — skipping")

    if not active_updaters:
        return []

    results: list[JobResult] = []

    progress = Progress(
        SpinnerColumn(finished_text=" "),
        TextColumn("[bold]{task.description:<10}[/bold]"),
        TimeElapsedColumn(),
        TextColumn("[dim]{task.fields[last_line]}[/dim]"),
        console=console,
        transient=False,
        disable=background,
    )

    task_ids: dict[str, TaskID] = {}

    with progress:
        for updater in active_updaters:
            tid = progress.add_task(updater.label, total=1, last_line="")
            task_ids[updater.label] = tid

        def _make_job_runner(updater: Updater) -> Callable[[], JobResult]:
            def _on_line(line: str) -> None:
                progress.update(task_ids[updater.label], last_line=line[:70])

            def _run() -> JobResult:
                result = _execute_job(updater, on_line=_on_line)
                icon = "[green]✓[/green]" if result.succeeded else "[red]✗[/red]"
                progress.update(
                    task_ids[updater.label],
                    advance=1,
                    description=f"{icon} {updater.label}",
                )
                return result

            return _run

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_make_job_runner(u)): u for u in active_updaters}
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

    order = {u.label: i for i, u in enumerate(active_updaters)}
    results.sort(key=lambda r: order[r.label])

    for result in results:
        console.rule(f"[bold]{result.label}[/bold] {result.description}")
        if result.output.strip():
            console.print(result.output.rstrip(), highlight=False)
        else:
            console.print("[dim](no output)[/dim]")
        if result.succeeded:
            console.print(f"[green]✓[/green] {result.label} done ({fmt_duration(result.duration)})")
        else:
            console.print(f"[red]✗[/red] {result.label} failed (exit {result.exit_code})")

    return results
