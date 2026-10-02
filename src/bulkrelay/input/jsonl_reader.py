from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from bulkrelay.input.base import InputError
from bulkrelay.input.models import InputRecord


class JsonlInputError(InputError):
    """Raised when JSONL/NDJSON input is malformed."""


class JsonlRecordSource:
    format_name = "JSONL"

    def __init__(self, path: Path) -> None:
        self.path = path

    def columns(self) -> None:
        # JSONL records may legitimately have different keys, so mappings are
        # checked per record during preflight instead of assuming a fixed schema.
        return None

    def records(self) -> Iterator[InputRecord]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    text = raw_line.strip()
                    if not text:
                        raise JsonlInputError(
                            f"JSONL line {line_number} is blank; "
                            "each line must contain one JSON object"
                        )
                    try:
                        value: Any = json.loads(text, parse_constant=_reject_nonstandard_constant)
                    except json.JSONDecodeError as exc:
                        raise JsonlInputError(
                            f"Invalid JSON on line {line_number}: {exc.msg} "
                            f"(column {exc.colno})"
                        ) from exc
                    except ValueError as exc:
                        raise JsonlInputError(
                            f"Invalid JSON on line {line_number}: {exc}"
                        ) from exc
                    if not isinstance(value, dict):
                        raise JsonlInputError(
                            f"JSONL line {line_number} must contain a JSON object, "
                            f"got {type(value).__name__}"
                        )
                    yield InputRecord(row_number=line_number, values=value)
        except UnicodeDecodeError as exc:
            raise JsonlInputError(f"JSONL is not valid UTF-8: {self.path}") from exc
        except OSError as exc:
            raise JsonlInputError(f"Could not read JSONL file: {self.path}") from exc


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError(f"non-standard numeric constant {value!r} is not allowed")
