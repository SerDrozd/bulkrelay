from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from bulkrelay.input.models import InputRecord


class InputError(ValueError):
    """Raised when an input file cannot be interpreted safely."""


class RecordSource(Protocol):
    """Streaming record source used by validation and execution."""

    format_name: str

    def columns(self) -> list[str] | None:
        """Return declared columns when the format has a fixed schema."""

    def records(self) -> Iterator[InputRecord]:
        """Yield records in source order."""
