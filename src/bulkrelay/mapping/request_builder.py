from __future__ import annotations

from typing import Any

from bulkrelay.config.models import RequestConfig
from bulkrelay.input.csv_reader import InputRecord


class MappingError(ValueError):
    """Raised when configured mappings cannot be applied to the input."""


def required_columns(config: RequestConfig) -> set[str]:
    return {
        mapping.from_column
        for mapping in config.json.values()
        if mapping.from_column is not None
    }


def validate_columns(config: RequestConfig, columns: list[str]) -> None:
    missing = sorted(required_columns(config) - set(columns))
    if missing:
        joined = ", ".join(missing)
        available = ", ".join(columns)
        raise MappingError(
            f"Missing input column(s): {joined}. Available columns: {available}"
        )


def build_json_body(config: RequestConfig, record: InputRecord) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for output_name, mapping in config.json.items():
        if mapping.from_column is not None:
            body[output_name] = record.values[mapping.from_column]
        else:
            body[output_name] = mapping.value
    return body
