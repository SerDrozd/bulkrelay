from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from bulkrelay.execution.models import RecordResult, RunSummary
from bulkrelay.state.run_state import ResumeSnapshot, atomic_write_json, write_checkpoint


class RunReporter:
    def __init__(
        self,
        run_directory: Path,
        *,
        input_total: int,
        snapshot: ResumeSnapshot | None = None,
    ) -> None:
        self.run_directory = run_directory
        self._results_path = self.run_directory / "results.jsonl"
        self._input_total = input_total
        self._completed_rows = set() if snapshot is None else set(snapshot.completed_rows)
        self._total = 0 if snapshot is None else snapshot.total
        self._succeeded = 0 if snapshot is None else snapshot.succeeded
        self._failed = 0 if snapshot is None else snapshot.failed
        self._attempts = 0 if snapshot is None else snapshot.attempts
        self._retried = 0 if snapshot is None else snapshot.retried

    @classmethod
    def create(cls, base_directory: Path, *, input_total: int) -> RunReporter:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_directory = base_directory / f"{stamp}-{uuid4().hex[:8]}"
        run_directory.mkdir(parents=True, exist_ok=False)
        reporter = cls(run_directory, input_total=input_total)
        reporter._write_checkpoint()
        return reporter

    @classmethod
    def resume(
        cls,
        run_directory: Path,
        *,
        input_total: int,
        snapshot: ResumeSnapshot,
    ) -> RunReporter:
        reporter = cls(run_directory, input_total=input_total, snapshot=snapshot)
        reporter._write_checkpoint()
        return reporter

    @property
    def processed_count(self) -> int:
        return self._total

    @property
    def completed_rows(self) -> frozenset[int]:
        return frozenset(self._completed_rows)

    def append(self, result: RecordResult) -> None:
        if result.row_number in self._completed_rows:
            raise RuntimeError(f"row {result.row_number} already has a persisted result")

        encoded = json.dumps(asdict(result), ensure_ascii=False) + "\n"
        with self._results_path.open("a", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

        self._completed_rows.add(result.row_number)
        self._total += 1
        self._attempts += result.attempts
        if result.attempts > 1:
            self._retried += 1
        if result.success:
            self._succeeded += 1
        else:
            self._failed += 1
        self._write_checkpoint()

    def finalize(
        self,
        *,
        input_total: int,
        stopped_early: bool = False,
        forced: bool = False,
        resumed: bool = False,
    ) -> RunSummary:
        summary = RunSummary(
            total=self._total,
            succeeded=self._succeeded,
            failed=self._failed,
            attempts=self._attempts,
            retried=self._retried,
            run_directory=str(self.run_directory),
            input_total=input_total,
            stopped_early=stopped_early,
            forced=forced,
            resumed=resumed,
        )
        payload = asdict(summary)
        payload["unprocessed"] = summary.unprocessed
        atomic_write_json(self.run_directory / "summary.json", payload)
        self._write_checkpoint()
        return summary

    def _write_checkpoint(self) -> None:
        write_checkpoint(
            self.run_directory,
            total=self._total,
            succeeded=self._succeeded,
            failed=self._failed,
            attempts=self._attempts,
            retried=self._retried,
            input_total=self._input_total,
        )
