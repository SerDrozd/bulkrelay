from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ResultClassification(StrEnum):
    SUCCESS = "success"
    HTTP_REDIRECT = "http_redirect"
    HTTP_CLIENT_ERROR = "http_client_error"
    HTTP_SERVER_ERROR = "http_server_error"
    HTTP_ERROR = "http_error"
    TIMEOUT_ERROR = "timeout_error"
    NETWORK_ERROR = "network_error"


@dataclass(frozen=True, slots=True)
class RecordResult:
    row_number: int
    success: bool
    classification: ResultClassification
    status_code: int | None
    attempts: int
    retryable: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RunSummary:
    total: int
    succeeded: int
    failed: int
    attempts: int
    retried: int
    run_directory: str
    input_total: int
    stopped_early: bool = False
    forced: bool = False

    @property
    def unprocessed(self) -> int:
        return max(0, self.input_total - self.total)
