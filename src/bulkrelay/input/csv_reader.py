from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


class CsvInputError(ValueError):
    """Raised when CSV input is invalid for a BulkRelay job."""


@dataclass(frozen=True, slots=True)
class InputRecord:
    row_number: int
    values: dict[str, str]


class CsvRecordSource:
    def __init__(self, path: Path) -> None:
        self.path = path

    def columns(self) -> list[str]:
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    raise CsvInputError(f"CSV has no header row: {self.path}")
                return list(reader.fieldnames)
        except OSError as exc:
            raise CsvInputError(f"Could not read CSV file: {self.path}") from exc

    def records(self) -> Iterator[InputRecord]:
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    raise CsvInputError(f"CSV has no header row: {self.path}")
                for row_number, row in enumerate(reader, start=1):
                    if None in row:
                        raise CsvInputError(
                            f"Row {row_number} has more values than the CSV header defines"
                        )
                    yield InputRecord(
                        row_number=row_number,
                        values={key: value or "" for key, value in row.items()},
                    )
        except OSError as exc:
            raise CsvInputError(f"Could not read CSV file: {self.path}") from exc
