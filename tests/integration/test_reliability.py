from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from bulkrelay.config.models import JobConfig
from bulkrelay.execution.engine import ExecutionEngine


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_input(tmp_path: Path, rows: int = 1) -> Path:
    path = tmp_path / "customers.csv"
    body = "email,first_name\n" + "".join(
        f"user{index}@example.com,User{index}\n" for index in range(1, rows + 1)
    )
    path.write_text(body, encoding="utf-8")
    return path


def make_config(
    input_path: Path,
    *,
    max_attempts: int = 3,
    initial_backoff: float = 1.0,
    max_backoff: float = 30.0,
    jitter: float = 0.0,
    requests_per_second: float | None = None,
) -> JobConfig:
    execution: dict[str, object] = {
        "timeout": {
            "connect_seconds": 2,
            "read_seconds": 3,
            "write_seconds": 4,
            "pool_seconds": 5,
        }
    }
    if requests_per_second is not None:
        execution["rate_limit"] = {"requests_per_second": requests_per_second}

    return JobConfig.model_validate(
        {
            "version": 1,
            "input": {"file": str(input_path)},
            "request": {
                "method": "POST",
                "url": "http://test/users",
                "json": {
                    "email": {"from": "email"},
                    "first_name": {"from": "first_name"},
                },
            },
            "execution": execution,
            "retry": {
                "max_attempts": max_attempts,
                "initial_backoff_seconds": initial_backoff,
                "max_backoff_seconds": max_backoff,
                "jitter_ratio": jitter,
            },
        }
    )


def read_only_result(summary_directory: str) -> dict[str, object]:
    path = Path(summary_directory) / "results.jsonl"
    return json.loads(path.read_text(encoding="utf-8").strip())


@pytest.mark.asyncio
async def test_retries_transient_server_errors_until_success(tmp_path: Path) -> None:
    input_path = make_input(tmp_path)
    fake_time = FakeTime()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, text="temporarily unavailable", request=request)
        return httpx.Response(201, json={"created": True}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await ExecutionEngine(
            client,
            sleep=fake_time.sleep,
            clock=fake_time.clock,
        ).run(
            config=make_config(input_path, max_attempts=4, initial_backoff=0.5),
            input_path=input_path,
            output_root=tmp_path / "runs",
        )

    result = read_only_result(summary.run_directory)
    assert calls == 3
    assert fake_time.sleeps == [0.5, 1.0]
    assert result["success"] is True
    assert result["attempts"] == 3
    assert result["retryable"] is False
    assert summary.attempts == 3
    assert summary.retried == 1


@pytest.mark.asyncio
async def test_does_not_retry_permanent_client_error(tmp_path: Path) -> None:
    input_path = make_input(tmp_path)
    fake_time = FakeTime()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(422, text="invalid record", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await ExecutionEngine(
            client,
            sleep=fake_time.sleep,
            clock=fake_time.clock,
        ).run(
            config=make_config(input_path),
            input_path=input_path,
            output_root=tmp_path / "runs",
        )

    result = read_only_result(summary.run_directory)
    assert calls == 1
    assert fake_time.sleeps == []
    assert result["attempts"] == 1
    assert result["retryable"] is False
    assert result["classification"] == "http_client_error"


@pytest.mark.asyncio
async def test_respects_retry_after_before_retrying(tmp_path: Path) -> None:
    input_path = make_input(tmp_path)
    fake_time = FakeTime()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, request=request)
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await ExecutionEngine(
            client,
            sleep=fake_time.sleep,
            clock=fake_time.clock,
        ).run(
            config=make_config(input_path, initial_backoff=0.5),
            input_path=input_path,
            output_root=tmp_path / "runs",
        )

    assert summary.succeeded == 1
    assert fake_time.sleeps == [7.0]


@pytest.mark.asyncio
async def test_retries_timeout_and_classifies_exhausted_timeout(tmp_path: Path) -> None:
    input_path = make_input(tmp_path)
    fake_time = FakeTime()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("target was too slow", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await ExecutionEngine(
            client,
            sleep=fake_time.sleep,
            clock=fake_time.clock,
        ).run(
            config=make_config(input_path, max_attempts=3, initial_backoff=1),
            input_path=input_path,
            output_root=tmp_path / "runs",
        )

    result = read_only_result(summary.run_directory)
    assert calls == 3
    assert fake_time.sleeps == [1.0, 2.0]
    assert result["classification"] == "timeout_error"
    assert result["attempts"] == 3
    assert result["retryable"] is True


@pytest.mark.asyncio
async def test_rate_limit_applies_to_every_http_attempt(tmp_path: Path) -> None:
    input_path = make_input(tmp_path, rows=3)
    fake_time = FakeTime()
    request_starts: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        request_starts.append(fake_time.clock())
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await ExecutionEngine(
            client,
            sleep=fake_time.sleep,
            clock=fake_time.clock,
        ).run(
            config=make_config(input_path, requests_per_second=2),
            input_path=input_path,
            output_root=tmp_path / "runs",
        )

    assert summary.succeeded == 3
    assert request_starts == [0.0, 0.5, 1.0]


@pytest.mark.asyncio
async def test_configured_timeout_is_passed_to_httpx(tmp_path: Path) -> None:
    input_path = make_input(tmp_path)
    seen_timeout: dict[str, float] | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_timeout
        seen_timeout = request.extensions.get("timeout")
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await ExecutionEngine(client).run(
            config=make_config(input_path),
            input_path=input_path,
            output_root=tmp_path / "runs",
        )

    assert seen_timeout == {"connect": 2.0, "read": 3.0, "write": 4.0, "pool": 5.0}


@pytest.mark.asyncio
async def test_retry_attempt_still_respects_global_rate_limit(tmp_path: Path) -> None:
    input_path = make_input(tmp_path)
    fake_time = FakeTime()
    request_starts: list[float] = []
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        request_starts.append(fake_time.clock())
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await ExecutionEngine(
            client,
            sleep=fake_time.sleep,
            clock=fake_time.clock,
        ).run(
            config=make_config(
                input_path,
                max_attempts=2,
                initial_backoff=0.1,
                requests_per_second=2,
            ),
            input_path=input_path,
            output_root=tmp_path / "runs",
        )

    assert summary.succeeded == 1
    assert request_starts == pytest.approx([0.0, 0.5])
    assert fake_time.sleeps == pytest.approx([0.1, 0.4])
