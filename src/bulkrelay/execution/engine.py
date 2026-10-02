from __future__ import annotations

from pathlib import Path

import httpx

from bulkrelay.config.models import JobConfig
from bulkrelay.execution.models import RecordResult, RunSummary
from bulkrelay.input.csv_reader import CsvRecordSource
from bulkrelay.mapping.request_builder import build_json_body, validate_columns
from bulkrelay.reporting.run_report import RunReporter


class ExecutionEngine:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def run(
        self,
        config: JobConfig,
        input_path: Path,
        output_root: Path,
    ) -> RunSummary:
        source = CsvRecordSource(input_path)
        validate_columns(config.request, source.columns())
        reporter = RunReporter(output_root)

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            for record in source.records():
                body = build_json_body(config.request, record)
                try:
                    response = await client.post(
                        str(config.request.url),
                        headers=config.request.headers,
                        json=body,
                    )
                    result = RecordResult(
                        row_number=record.row_number,
                        success=response.is_success,
                        status_code=response.status_code,
                        error=None if response.is_success else _response_error(response),
                    )
                except httpx.HTTPError as exc:
                    result = RecordResult(
                        row_number=record.row_number,
                        success=False,
                        status_code=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                reporter.append(result)
        finally:
            if owns_client:
                await client.aclose()

        return reporter.finalize()


def _response_error(response: httpx.Response) -> str:
    text = response.text.strip()
    if not text:
        return f"HTTP {response.status_code}"
    return text[:1000]
