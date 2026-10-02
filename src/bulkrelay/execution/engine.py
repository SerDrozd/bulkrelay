from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import cast

import httpx

from bulkrelay.config.models import JobConfig, TimeoutConfig
from bulkrelay.execution.models import RecordResult, ResultClassification, RunSummary
from bulkrelay.execution.rate_limit import RateLimiter
from bulkrelay.execution.retry import RetryPolicy
from bulkrelay.execution.shutdown import ShutdownController
from bulkrelay.input.factory import open_record_source
from bulkrelay.input.models import InputRecord
from bulkrelay.mapping.request_builder import build_json_body
from bulkrelay.reporting.run_report import RunReporter
from bulkrelay.state.fingerprints import fingerprint_file, fingerprint_job
from bulkrelay.state.run_state import (
    load_manifest,
    load_resume_snapshot,
    mark_final_state,
    mark_resumed,
    new_manifest,
    verify_resume_identity,
    write_manifest,
)
from bulkrelay.validation.preflight import preflight

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]
RandomValue = Callable[[], float]
WallClock = Callable[[], datetime]
RecordTask = asyncio.Task[RecordResult]


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
        *,
        shutdown: ShutdownController | None = None,
        config_path: Path | None = None,
        resume_from: Path | None = None,
    ) -> RunSummary:
        # Validate the full source before causing any remote side effects. This
        # deliberately trades a second streaming read for a safer migration UX.
        validation = preflight(config, input_path)
        input_sha256, input_size_bytes = fingerprint_file(input_path)
        config_sha256 = fingerprint_job(config)
        resumed = resume_from is not None

        if resume_from is None:
            reporter = RunReporter.create(output_root, input_total=validation.records)
            manifest = new_manifest(
                run_directory=reporter.run_directory,
                config_path=config_path,
                input_path=input_path,
                input_format=validation.input_format,
                input_sha256=input_sha256,
                input_size_bytes=input_size_bytes,
                config_sha256=config_sha256,
                input_total=validation.records,
            )
            write_manifest(reporter.run_directory, manifest)
        else:
            run_directory = resume_from.resolve()
            manifest = load_manifest(run_directory)
            verify_resume_identity(
                manifest,
                input_format=validation.input_format,
                input_sha256=input_sha256,
                input_size_bytes=input_size_bytes,
                config_sha256=config_sha256,
                input_total=validation.records,
            )
            snapshot = load_resume_snapshot(
                run_directory,
                input_total=validation.records,
            )
            reporter = RunReporter.resume(
                run_directory,
                input_total=validation.records,
                snapshot=snapshot,
            )
            manifest = mark_resumed(run_directory, manifest)

        source = open_record_source(input_path)
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
        controller = shutdown or ShutdownController()

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient()
        forced = False
        try:
            forced = await self._execute_records(
                records=source.records(),
                completed_rows=reporter.completed_rows,
                concurrency=config.execution.concurrency,
                client=client,
                config=config,
                timeout=timeout,
                retry_policy=retry_policy,
                limiter=limiter,
                reporter=reporter,
                shutdown=controller,
            )
        finally:
            if owns_client:
                await client.aclose()

        stopped_early = reporter.processed_count < validation.records
        summary = reporter.finalize(
            input_total=validation.records,
            stopped_early=stopped_early,
            forced=forced,
            resumed=resumed,
        )
        mark_final_state(
            reporter.run_directory,
            manifest,
            stopped_early=summary.stopped_early,
            forced=summary.forced,
            failed=summary.failed,
        )
        return summary

    async def _execute_records(
        self,
        *,
        records: Iterator[InputRecord],
        completed_rows: frozenset[int],
        concurrency: int,
        client: httpx.AsyncClient,
        config: JobConfig,
        timeout: httpx.Timeout,
        retry_policy: RetryPolicy,
        limiter: RateLimiter,
        reporter: RunReporter,
        shutdown: ShutdownController,
    ) -> bool:
        active: set[RecordTask] = set()
        exhausted = False
        force_waiter = asyncio.create_task(
            shutdown.wait_for_force(),
            name="bulkrelay-force-shutdown",
        )

        def schedule_available() -> None:
            nonlocal exhausted
            while (
                not exhausted
                and not shutdown.stop_requested
                and len(active) < concurrency
            ):
                try:
                    record = next(records)
                except StopIteration:
                    exhausted = True
                    return

                if record.row_number in completed_rows:
                    continue

                body = build_json_body(config.request, record)
                task = asyncio.create_task(
                    self._execute_record(
                        client=client,
                        config=config,
                        body=body,
                        row_number=record.row_number,
                        timeout=timeout,
                        retry_policy=retry_policy,
                        limiter=limiter,
                    ),
                    name=f"bulkrelay-record-{record.row_number}",
                )
                active.add(task)

        try:
            if shutdown.force_requested:
                return True

            schedule_available()

            while active:
                wait_set: set[asyncio.Future[object]] = {
                    cast(asyncio.Future[object], task) for task in active
                }
                wait_set.add(cast(asyncio.Future[object], force_waiter))
                done, _ = await asyncio.wait(
                    wait_set,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                completed = sorted(
                    (
                        cast(RecordTask, task)
                        for task in done
                        if task is not force_waiter
                    ),
                    key=lambda task: task.get_name(),
                )
                for task in completed:
                    active.remove(task)
                    reporter.append(task.result())

                if force_waiter in done:
                    await _cancel_tasks(active)
                    active.clear()
                    return True

                schedule_available()

            return shutdown.force_requested
        except BaseException:
            await _cancel_tasks(active)
            raise
        finally:
            if not force_waiter.done():
                force_waiter.cancel()
                await asyncio.gather(force_waiter, return_exceptions=True)

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


async def _cancel_tasks(tasks: set[RecordTask]) -> None:
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


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
