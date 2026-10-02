from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bulkrelay.config.models import JobConfig

_CHUNK_SIZE = 1024 * 1024


def fingerprint_file(path: Path) -> tuple[str, int]:
    """Return a SHA-256 digest and byte size without loading the file into memory."""

    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def fingerprint_job(config: JobConfig) -> str:
    """Fingerprint request-affecting config while allowing the input path to move.

    The input file is fingerprinted separately. Only a digest is persisted, so headers or
    other sensitive config values are never copied into the run directory.
    """

    payload = config.model_dump(mode="json", by_alias=True, exclude={"input"})
    retry = payload.get("retry")
    if isinstance(retry, dict) and isinstance(retry.get("statuses"), list):
        retry["statuses"] = sorted(retry["statuses"])
    canonical = json.dumps(
        _canonicalize(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonicalize(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value
