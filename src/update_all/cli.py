"""CLI entry point for update-all."""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import sys
import time
from typing import Annotated

import typer
from rich.console import Console

from update_all import agent, idempotency, notify
from update_all.runner import JobResult, run_parallel, run_sequential
from update_all.sudo import SudoKeepalive
from update_all.updaters import Updater, all_updaters

def _fmt_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h} h {m} min" if m else f"{h} h"
    if m:
        return f"{m} min {sec} s" if sec else f"{m} min"
    return f"{sec} s"


app = typer.Typer(
    name="update-all",
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def main(argv: list[str] | None = None) -> int:
    """Entry point wired to the update-all console script."""
    try:
        result = app(standalone_mode=False, args=argv)
        if isinstance(result, int):
            return result
        return 0
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0


@app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    do_os: Annotated[bool, typer.Option("--os/--no-os", help="Include OS system updates (macOS: softwareupdate; Linux: apt full-upgrade). Requires sudo.")] = False,
    jobs: Annotated[int, typer.Option("--jobs", help="Max parallel workers")] = 0,
    only: Annotated[str | None, typer.Option("--only", help="Comma-separated labels to run exclusively")] = None,
    skip: Annotated[str | None, typer.Option("--skip", help="Comma-separated labels to skip")] = None,
    background: Annotated[bool, typer.Option("--background/--no-background", help="Background mode: log to file, skip OS updates")] = False,
    install_agent: Annotated[bool, typer.Option("--install-agent", help="Install LaunchAgent (macOS) or systemd timer (Linux) for auto-run")] = False,
    uninstall_agent: Annotated[bool, typer.Option("--uninstall-agent", help="Remove LaunchAgent (macOS) or systemd timer (Linux)")] = False,
    force: Annotated[bool, typer.Option("--force", help="Override daily idempotency check")] = False,
    no_colors: Annotated[bool, typer.Option("--no-colors", help="Disable colored output")] = False,
) -> None:
    if ctx.invoked_subcommand is not None:
        return

    use_color = not no_colors and not background
    console = Console(no_color=not use_color)

    if install_agent:
        agent.install(console)
        raise typer.Exit(0)
    if uninstall_agent:
        agent.uninstall(console)
        raise typer.Exit(0)

    if not force and idempotency.already_ran_today():
        ts = idempotency.last_ran_at()
        if ts is not None:
            now = time.time()
            age = now - ts
            remaining = idempotency.THRESHOLD_SECONDS - age
            last_dt = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            next_dt = datetime.datetime.fromtimestamp(ts + idempotency.THRESHOLD_SECONDS).strftime("%Y-%m-%d %H:%M:%S")
            console.print(
                f"[dim]Already ran in the last {_fmt_duration(idempotency.THRESHOLD_SECONDS)} — skipping.\n"
                f"The last run was {_fmt_duration(age)} ago ({last_dt}).\n"
                f"The next run will be in {_fmt_duration(remaining)} ({next_dt}).\n"
                f"Use --force to override.[/dim]"
            )
        else:
            console.print("[dim]Already ran in the last 12 h — skipping. Use --force to override.[/dim]")
        raise typer.Exit(0)

    if jobs <= 0:
        max_workers = min(os.cpu_count() or 4, 6)
    else:
        max_workers = jobs

    if background:
        do_os = False

    if not background:
        console.rule("[bold]update-all[/bold]")
        console.print(f"jobs={max_workers}  os_updates={do_os}  background={background}")

    start_ts = time.monotonic()
    keepalive: SudoKeepalive | None = None

    try:
        if do_os:
            keepalive = SudoKeepalive()
            keepalive.start()

        updaters = all_updaters()

        if only:
            only_labels = {lbl.strip().upper() for lbl in only.split(",")}
            updaters = [u for u in updaters if u.label in only_labels]

        if skip:
            skip_labels = {lbl.strip().upper() for lbl in skip.split(",")}
            updaters = [u for u in updaters if u.label not in skip_labels]

        sequential_updaters = [u for u in updaters if u.is_sequential]
        parallel_updaters   = [u for u in updaters if not u.is_sequential]

        seq_results: list[JobResult] = []
        if sequential_updaters:
            if not background:
                console.print("[bold][SEQ][/bold] Sequential phase...")
            seq_results = run_sequential(sequential_updaters, console)

        par_results: list[JobResult] = []
        if parallel_updaters:
            if not background:
                console.print("[bold][PAR][/bold] Parallel phase...")
            par_results = run_parallel(parallel_updaters, max_workers, console, background=background)

        os_results: list[JobResult] = []
        if do_os:
            if sys.platform == "darwin":
                os_commands = ["sudo softwareupdate -l", "sudo softwareupdate -ia --verbose"]
                os_description = "macOS system updates"
                os_label = "macOS"
            else:
                os_commands = ["sudo apt full-upgrade -y", "sudo apt autoremove -y"]
                os_description = "Ubuntu/Debian system updates"
                os_label = "Linux"
            os_updater = Updater(
                label="OS",
                commands=os_commands,
                check=lambda: True,
                is_sequential=True,
                description=os_description,
            )
            console.print(f"[bold][OS][/bold] Running {os_label} system updates...")
            os_results = run_sequential([os_updater], console)

        try:
            idempotency.mark_ran_today()
        except OSError as exc:
            console.print(f"[yellow][WARN][/yellow] Could not write idempotency sentinel: {exc}")

        all_results = seq_results + par_results + os_results
        ok_count   = sum(1 for r in all_results if r.succeeded)
        fail_count = sum(1 for r in all_results if not r.succeeded)
        elapsed    = time.monotonic() - start_ts

        if not background:
            console.rule()
            console.print(f"[bold]Done in {elapsed:.0f}s[/bold] — {ok_count} succeeded, {fail_count} failed")
            _print_versions(console)

        notify.send(
            "update-all",
            f"{ok_count} succeeded, {fail_count} failed — done in {elapsed:.0f}s",
            success=(fail_count == 0),
        )

        raise typer.Exit(0 if fail_count == 0 else 1)
    finally:
        if keepalive is not None:
            keepalive.stop()


@app.command()
def logs(
    no_colors: Annotated[bool, typer.Option("--no-colors", help="Disable colored output")] = False,
) -> None:
    """Display the log from the latest background run."""
    console = Console(no_color=no_colors)
    if not agent.LOG_PATH.exists():
        console.print(f"[yellow]No log file found.[/yellow] Expected: {agent.LOG_PATH}")
        console.print("[dim]Install the LaunchAgent with --install-agent to enable background logging.[/dim]")
        raise typer.Exit(1)
    content = agent.LOG_PATH.read_text()
    if not content.strip():
        console.print("[dim](log file is empty)[/dim]")
    else:
        console.print(content, end="")


def _print_versions(console: Console) -> None:
    """Print versions of detected tools."""
    tools = [
        ("brew",    ["brew", "--version"]),
        ("node",    ["node", "-v"]),
        ("npm",     ["npm", "-v"]),
        ("pnpm",    ["pnpm", "-v"]),
        ("yarn",    ["yarn", "-v"]),
        ("rustc",   ["rustc", "-V"]),
        ("go",      ["go", "version"]),
        ("python3", ["python3", "--version"]),
        ("code",    ["code", "--version"]),
        ("claude",  ["claude", "--version"]),
    ]
    console.rule("[dim]Versions[/dim]")
    for name, cmd in tools:
        if shutil.which(name) is None:
            continue
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=5)
            version_line = (result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else ""
            if version_line:
                console.print(f"[cyan][VER][/cyan] {version_line}")
        except subprocess.TimeoutExpired:
            console.print(f"[yellow][WARN][/yellow] {name} --version timed out")
