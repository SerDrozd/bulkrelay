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
