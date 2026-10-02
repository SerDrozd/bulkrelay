from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from bulkrelay.config.loader import ConfigLoadError, load_config, resolve_input_path
from bulkrelay.execution.engine import ExecutionEngine
from bulkrelay.input.csv_reader import CsvInputError
from bulkrelay.mapping.request_builder import MappingError

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Reliable bulk HTTP jobs from flat files.",
)
console = Console()


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
    """Run a CSV-to-HTTP POST job and write a durable result report."""
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
    except (ConfigLoadError, CsvInputError, MappingError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=2) from exc

    table = Table(title="BulkRelay run complete")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Records", str(summary.total))
    table.add_row("Succeeded", str(summary.succeeded))
    table.add_row("Failed", str(summary.failed))
    console.print(table)
    console.print(f"Report: [bold]{summary.run_directory}[/bold]")

    if summary.failed:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
