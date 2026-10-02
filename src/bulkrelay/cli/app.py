from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Never

import typer
from rich.console import Console
from rich.table import Table

from bulkrelay.config.loader import ConfigLoadError, load_config, resolve_input_path
from bulkrelay.execution.engine import ExecutionEngine
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
    """Validate the full input, then execute an HTTP POST job with reliability controls."""
    try:
        config = load_config(config_path)
        input_path = resolve_input_path(config_path, config.input.file)
        summary = asyncio.run(
            ExecutionEngine().run(
                config=config,
                input_path=input_path,
                output_root=output_dir,
            )
        )
    except (ConfigLoadError, InputError, MappingError) as exc:
        _exit_with_error(exc)

    table = Table(title="BulkRelay run complete")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Records", str(summary.total))
    table.add_row("Succeeded", str(summary.succeeded))
    table.add_row("Failed", str(summary.failed))
    table.add_row("HTTP attempts", str(summary.attempts))
    table.add_row("Retried records", str(summary.retried))
    console.print(table)
    console.print(f"Report: [bold]{summary.run_directory}[/bold]")

    if summary.failed:
        raise typer.Exit(code=1)


def _exit_with_error(exc: Exception) -> Never:
    console.print(f"[bold red]Error:[/bold red] {exc}")
    raise typer.Exit(code=2) from exc


if __name__ == "__main__":
    app()
