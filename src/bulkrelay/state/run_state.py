from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from bulkrelay import __version__


class ResumeError(ValueError):
    """Raised when an existing run cannot be resumed safely."""


class RunState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    FORCED = "forced"
    COMPLETED = "completed"
    COMPLETED_WITH_FAILURES = "completed_with_failures"


@dataclass(frozen=True, slots=True)
class RunManifest:
    schema_version: int
    tool_version: str
    run_id: str
    state: RunState
    created_at: str
    updated_at: str
    config_path: str | None
    input_path: str
    input_format: str
    input_sha256: str
    input_size_bytes: int
    config_sha256: str
    input_total: int
    resume_count: int = 0


@dataclass(frozen=True, slots=True)
class ResumeSnapshot:
    completed_rows: frozenset[int]
    total: int
    succeeded: int
    failed: int
    attempts: int
    retried: int


def new_manifest(
    *,
    run_directory: Path,
    config_path: Path | None,
    input_path: Path,
    input_format: str,
    input_sha256: str,
    input_size_bytes: int,
    config_sha256: str,
    input_total: int,
) -> RunManifest:
    now = _utc_now()
    return RunManifest(
        schema_version=1,
        tool_version=__version__,
        run_id=run_directory.name,
        state=RunState.RUNNING,
        created_at=now,
        updated_at=now,
        config_path=None if config_path is None else str(config_path.resolve()),
        input_path=str(input_path.resolve()),
        input_format=input_format,
        input_sha256=input_sha256,
        input_size_bytes=input_size_bytes,
        config_sha256=config_sha256,
        input_total=input_total,
    )


def load_manifest(run_directory: Path) -> RunManifest:
    path = run_directory / "run.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ResumeError(f"Run manifest not found: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResumeError(f"Run manifest is unreadable or corrupted: {path}") from exc

    try:
        schema_version = int(raw["schema_version"])
        if schema_version != 1:
            raise ResumeError(
                f"Unsupported run manifest schema {schema_version}; expected schema 1"
            )
        return RunManifest(
            schema_version=schema_version,
            tool_version=str(raw["tool_version"]),
            run_id=str(raw["run_id"]),
            state=RunState(raw["state"]),
            created_at=str(raw["created_at"]),
            updated_at=str(raw["updated_at"]),
            config_path=None if raw.get("config_path") is None else str(raw["config_path"]),
            input_path=str(raw["input_path"]),
            input_format=str(raw["input_format"]),
            input_sha256=str(raw["input_sha256"]),
            input_size_bytes=int(raw["input_size_bytes"]),
            config_sha256=str(raw["config_sha256"]),
            input_total=int(raw["input_total"]),
            resume_count=int(raw.get("resume_count", 0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ResumeError):
            raise
        raise ResumeError(f"Run manifest is missing or contains invalid fields: {path}") from exc


def write_manifest(run_directory: Path, manifest: RunManifest) -> None:
    payload = asdict(manifest)
    payload["state"] = manifest.state.value
    _atomic_write_json(run_directory / "run.json", payload)


def mark_resumed(run_directory: Path, manifest: RunManifest) -> RunManifest:
    updated = replace(
        manifest,
        state=RunState.RUNNING,
        updated_at=_utc_now(),
        resume_count=manifest.resume_count + 1,
    )
    write_manifest(run_directory, updated)
    return updated


def mark_final_state(
    run_directory: Path,
    manifest: RunManifest,
    *,
    stopped_early: bool,
    forced: bool,
    failed: int,
) -> RunManifest:
    if stopped_early:
        state = RunState.FORCED if forced else RunState.STOPPED
    elif failed:
        state = RunState.COMPLETED_WITH_FAILURES
    else:
        state = RunState.COMPLETED
    updated = replace(manifest, state=state, updated_at=_utc_now())
    write_manifest(run_directory, updated)
    return updated


def verify_resume_identity(
    manifest: RunManifest,
    *,
    input_format: str,
    input_sha256: str,
    input_size_bytes: int,
    config_sha256: str,
    input_total: int,
) -> None:
    if manifest.state in {RunState.COMPLETED, RunState.COMPLETED_WITH_FAILURES}:
        raise ResumeError(
            f"Run {manifest.run_id} is already {manifest.state.value}; "
            "completed runs cannot be resumed"
        )
    if manifest.input_format != input_format:
        raise ResumeError(
            "Input format changed since the original run: "
            f"expected {manifest.input_format}, got {input_format}"
        )
    if manifest.input_sha256 != input_sha256 or manifest.input_size_bytes != input_size_bytes:
        raise ResumeError(
            "Input file changed since the original run; refusing unsafe resume "
            f"(expected sha256 {manifest.input_sha256}, got {input_sha256})"
        )
    if manifest.config_sha256 != config_sha256:
        raise ResumeError(
            "Job configuration changed since the original run; refusing unsafe resume "
            f"(expected sha256 {manifest.config_sha256}, got {config_sha256})"
        )
    if manifest.input_total != input_total:
        raise ResumeError(
            "Input record count changed since the original run: "
            f"expected {manifest.input_total}, got {input_total}"
        )


def load_resume_snapshot(run_directory: Path, *, input_total: int) -> ResumeSnapshot:
    path = run_directory / "results.jsonl"
    if not path.exists():
        return ResumeSnapshot(
            completed_rows=frozenset(),
            total=0,
            succeeded=0,
            failed=0,
            attempts=0,
            retried=0,
        )

    completed_rows: set[int] = set()
    total = succeeded = failed = attempts = retried = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise ResumeError(f"Blank line in result journal at line {line_number}")
                try:
                    raw: Any = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ResumeError(
                        f"Result journal is corrupted at line {line_number}: invalid JSON"
                    ) from exc
                if not isinstance(raw, dict):
                    raise ResumeError(
                        f"Result journal is corrupted at line {line_number}: expected object"
                    )
                try:
                    row_number = int(raw["row_number"])
                    success = raw["success"]
                    record_attempts = int(raw["attempts"])
                    classification = raw["classification"]
                    status_code = raw["status_code"]
                    retryable = raw["retryable"]
                    error = raw.get("error")
                except (KeyError, TypeError, ValueError) as exc:
                    raise ResumeError(
                        f"Result journal is corrupted at line {line_number}: missing invalid fields"
                    ) from exc
                if type(success) is not bool:  # bool only; integers must not pass as booleans.
                    raise ResumeError(
                        f"Result journal is corrupted at line {line_number}: "
                        "success must be boolean"
                    )
                if not isinstance(classification, str) or not classification:
                    raise ResumeError(
                        f"Result journal is corrupted at line {line_number}: invalid classification"
                    )
                if status_code is not None and (
                    type(status_code) is not int or status_code < 100 or status_code > 599
                ):
                    raise ResumeError(
                        f"Result journal is corrupted at line {line_number}: invalid status_code"
                    )
                if type(retryable) is not bool:
                    raise ResumeError(
                        f"Result journal is corrupted at line {line_number}: "
                        "retryable must be boolean"
                    )
                if error is not None and not isinstance(error, str):
                    raise ResumeError(
                        f"Result journal is corrupted at line {line_number}: "
                        "error must be string or null"
                    )
                if row_number < 1 or row_number > input_total:
                    raise ResumeError(
                        f"Result journal row {row_number} is outside input range 1..{input_total}"
                    )
                if row_number in completed_rows:
                    raise ResumeError(
                        f"Result journal contains duplicate row_number {row_number}; "
                        "refusing resume"
                    )
                if record_attempts < 1:
                    raise ResumeError(
                        f"Result journal row {row_number} has invalid attempts={record_attempts}"
                    )
                completed_rows.add(row_number)
                total += 1
                attempts += record_attempts
                retried += int(record_attempts > 1)
                if success:
                    succeeded += 1
                else:
                    failed += 1
    except (OSError, UnicodeDecodeError) as exc:
        raise ResumeError(f"Could not read result journal: {path}") from exc

    return ResumeSnapshot(
        completed_rows=frozenset(completed_rows),
        total=total,
        succeeded=succeeded,
        failed=failed,
        attempts=attempts,
        retried=retried,
    )


def write_checkpoint(
    run_directory: Path,
    *,
    total: int,
    succeeded: int,
    failed: int,
    attempts: int,
    retried: int,
    input_total: int,
) -> None:
    _atomic_write_json(
        run_directory / "checkpoint.json",
        {
            "schema_version": 1,
            "updated_at": _utc_now(),
            "processed": total,
            "unprocessed": max(0, input_total - total),
            "succeeded": succeeded,
            "failed": failed,
            "attempts": attempts,
            "retried": retried,
        },
    )


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    _atomic_write_json(path, payload)


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    data = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
