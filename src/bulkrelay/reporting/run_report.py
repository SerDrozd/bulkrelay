from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from bulkrelay.execution.models import RecordResult, RunSummary


class RunReporter:
    def __init__(self, base_directory: Path) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.run_directory = base_directory / f"{stamp}-{uuid4().hex[:8]}"
        self.run_directory.mkdir(parents=True, exist_ok=False)
        self._results_path = self.run_directory / "results.jsonl"
        self._total = 0
        self._succeeded = 0
        self._failed = 0
        self._attempts = 0
        self._retried = 0

    @property
    def processed_count(self) -> int:
        return self._total

    def append(self, result: RecordResult) -> None:
        with self._results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
        self._total += 1
        self._attempts += result.attempts
        if result.attempts > 1:
            self._retried += 1
        if result.success:
            self._succeeded += 1
        else:
            self._failed += 1

    def finalize(
        self,
        *,
        input_total: int,
        stopped_early: bool = False,
        forced: bool = False,
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
        )
        payload = asdict(summary)
        payload["unprocessed"] = summary.unprocessed
        (self.run_directory / "summary.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return summary
