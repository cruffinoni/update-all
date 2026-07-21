"""CLI entry point for update-all."""

from __future__ import annotations

import datetime
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Annotated

import rich.box
import typer
try:
    from typer._click.exceptions import UsageError
except ImportError:
    from click.exceptions import UsageError
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from update_all import agent, idempotency, notify
from update_all import __version__
from update_all.commands import COMMAND_SPECS, VERSION_COMMANDS
from update_all.password import PasswordBroker
from update_all.runner import JobDashboard, JobResult, fmt_duration, run_parallel, run_sequential
from update_all.sudo import SudoKeepalive
from update_all.updaters import Updater, all_updaters


app = typer.Typer(
    name="update-all",
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


_NO_COLOR_ARGS = ("--no-colors", "--no-color", "--background")


def _color_disabled(argv: list[str] | None) -> bool:
    args = argv if argv is not None else sys.argv[1:]
    return any(arg in _NO_COLOR_ARGS for arg in args)


def main(argv: list[str] | None = None) -> int:
    """Entry point wired to the update-all console script."""
    if _color_disabled(argv):
        os.environ["NO_COLOR"] = "1"
    try:
        result = app(standalone_mode=False, args=argv)
        if isinstance(result, int):
            return result
        return 0
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0
    except UsageError as exc:
        typer.echo(f"Error: {exc.format_message()}", err=True)
        if exc.ctx is not None:
            typer.echo(exc.ctx.get_help())
        return 2


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"update-all {__version__}")
        raise typer.Exit(0)


@app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", callback=_show_version, is_eager=True, help="Show the version and exit.")] = False,
    do_os: Annotated[bool, typer.Option("--os/--no-os", help="Include OS system updates (macOS: softwareupdate; Linux: apt full-upgrade). Requires sudo.")] = False,
    jobs: Annotated[int, typer.Option("--jobs", help="Max parallel workers")] = 0,
    only: Annotated[str | None, typer.Option("--only", help="Comma-separated labels to run exclusively")] = None,
    skip: Annotated[str | None, typer.Option("--skip", help="Comma-separated labels to skip")] = None,
    background: Annotated[bool, typer.Option("--background/--no-background", help="Background mode: log to file, skip OS updates")] = False,
    install_agent: Annotated[bool, typer.Option("--install-agent", help="Install LaunchAgent (macOS) or systemd timer (Linux) for auto-run")] = False,
    uninstall_agent: Annotated[bool, typer.Option("--uninstall-agent", help="Remove LaunchAgent (macOS) or systemd timer (Linux)")] = False,
    force: Annotated[bool, typer.Option("--force", help="Override daily idempotency check")] = False,
    no_colors: Annotated[bool, typer.Option("--no-colors", "--no-color", help="Disable colored output")] = False,
) -> None:
    if ctx.invoked_subcommand is not None:
        return

    use_color = not no_colors and not background
    console = Console(no_color=None if use_color else True)

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
                f"[dim]Already ran in the last {fmt_duration(idempotency.THRESHOLD_SECONDS)} — skipping.\n"
                f"The last run was {fmt_duration(age)} ago ({last_dt}).\n"
                f"The next run will be in {fmt_duration(remaining)} ({next_dt}).\n"
                f"Use --force to override.[/dim]"
            )
        else:
            console.print(f"[dim]Already ran in the last {fmt_duration(idempotency.THRESHOLD_SECONDS)} — skipping. Use --force to override.[/dim]")
        raise typer.Exit(0)

    if jobs <= 0:
        max_workers = min(os.cpu_count() or 4, 6)
    else:
        max_workers = jobs

    if background:
        do_os = False

    if not background:
        os_flag = "  ·  os on" if do_os else ""
        console.print(f"[bold]update-all[/bold]  [dim]·  {max_workers} workers{os_flag}[/dim]")
        console.print()

    start_ts = time.monotonic()
    keepalive: SudoKeepalive | None = None
    try:
        updaters = all_updaters()

        if not do_os:
            updaters = [u for u in updaters if not u.requires_os]

        if only:
            only_labels = {lbl.strip().upper() for lbl in only.split(",")}
            updaters = [u for u in updaters if u.label in only_labels]

        if skip:
            skip_labels = {lbl.strip().upper() for lbl in skip.split(",")}
            updaters = [u for u in updaters if u.label not in skip_labels]

        sequential_updaters = [u for u in updaters if u.is_sequential]
        parallel_updaters   = [u for u in updaters if not u.is_sequential]

        os_spec = None
        if do_os:
            os_spec = COMMAND_SPECS["softwareupdate" if sys.platform == "darwin" else "apt"]

        dashboard = JobDashboard(console, disabled=background)
        broker = PasswordBroker(pause=dashboard.pause)

        needs_sudo = (
            (os_spec is not None and os_spec.available())
            or (not background and any(u.needs_sudo for u in updaters if u.check()))
        )

        seq_results: list[JobResult] = []
        par_results: list[JobResult] = []
        os_results: list[JobResult] = []

        with dashboard:
            if needs_sudo:
                console.print("[bold]⚠  sudo required — enter your password once:[/bold]")
                # sudo timestamps are normally scoped to a tty. Updaters run in
                # their own PTYs, so authenticate through the shared broker
                # rather than `sudo -v` on the parent terminal.
                broker.get_password([], reprompt=False)

            if sequential_updaters:
                seq_results = run_sequential(sequential_updaters, console, dashboard, background=background, broker=broker)

            if parallel_updaters:
                par_results = run_parallel(parallel_updaters, max_workers, console, dashboard, background=background, broker=broker)

            if do_os and os_spec is not None and os_spec.available():
                if sys.platform == "darwin":
                    os_commands = ["sudo softwareupdate -l", "sudo softwareupdate -ia --verbose"]
                else:
                    os_commands = ["sudo apt full-upgrade -y", "sudo apt autoremove -y"]
                os_results = run_sequential(
                    [
                        Updater(
                            label="OS",
                            description="system updates",
                            check=os_spec.available,
                            is_sequential=True,
                            needs_sudo=True,
                            commands=os_commands,
                            error_lines=20,
                        )
                    ],
                    console,
                    dashboard,
                    broker=broker,
                )

        all_results = seq_results + par_results + os_results
        _print_failures(all_results, console)

        try:
            idempotency.mark_ran_today()
        except OSError as exc:
            console.print(f"[yellow]⚠[/yellow] Could not write idempotency sentinel: {exc}")
        ok_count   = sum(1 for r in all_results if r.succeeded)
        fail_count = sum(1 for r in all_results if not r.succeeded)
        elapsed    = time.monotonic() - start_ts

        if not background:
            _print_summary(all_results, elapsed, console)
            _print_versions(console)

        notify.send(
            "update-all",
            f"{ok_count} succeeded, {fail_count} failed — done in {fmt_duration(elapsed)}",
            success=(fail_count == 0),
        )

        raise typer.Exit(0 if fail_count == 0 else 1)
    finally:
        if keepalive is not None:
            keepalive.stop()


@app.command("update")
def self_update() -> None:
    """Update update-all itself from PyPI using uv."""
    uv = shutil.which("uv")
    if uv is None:
        typer.echo(
            "Error: uv is required to update update-all. "
            "Install uv, then run 'update-all update' again.",
            err=True,
        )
        raise typer.Exit(1)

    result = subprocess.run(
        [uv, "tool", "install", "update-all@latest", "--force"],
        check=False,
    )
    if result.returncode != 0:
        raise typer.Exit(result.returncode)

    typer.echo("update-all updated successfully.")


@app.command()
def logs(
    no_colors: Annotated[bool, typer.Option("--no-colors", "--no-color", help="Disable colored output")] = False,
) -> None:
    """Display the log from the latest background run."""
    console = Console(no_color=True if no_colors else None)
    if not agent.LOG_PATH.exists():
        console.print(f"[yellow]⚠[/yellow] No log file found. Expected: {agent.LOG_PATH}")
        if sys.platform == "darwin":
            console.print("[dim]Install the LaunchAgent with --install-agent to enable background logging.[/dim]")
        else:
            console.print("[dim]Install the systemd timer with --install-agent to enable background logging.[/dim]")
        raise typer.Exit(1)
    content = agent.LOG_PATH.read_text()
    if not content.strip():
        console.print("[dim](log file is empty)[/dim]")
    else:
        console.print(content, end="", highlight=False)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _extract_notes(result: JobResult) -> str:
    """Parse result.output for a human-readable one-line summary."""
    if not result.output:
        return "—"
    out = result.output
    label = result.label
    if label == "BREW":
        parts = []
        m = re.search(r"Upgrading (\d+) (formulae?)", out)
        if m:
            parts.append(f"{m.group(1)} {m.group(2)}")
        m = re.search(r"Upgrading (\d+) (casks?)", out)
        if m:
            parts.append(f"{m.group(1)} {m.group(2)}")
        return ", ".join(parts) or "no upgrades"
    if label == "APT":
        m = re.search(r"(\d+) upgraded", out)
        return f"{m.group(1)} upgraded" if m else "no upgrades"
    if label == "NPM":
        m = re.search(r"changed (\d+) packages?", out)
        if m:
            n = int(m.group(1))
            return f"{_plural(n, 'package')} changed"
        return "no changes"
    if label == "PNPM":
        m = re.search(r"(\d+) packages? updated", out)
        if m:
            n = int(m.group(1))
            return f"{_plural(n, 'package')} updated"
        return "no changes"
    if label == "PIPX":
        count = sum(1 for line in out.splitlines() if "upgraded" in line.lower())
        return _plural(count, "package") + " upgraded" if count else "no upgrades"
    if not result.succeeded:
        for line in out.splitlines():
            if "error:" in line.lower():
                return line.strip()
    lines = [line for line in out.splitlines() if line.strip()]
    return f"{len(lines)} lines" if lines else "—"


def _print_failures(results: list[JobResult], console: Console) -> None:
    failed = [r for r in results if not r.succeeded]
    if not failed:
        return
    console.print()
    for result in failed:
        console.print(f"[red]✗[/red] [bold]{result.label}[/bold] — exit {result.exit_code}")
        if result.output:
            tail = result.output.splitlines()[-result.error_lines:]
            for line in tail:
                console.print(f"  [dim]{escape(line)}[/dim]", highlight=False)


def _print_summary(results: list[JobResult], elapsed: float, console: Console) -> None:
    """Print a table summarising all job results."""
    table = Table(
        show_header=True,
        header_style="bold",
        show_edge=True,
        box=rich.box.SIMPLE_HEAD,
    )
    table.add_column("", justify="center", width=2, no_wrap=True)
    table.add_column("Tool", style="bold", no_wrap=True)
    table.add_column("Time", justify="right", no_wrap=True)
    table.add_column("Notes")
    for result in results:
        icon = "[green]✓[/green]" if result.succeeded else "[red]✗[/red]"
        table.add_row(icon, result.label, fmt_duration(result.duration), _extract_notes(result))
    console.print()
    console.print(table)
    ok = sum(1 for r in results if r.succeeded)
    fail = sum(1 for r in results if not r.succeeded)
    status = "[green]✓[/green]" if fail == 0 else "[red]✗[/red]"
    console.print(f"{status}  {ok} succeeded  ·  {fail} failed  ·  {fmt_duration(elapsed)}")


def _print_versions(console: Console) -> None:
    """Print versions of detected tools."""
    console.print()
    console.print("[dim]Versions[/dim]")
    for spec in VERSION_COMMANDS:
        if not spec.available():
            continue
        name = spec.executable
        try:
            result = subprocess.run(
                spec.version_command(), capture_output=True, text=True, check=False, timeout=5
            )
            version_line = (result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else ""
            if version_line:
                console.print(f"[dim]{name}[/dim]  {version_line}", highlight=False)
        except subprocess.TimeoutExpired:
            console.print(f"[yellow]⚠[/yellow] {name} --version timed out")
