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


class RequestConfig(BaseModel):
    method: Literal["POST"] = "POST"
    url: HttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: dict[str, FieldMapping] = Field(alias="json")


class JobConfig(BaseModel):
    version: Literal[1]
    input: InputConfig
    request: RequestConfig
