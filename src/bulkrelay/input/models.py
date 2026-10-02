from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class InputRecord:
    """One logical input record with a stable human-facing source position."""

    row_number: int
    values: dict[str, Any]
