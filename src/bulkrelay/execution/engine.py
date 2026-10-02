from __future__ import annotations

from pathlib import Path

import httpx

from bulkrelay.config.models import JobConfig
from bulkrelay.execution.models import RecordResult, ResultClassification, RunSummary
from bulkrelay.input.factory import open_record_source
from bulkrelay.mapping.request_builder import build_json_body
from bulkrelay.reporting.run_report import RunReporter
from bulkrelay.validation.preflight import preflight


class ExecutionEngine:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def run(
        self,
        config: JobConfig,
        input_path: Path,
        output_root: Path,
    ) -> RunSummary:
        # Validate the full source before causing any remote side effects. This
        # deliberately trades a second streaming read for a safer migration UX.
        preflight(config, input_path)
        source = open_record_source(input_path)
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
                    classification = _classify_response(response)
                    result = RecordResult(
                        row_number=record.row_number,
                        success=response.is_success,
                        classification=classification,
                        status_code=response.status_code,
                        error=None if response.is_success else _response_error(response),
                    )
                except httpx.HTTPError as exc:
                    result = RecordResult(
                        row_number=record.row_number,
                        success=False,
                        classification=ResultClassification.NETWORK_ERROR,
                        status_code=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                reporter.append(result)
        finally:
            if owns_client:
                await client.aclose()

        return reporter.finalize()


def _classify_response(response: httpx.Response) -> ResultClassification:
    if response.is_success:
        return ResultClassification.SUCCESS
    if response.is_redirect:
        return ResultClassification.HTTP_REDIRECT
    if response.is_client_error:
        return ResultClassification.HTTP_CLIENT_ERROR
    if response.is_server_error:
        return ResultClassification.HTTP_SERVER_ERROR
    return ResultClassification.HTTP_ERROR


def _response_error(response: httpx.Response) -> str:
    text = response.text.strip()
    if not text:
        return f"HTTP {response.status_code}"
    return text[:1000]
