from __future__ import annotations

import pytest

from bulkrelay.config.models import RequestConfig
from bulkrelay.input.models import InputRecord
from bulkrelay.mapping.request_builder import MappingError, build_json_body, validate_columns


def request_config(source_field: str = "email") -> RequestConfig:
    return RequestConfig.model_validate(
        {
            "method": "POST",
            "url": "https://api.example.com/users",
            "json": {
                "email": {"from": source_field},
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


def test_build_json_body_preserves_json_types() -> None:
    record = InputRecord(row_number=7, values={"active": True, "score": 42, "tags": ["a", "b"]})
    config = RequestConfig.model_validate(
        {
            "url": "https://api.example.com/users",
            "json": {
                "active": {"from": "active"},
                "score": {"from": "score"},
                "tags": {"from": "tags"},
            },
        }
    )

    assert build_json_body(config, record) == {"active": True, "score": 42, "tags": ["a", "b"]}


def test_validate_columns_reports_missing_column_with_suggestion() -> None:
    with pytest.raises(MappingError) as exc_info:
        validate_columns(request_config("customer_email"), ["customer_id", "email"])

    message = str(exc_info.value)
    assert "customer_email" in message
    assert "Did you mean 'email'?" in message


def test_build_json_body_reports_record_number_for_shape_drift() -> None:
    record = InputRecord(row_number=4, values={"name": "Alice"})

    with pytest.raises(MappingError, match="Input record 4"):
        build_json_body(request_config(), record)


def test_preflight_json_validation_rejects_non_serializable_constant() -> None:
    from datetime import date

    from bulkrelay.mapping.request_builder import validate_json_body

    with pytest.raises(MappingError, match="not valid JSON"):
        validate_json_body({"created_on": date(2026, 10, 2)}, row_number=1)
