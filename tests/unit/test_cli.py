from typer.testing import CliRunner

from bulkrelay.cli.app import app


runner = CliRunner()


def test_cli_exposes_run_subcommand() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.stdout
