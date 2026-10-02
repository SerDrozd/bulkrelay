from __future__ import annotations

from pathlib import Path

import pytest

from bulkrelay.config.loader import ConfigLoadError, load_config


def test_load_config_parses_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        """
version: 1
input:
  file: customers.csv
request:
  method: POST
  url: https://api.example.com/users
  json:
    email:
      from: email
    source:
      value: import
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.version == 1
    assert config.request.method == "POST"
    assert config.request.json_body["email"].from_column == "email"
    assert config.request.json_body["source"].value == "import"


def test_mapping_requires_exactly_one_source(tmp_path: Path) -> None:
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        """
version: 1
input:
  file: customers.csv
request:
  method: POST
  url: https://api.example.com/users
  json:
    email:
      from: email
      value: duplicate
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match="exactly one"):
        load_config(config_path)


def test_config_rejects_unknown_fields_with_readable_path(tmp_path: Path) -> None:
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        """
version: 1
input:
  file: customers.csv
request:
  method: POST
  url: https://api.example.com/users
  timeout: 10
  json:
    email:
      from: email
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError) as exc_info:
        load_config(config_path)

    assert "request.timeout: Unexpected field" in str(exc_info.value)


def test_config_rejects_empty_json_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        """
version: 1
input:
  file: customers.csv
request:
  method: POST
  url: https://api.example.com/users
  json: {}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match=r"request\.json"):
        load_config(config_path)


def test_config_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        """
version: 1
input:
  file: customers.csv
request:
  method: POST
  url: https://api.example.com/first
  url: https://api.example.com/second
  json:
    email:
      from: email
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match="duplicate key 'url'"):
        load_config(config_path)


def test_reliability_defaults_are_safe_and_bounded(tmp_path: Path) -> None:
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        """
version: 1
input:
  file: customers.csv
request:
  method: POST
  url: https://api.example.com/users
  json:
    email:
      from: email
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.retry.max_attempts == 1
    assert 429 in config.retry.statuses
    assert 503 in config.retry.statuses
    assert config.execution.timeout.read_seconds == 30.0
    assert config.execution.rate_limit is None


def test_config_rejects_invalid_retry_status(tmp_path: Path) -> None:
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        """
version: 1
input:
  file: customers.csv
request:
  method: POST
  url: https://api.example.com/users
  json:
    email:
      from: email
retry:
  statuses: [200, 503]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match="400-599"):
        load_config(config_path)


def test_config_rejects_backoff_max_below_initial(tmp_path: Path) -> None:
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        """
version: 1
input:
  file: customers.csv
request:
  method: POST
  url: https://api.example.com/users
  json:
    email:
      from: email
retry:
  initial_backoff_seconds: 5
  max_backoff_seconds: 2
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match="max_backoff_seconds"):
        load_config(config_path)


def test_execution_concurrency_defaults_to_one(tmp_path: Path) -> None:
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        """
version: 1
input:
  file: customers.csv
request:
  method: POST
  url: https://api.example.com/users
  json:
    email:
      from: email
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.execution.concurrency == 1


def test_config_rejects_unbounded_concurrency(tmp_path: Path) -> None:
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        """
version: 1
input:
  file: customers.csv
request:
  method: POST
  url: https://api.example.com/users
  json:
    email:
      from: email
execution:
  concurrency: 101
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match=r"execution\.concurrency"):
        load_config(config_path)
