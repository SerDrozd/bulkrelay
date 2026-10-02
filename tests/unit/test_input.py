from __future__ import annotations

from pathlib import Path

import pytest

from bulkrelay.input.base import InputError
from bulkrelay.input.csv_reader import CsvInputError, CsvRecordSource
from bulkrelay.input.factory import open_record_source
from bulkrelay.input.jsonl_reader import JsonlInputError, JsonlRecordSource


def test_csv_rejects_duplicate_header(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("email,email\na@example.com,Alice\n", encoding="utf-8")

    with pytest.raises(CsvInputError, match="duplicate column"):
        CsvRecordSource(path).columns()


def test_csv_rejects_short_row(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("email,name\na@example.com\n", encoding="utf-8")

    with pytest.raises(CsvInputError, match="fewer values"):
        list(CsvRecordSource(path).records())


def test_jsonl_reads_objects_and_preserves_types(tmp_path: Path) -> None:
    path = tmp_path / "input.jsonl"
    path.write_text('{"email":"a@example.com","active":true,"score":3}\n', encoding="utf-8")

    records = list(JsonlRecordSource(path).records())

    assert records[0].row_number == 1
    assert records[0].values == {"email": "a@example.com", "active": True, "score": 3}


def test_jsonl_reports_invalid_line_number(tmp_path: Path) -> None:
    path = tmp_path / "input.jsonl"
    path.write_text('{"email":"a@example.com"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(JsonlInputError, match="line 2"):
        list(JsonlRecordSource(path).records())


def test_jsonl_rejects_non_object_record(tmp_path: Path) -> None:
    path = tmp_path / "input.jsonl"
    path.write_text('[1, 2, 3]\n', encoding="utf-8")

    with pytest.raises(JsonlInputError, match="must contain a JSON object"):
        list(JsonlRecordSource(path).records())


def test_factory_rejects_unknown_extension(tmp_path: Path) -> None:
    path = tmp_path / "input.txt"
    path.write_text("hello", encoding="utf-8")

    with pytest.raises(InputError, match="Unsupported input extension"):
        open_record_source(path)


def test_jsonl_rejects_nonstandard_nan(tmp_path: Path) -> None:
    path = tmp_path / "input.jsonl"
    path.write_text('{"score":NaN}\n', encoding="utf-8")

    with pytest.raises(JsonlInputError, match="non-standard numeric constant"):
        list(JsonlRecordSource(path).records())
