from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from bulkrelay.cli.app import app

runner = CliRunner()


def test_cli_exposes_run_and_validate_subcommands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "validate" in result.stdout
    assert "resume" in result.stdout


def test_validate_command_preflights_without_http(tmp_path: Path) -> None:
    data_path = tmp_path / "users.jsonl"
    data_path.write_text('{"email":"alice@example.com","active":true}\n', encoding="utf-8")
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        """
version: 1
input:
  file: users.jsonl
request:
  method: POST
  url: https://api.example.com/users
  json:
    email:
      from: email
    active:
      from: active
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["validate", str(config_path)])

    assert result.exit_code == 0
    assert "BulkRelay validation" in result.stdout
    assert "passed" in result.stdout
    assert "JSONL" in result.stdout
    assert "1" in result.stdout


def test_validate_command_returns_usage_error_for_bad_mapping(tmp_path: Path) -> None:
    data_path = tmp_path / "users.csv"
    data_path.write_text("email\nalice@example.com\n", encoding="utf-8")
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        """
version: 1
input:
  file: users.csv
request:
  method: POST
  url: https://api.example.com/users
  json:
    email:
      from: customer_email
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["validate", str(config_path)])

    assert result.exit_code == 2
    assert "customer_email" in result.stdout
    assert "Did you mean 'email'?" in result.stdout
