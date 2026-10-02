from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputConfig(StrictModel):
    file: NonEmptyString


class FieldMapping(StrictModel):
    """Map one output field from either an input column or a constant value."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_column: NonEmptyString | None = Field(default=None, alias="from")
    value: Any | None = None

    @model_validator(mode="before")
    @classmethod
    def exactly_one_source(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        has_column = "from" in data or "from_column" in data
        has_value = "value" in data
        if has_column == has_value:
            raise ValueError("mapping must define exactly one of 'from' or 'value'")
        return data


class RequestConfig(StrictModel):
    method: Literal["POST"] = "POST"
    url: HttpUrl
    headers: dict[NonEmptyString, str] = Field(default_factory=dict)
    json_body: dict[NonEmptyString, FieldMapping] = Field(alias="json", min_length=1)

    @field_validator("headers")
    @classmethod
    def reject_header_newlines(cls, headers: dict[str, str]) -> dict[str, str]:
        for name, value in headers.items():
            if "\n" in name or "\r" in name or "\n" in value or "\r" in value:
                raise ValueError("HTTP headers cannot contain newline characters")
        return headers


class TimeoutConfig(StrictModel):
    connect_seconds: float = Field(default=10.0, gt=0)
    read_seconds: float = Field(default=30.0, gt=0)
    write_seconds: float = Field(default=30.0, gt=0)
    pool_seconds: float = Field(default=5.0, gt=0)


class RateLimitConfig(StrictModel):
    requests_per_second: float = Field(gt=0)


class ExecutionConfig(StrictModel):
    timeout: TimeoutConfig = Field(default_factory=TimeoutConfig)
    rate_limit: RateLimitConfig | None = None


class RetryConfig(StrictModel):
    max_attempts: int = Field(default=1, ge=1, le=20)
    statuses: frozenset[int] = Field(
        default_factory=lambda: frozenset({408, 425, 429, 500, 502, 503, 504})
    )
    initial_backoff_seconds: float = Field(default=1.0, ge=0)
    max_backoff_seconds: float = Field(default=30.0, ge=0)
    jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    respect_retry_after: bool = True

    @field_validator("statuses")
    @classmethod
    def validate_statuses(cls, statuses: frozenset[int]) -> frozenset[int]:
        invalid = sorted(status for status in statuses if status < 400 or status > 599)
        if invalid:
            raise ValueError(f"retry statuses must be HTTP error codes (400-599): {invalid}")
        return statuses

    @model_validator(mode="after")
    def validate_backoff_bounds(self) -> RetryConfig:
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds must be >= initial_backoff_seconds")
        return self


class JobConfig(StrictModel):
    version: Literal[1]
    input: InputConfig
    request: RequestConfig
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
