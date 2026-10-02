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


class JobConfig(StrictModel):
    version: Literal[1]
    input: InputConfig
    request: RequestConfig
