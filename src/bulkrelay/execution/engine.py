from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

import httpx

from bulkrelay.config.models import JobConfig, TimeoutConfig
from bulkrelay.execution.models import RecordResult, ResultClassification, RunSummary
from bulkrelay.execution.rate_limit import RateLimiter
from bulkrelay.execution.retry import RetryPolicy
from bulkrelay.input.factory import open_record_source
from bulkrelay.mapping.request_builder import build_json_body
from bulkrelay.reporting.run_report import RunReporter
from bulkrelay.validation.preflight import preflight

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]
RandomValue = Callable[[], float]
WallClock = Callable[[], datetime]


class ExecutionEngine:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
        random_value: RandomValue = random.random,
        wall_clock: WallClock | None = None,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._clock = clock
        self._random_value = random_value
        self._wall_clock = wall_clock

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
        retry_policy = RetryPolicy(
            config.retry,
            random_value=self._random_value,
            wall_clock=self._wall_clock,
        )
        rate_limit = config.execution.rate_limit
        limiter = RateLimiter(
            None if rate_limit is None else rate_limit.requests_per_second,
            sleep=self._sleep,
            clock=self._clock,
        )
        timeout = _httpx_timeout(config.execution.timeout)

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            for record in source.records():
                body = build_json_body(config.request, record)
                result = await self._execute_record(
                    client=client,
                    config=config,
                    body=body,
                    row_number=record.row_number,
                    timeout=timeout,
                    retry_policy=retry_policy,
                    limiter=limiter,
                )
                reporter.append(result)
        finally:
            if owns_client:
                await client.aclose()

        return reporter.finalize()

    async def _execute_record(
        self,
        *,
        client: httpx.AsyncClient,
        config: JobConfig,
        body: dict[str, object],
        row_number: int,
        timeout: httpx.Timeout,
        retry_policy: RetryPolicy,
        limiter: RateLimiter,
    ) -> RecordResult:
        attempt = 0

        while True:
            attempt += 1
            await limiter.acquire()
            try:
                response = await client.post(
                    str(config.request.url),
                    headers=config.request.headers,
                    json=body,
                    timeout=timeout,
                )
            except httpx.HTTPError as exc:
                retryable = retry_policy.exception_is_retryable(exc)
                if retryable and retry_policy.can_retry(attempt):
                    await self._sleep(retry_policy.delay_for_exception(attempt))
                    continue

                return RecordResult(
                    row_number=row_number,
                    success=False,
                    classification=_classify_exception(exc),
                    status_code=None,
                    attempts=attempt,
                    retryable=retryable,
                    error=f"{type(exc).__name__}: {exc}",
                )

            retryable = retry_policy.response_is_retryable(response)
            if not response.is_success and retryable and retry_policy.can_retry(attempt):
                await self._sleep(retry_policy.delay_for_response(response, attempt))
                continue

            return RecordResult(
                row_number=row_number,
                success=response.is_success,
                classification=_classify_response(response),
                status_code=response.status_code,
                attempts=attempt,
                retryable=retryable,
                error=None if response.is_success else _response_error(response),
            )


def _httpx_timeout(config: TimeoutConfig) -> httpx.Timeout:
    return httpx.Timeout(
        connect=config.connect_seconds,
        read=config.read_seconds,
        write=config.write_seconds,
        pool=config.pool_seconds,
    )


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


def _classify_exception(exc: httpx.HTTPError) -> ResultClassification:
    if isinstance(exc, httpx.TimeoutException):
        return ResultClassification.TIMEOUT_ERROR
    return ResultClassification.NETWORK_ERROR


def _response_error(response: httpx.Response) -> str:
    text = response.text.strip()
    if not text:
        return f"HTTP {response.status_code}"
    return text[:1000]
