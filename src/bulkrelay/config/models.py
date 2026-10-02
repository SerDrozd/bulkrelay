from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class InputConfig(BaseModel):
    file: str


class FieldMapping(BaseModel):
    """Map one output field from either an input column or a constant value."""

    model_config = ConfigDict(populate_by_name=True)

    from_column: str | None = Field(default=None, alias="from")
    value: Any | None = None

    @model_validator(mode="after")
    def exactly_one_source(self) -> FieldMapping:
        has_column = self.from_column is not None
        has_value = self.value is not None
        if has_column == has_value:
            raise ValueError("mapping must define exactly one of 'from' or 'value'")
        return self


class RequestConfig(BaseModel):
    method: Literal["POST"] = "POST"
    url: HttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    json: dict[str, FieldMapping]


class JobConfig(BaseModel):
    version: Literal[1]
    input: InputConfig
    request: RequestConfig
