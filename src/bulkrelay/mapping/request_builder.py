from __future__ import annotations

import json
from difflib import get_close_matches
from typing import Any

from bulkrelay.config.models import RequestConfig
from bulkrelay.input.models import InputRecord


class MappingError(ValueError):
    """Raised when configured mappings cannot be applied to the input."""


def required_columns(config: RequestConfig) -> set[str]:
    return {
        mapping.from_column
        for mapping in config.json_body.values()
        if mapping.from_column is not None
    }


def validate_columns(config: RequestConfig, columns: list[str]) -> None:
    missing = sorted(required_columns(config) - set(columns))
    if not missing:
        return

    details = [_missing_column_message(column, columns) for column in missing]
    available = ", ".join(columns) if columns else "<none>"
    raise MappingError(
        "Input schema does not satisfy the request mapping:\n"
        + "\n".join(f"- {detail}" for detail in details)
        + f"\nAvailable columns: {available}"
    )


def build_json_body(config: RequestConfig, record: InputRecord) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for output_name, mapping in config.json_body.items():
        if mapping.from_column is None:
            body[output_name] = mapping.value
            continue

        if mapping.from_column not in record.values:
            available = list(record.values)
            detail = _missing_column_message(mapping.from_column, available)
            raise MappingError(f"Input record {record.row_number}: {detail}")
        body[output_name] = record.values[mapping.from_column]
    return body


def validate_json_body(body: dict[str, Any], row_number: int) -> None:
    """Ensure the materialized body can be encoded as standards-compliant JSON."""

    try:
        json.dumps(body, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MappingError(
            f"Input record {row_number}: mapped request body is not valid JSON: {exc}"
        ) from exc


def _missing_column_message(column: str, available: list[str]) -> str:
    normalized = column.casefold()
    token_matches = [
        candidate
        for candidate in available
        if candidate.casefold() in normalized.replace("-", "_").split("_")
    ]
    if token_matches:
        match = token_matches[0]
    else:
        matches = get_close_matches(column, available, n=1, cutoff=0.6)
        match = matches[0] if matches else None

    suggestion = f" Did you mean {match!r}?" if match else ""
    return f"missing mapped field {column!r}.{suggestion}"
