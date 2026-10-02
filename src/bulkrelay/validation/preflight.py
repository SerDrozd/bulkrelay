from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bulkrelay.config.models import JobConfig
from bulkrelay.input.factory import open_record_source
from bulkrelay.mapping.request_builder import build_json_body, validate_columns, validate_json_body


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    input_format: str
    records: int
    mapped_fields: int


def preflight(config: JobConfig, input_path: Path) -> ValidationSummary:
    """Validate the complete input and mapping without making HTTP requests."""

    source = open_record_source(input_path)
    columns = source.columns()
    if columns is not None:
        validate_columns(config.request, columns)

    record_count = 0
    for record in source.records():
        body = build_json_body(config.request, record)
        validate_json_body(body, record.row_number)
        record_count += 1

    return ValidationSummary(
        input_format=source.format_name,
        records=record_count,
        mapped_fields=len(config.request.json_body),
    )
