from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from types import FrameType
from typing import Never

import typer
from rich.console import Console
from rich.table import Table

from bulkrelay.config.loader import ConfigLoadError, load_config, resolve_input_path
from bulkrelay.config.models import JobConfig
from bulkrelay.execution.engine import ExecutionEngine
from bulkrelay.execution.models import RunSummary
from bulkrelay.execution.shutdown import ShutdownController, ShutdownRequest
from bulkrelay.input.base import InputError
from bulkrelay.mapping.request_builder import MappingError
from bulkrelay.validation.preflight import preflight

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Reliable bulk HTTP jobs from flat files.",
)
console = Console()


@app.callback()
def main() -> None:
    """Run reliable bulk HTTP jobs from flat files."""


@app.command()
def validate(
    config_path: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Path to a BulkRelay YAML job config.",
    ),
) -> None:
    """Validate config, input syntax, and every record mapping without HTTP calls."""
    try:
        config = load_config(config_path)
        input_path = resolve_input_path(config_path, config.input.file)
        summary = preflight(config, input_path)
    except (ConfigLoadError, InputError, MappingError) as exc:
        _exit_with_error(exc)

    table = Table(title="BulkRelay validation passed")
    table.add_column("Check")
    table.add_column("Value", justify="right")
    table.add_row("Input format", summary.input_format)
    table.add_row("Records", str(summary.records))
    table.add_row("Mapped fields", str(summary.mapped_fields))
    console.print(table)


@app.command()
def run(
    config_path: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Path to a BulkRelay YAML job config.",
    ),
    output_dir: Path = typer.Option(
        Path(".bulkrelay/runs"),
        "--output-dir",
        help="Directory where run reports are written.",
    ),
) -> None:
    """Validate the full input, then execute a bounded concurrent HTTP POST job."""
    try:
        config = load_config(config_path)
        input_path = resolve_input_path(config_path, config.input.file)
        summary = asyncio.run(
            _run_with_interrupts(
                config=config,
                input_path=input_path,
                output_dir=output_dir,
            )
        )
    except (ConfigLoadError, InputError, MappingError) as exc:
        _exit_with_error(exc)

    _print_run_summary(summary)

    if summary.stopped_early:
        if summary.forced:
            console.print(
                "[bold red]Forced stop:[/bold red] in-flight requests were cancelled. "
                "Remote side effects may be ambiguous."
            )
        else:
            console.print(
                "[yellow]Stopped safely after finishing in-flight records. "
                "No new records were started after the interrupt.[/yellow]"
            )
        raise typer.Exit(code=130)

    if summary.failed:
        raise typer.Exit(code=1)


async def _run_with_interrupts(
    *,
    config: JobConfig,
    input_path: Path,
    output_dir: Path,
) -> RunSummary:
    shutdown = ShutdownController()
    loop = asyncio.get_running_loop()
    previous_handler = signal.getsignal(signal.SIGINT)

    def handle_sigint(_signum: int, _frame: FrameType | None) -> None:
        request = shutdown.request_stop()
        if request is ShutdownRequest.GRACEFUL:
            message = (
                "[yellow]Interrupt received: stopping new records and waiting for "
                "in-flight requests. Press Ctrl+C again to force stop.[/yellow]"
            )
        else:
            message = "[red]Second interrupt received: cancelling in-flight requests.[/red]"
        loop.call_soon_threadsafe(console.print, message)

    signal.signal(signal.SIGINT, handle_sigint)
    try:
        return await ExecutionEngine().run(
            config=config,
            input_path=input_path,
            output_root=output_dir,
            shutdown=shutdown,
        )
    finally:
        signal.signal(signal.SIGINT, previous_handler)


def _print_run_summary(summary: RunSummary) -> None:
    title = "BulkRelay run stopped" if summary.stopped_early else "BulkRelay run complete"
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Input records", str(summary.input_total))
    table.add_row("Processed", str(summary.total))
    table.add_row("Unprocessed", str(summary.unprocessed))
    table.add_row("Succeeded", str(summary.succeeded))
    table.add_row("Failed", str(summary.failed))
    table.add_row("HTTP attempts", str(summary.attempts))
    table.add_row("Retried records", str(summary.retried))
    console.print(table)
    console.print(f"Report: [bold]{summary.run_directory}[/bold]")


def _exit_with_error(exc: Exception) -> Never:
    console.print(f"[bold red]Error:[/bold red] {exc}")
    raise typer.Exit(code=2) from exc


if __name__ == "__main__":
    app()
