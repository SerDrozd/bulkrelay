from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from bulkrelay.config.models import JobConfig


class ConfigLoadError(ValueError):
    """Raised when a configuration file cannot be loaded or validated."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable mapping key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load_config(path: Path) -> JobConfig:
    try:
        raw: Any = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except UnicodeDecodeError as exc:
        raise ConfigLoadError(f"Config file is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise ConfigLoadError(f"Could not read config file: {path}") from exc
    except yaml.YAMLError as exc:
        problem = getattr(exc, "problem", None) or str(exc)
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise ConfigLoadError(f"Invalid YAML{location}: {problem}") from exc

    if not isinstance(raw, dict):
        raise ConfigLoadError("Config root must be a YAML mapping")

    try:
        return JobConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigLoadError(_format_validation_error(exc)) from exc


def resolve_input_path(config_path: Path, configured_file: str) -> Path:
    input_path = Path(configured_file)
    if input_path.is_absolute():
        return input_path
    return (config_path.parent / input_path).resolve()


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["Configuration validation failed:"]
    for error in exc.errors(include_url=False, include_context=False):
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        message = str(error["msg"])
        if error["type"] == "extra_forbidden":
            message = "Unexpected field"
        elif message.startswith("Value error, "):
            message = message.removeprefix("Value error, ")
        lines.append(f"- {location}: {message}")
    return "\n".join(lines)
