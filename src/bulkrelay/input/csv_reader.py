from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from bulkrelay.input.base import InputError
from bulkrelay.input.models import InputRecord


class CsvInputError(InputError):
    """Raised when CSV input is invalid for a BulkRelay job."""


class CsvRecordSource:
    format_name = "CSV"

    def __init__(self, path: Path) -> None:
        self.path = path

    def columns(self) -> list[str]:
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                try:
                    header = next(reader)
                except StopIteration as exc:
                    raise CsvInputError(f"CSV is empty and has no header row: {self.path}") from exc
                return _validate_header(header, self.path)
        except UnicodeDecodeError as exc:
            raise CsvInputError(f"CSV is not valid UTF-8: {self.path}") from exc
        except csv.Error as exc:
            raise CsvInputError(f"Invalid CSV syntax in {self.path}: {exc}") from exc
        except OSError as exc:
            raise CsvInputError(f"Could not read CSV file: {self.path}") from exc

    def records(self) -> Iterator[InputRecord]:
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    raise CsvInputError(f"CSV has no header row: {self.path}")
                columns = _validate_header(list(reader.fieldnames), self.path)

                for row_number, row in enumerate(reader, start=1):
                    if None in row:
                        raise CsvInputError(
                            f"CSV row {row_number} has more values than the header defines"
                        )
                    missing_values = [column for column in columns if row.get(column) is None]
                    if missing_values:
                        joined = ", ".join(missing_values)
                        raise CsvInputError(
                            f"CSV row {row_number} has fewer values than the header defines; "
                            f"missing value(s) for: {joined}"
                        )
                    yield InputRecord(
                        row_number=row_number,
                        values={column: row[column] for column in columns},
                    )
        except UnicodeDecodeError as exc:
            raise CsvInputError(f"CSV is not valid UTF-8: {self.path}") from exc
        except csv.Error as exc:
            raise CsvInputError(f"Invalid CSV syntax in {self.path}: {exc}") from exc
        except OSError as exc:
            raise CsvInputError(f"Could not read CSV file: {self.path}") from exc


def _validate_header(header: list[str], path: Path) -> list[str]:
    if not header or all(not column.strip() for column in header):
        raise CsvInputError(f"CSV has no usable header columns: {path}")

    blank_positions = [str(index + 1) for index, column in enumerate(header) if not column.strip()]
    if blank_positions:
        raise CsvInputError(
            "CSV header contains blank column name(s) at position(s): " + ", ".join(blank_positions)
        )

    duplicates = sorted({column for column in header if header.count(column) > 1})
    if duplicates:
        raise CsvInputError(
            "CSV header contains duplicate column name(s): " + ", ".join(duplicates)
        )

    return header
