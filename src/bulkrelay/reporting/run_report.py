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

    def append(self, result: RecordResult) -> None:
        with self._results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
        self._total += 1
        if result.success:
            self._succeeded += 1
        else:
            self._failed += 1

    def finalize(self) -> RunSummary:
        summary = RunSummary(
            total=self._total,
            succeeded=self._succeeded,
            failed=self._failed,
            run_directory=str(self.run_directory),
        )
        (self.run_directory / "summary.json").write_text(
            json.dumps(asdict(summary), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return summary
