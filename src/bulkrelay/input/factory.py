from __future__ import annotations

from pathlib import Path

from bulkrelay.input.base import InputError, RecordSource
from bulkrelay.input.csv_reader import CsvRecordSource
from bulkrelay.input.jsonl_reader import JsonlRecordSource


_SUPPORTED_EXTENSIONS: dict[str, type[CsvRecordSource] | type[JsonlRecordSource]] = {
    ".csv": CsvRecordSource,
    ".jsonl": JsonlRecordSource,
    ".ndjson": JsonlRecordSource,
}


def open_record_source(path: Path) -> RecordSource:
    if not path.exists():
        raise InputError(f"Input file does not exist: {path}")
    if not path.is_file():
        raise InputError(f"Input path is not a file: {path}")

    source_type = _SUPPORTED_EXTENSIONS.get(path.suffix.lower())
    if source_type is None:
        supported = ", ".join(sorted(_SUPPORTED_EXTENSIONS))
        suffix = path.suffix or "<none>"
        raise InputError(
            f"Unsupported input extension {suffix!r} for {path.name}. Supported: {supported}"
        )
    return source_type(path)
