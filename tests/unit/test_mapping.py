from __future__ import annotations

import pytest

from bulkrelay.config.models import RequestConfig
from bulkrelay.input.csv_reader import InputRecord
from bulkrelay.mapping.request_builder import MappingError, build_json_body, validate_columns


def request_config() -> RequestConfig:
    return RequestConfig.model_validate(
        {
            "method": "POST",
            "url": "https://api.example.com/users",
            "json": {
                "email": {"from": "email"},
                "source": {"value": "migration"},
            },
        }
    )


def test_build_json_body_maps_columns_and_constants() -> None:
    record = InputRecord(row_number=1, values={"email": "alice@example.com"})

    assert build_json_body(request_config(), record) == {
        "email": "alice@example.com",
        "source": "migration",
    }


def test_validate_columns_reports_missing_column() -> None:
    with pytest.raises(MappingError, match="Missing input column.*email"):
        validate_columns(request_config(), ["name"])
