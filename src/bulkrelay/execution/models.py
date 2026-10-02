from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecordResult:
    row_number: int
    success: bool
    status_code: int | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RunSummary:
    total: int
    succeeded: int
    failed: int
    run_directory: str
