from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from bulkrelay.config.models import JobConfig


class ConfigLoadError(ValueError):
    """Raised when a configuration file cannot be loaded or validated."""


def load_config(path: Path) -> JobConfig:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigLoadError(f"Could not read config file: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"Invalid YAML in config file: {path}") from exc

    if not isinstance(raw, dict):
        raise ConfigLoadError("Config root must be a YAML mapping")

    try:
        return JobConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigLoadError(str(exc)) from exc


def resolve_input_path(config_path: Path, configured_file: str) -> Path:
    input_path = Path(configured_file)
    if input_path.is_absolute():
        return input_path
    return (config_path.parent / input_path).resolve()
