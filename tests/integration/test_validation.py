from __future__ import annotations

from pathlib import Path

import pytest

from bulkrelay.config.models import JobConfig
from bulkrelay.input.jsonl_reader import JsonlInputError
from bulkrelay.mapping.request_builder import MappingError
from bulkrelay.validation.preflight import preflight


def make_config(input_path: Path) -> JobConfig:
    return JobConfig.model_validate(
        {
            "version": 1,
            "input": {"file": str(input_path)},
            "request": {
                "method": "POST",
                "url": "http://test/users",
                "json": {
                    "email": {"from": "email"},
                    "active": {"from": "active"},
                },
            },
        }
    )


def test_preflight_validates_complete_jsonl_file(tmp_path: Path) -> None:
    path = tmp_path / "users.jsonl"
    path.write_text(
        '{"email":"a@example.com","active":true}\n'
        '{"email":"b@example.com","active":false}\n',
        encoding="utf-8",
    )

    summary = preflight(make_config(path), path)

    assert summary.input_format == "JSONL"
    assert summary.records == 2
    assert summary.mapped_fields == 2


def test_preflight_catches_late_jsonl_shape_drift(tmp_path: Path) -> None:
    path = tmp_path / "users.jsonl"
    path.write_text(
        '{"email":"a@example.com","active":true}\n'
        '{"email":"b@example.com"}\n',
        encoding="utf-8",
    )

    with pytest.raises(MappingError, match="Input record 2.*active"):
        preflight(make_config(path), path)


def test_preflight_catches_malformed_json_before_execution(tmp_path: Path) -> None:
    path = tmp_path / "users.jsonl"
    path.write_text(
        '{"email":"a@example.com","active":true}\n'
        '{bad json}\n',
        encoding="utf-8",
    )

    with pytest.raises(JsonlInputError, match="line 2"):
        preflight(make_config(path), path)
