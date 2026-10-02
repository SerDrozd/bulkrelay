from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from bulkrelay.config.models import JobConfig
from bulkrelay.execution.engine import ExecutionEngine
from bulkrelay.execution.shutdown import ShutdownController


def make_input(tmp_path: Path, rows: int) -> Path:
    path = tmp_path / "customers.csv"
    path.write_text(
        "email,first_name\n"
        + "".join(
            f"user{index}@example.com,User{index}\n" for index in range(1, rows + 1)
        ),
        encoding="utf-8",
    )
    return path


def make_config(
    input_path: Path,
    *,
    concurrency: int,
    requests_per_second: float | None = None,
) -> JobConfig:
    execution: dict[str, object] = {"concurrency": concurrency}
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
            "retry": {"max_attempts": 1},
        }
    )


@pytest.mark.asyncio
async def test_execution_never_exceeds_configured_concurrency(tmp_path: Path) -> None:
    input_path = make_input(tmp_path, rows=9)
    release = asyncio.Event()
    window_full = asyncio.Event()
    active = 0
    max_active = 0
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, max_active, calls
        active += 1
        calls += 1
        max_active = max(max_active, active)
        if active == 3:
            window_full.set()
        try:
            await release.wait()
            return httpx.Response(201, request=request)
        finally:
            active -= 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        run_task = asyncio.create_task(
            ExecutionEngine(client).run(
                config=make_config(input_path, concurrency=3),
                input_path=input_path,
                output_root=tmp_path / "runs",
            )
        )
        await asyncio.wait_for(window_full.wait(), timeout=1)
        assert calls == 3
        assert max_active == 3
        release.set()
        summary = await asyncio.wait_for(run_task, timeout=2)

    assert summary.succeeded == 9
    assert summary.total == 9
    assert max_active == 3


@pytest.mark.asyncio
async def test_graceful_stop_finishes_only_in_flight_records(tmp_path: Path) -> None:
    input_path = make_input(tmp_path, rows=8)
    release = asyncio.Event()
    window_full = asyncio.Event()
    shutdown = ShutdownController()
    active = 0
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, calls
        active += 1
        calls += 1
        if active == 3:
            window_full.set()
        try:
            await release.wait()
            return httpx.Response(201, request=request)
        finally:
            active -= 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        run_task = asyncio.create_task(
            ExecutionEngine(client).run(
                config=make_config(input_path, concurrency=3),
                input_path=input_path,
                output_root=tmp_path / "runs",
                shutdown=shutdown,
            )
        )
        await asyncio.wait_for(window_full.wait(), timeout=1)
        shutdown.request_stop()
        release.set()
        summary = await asyncio.wait_for(run_task, timeout=2)

    assert calls == 3
    assert summary.input_total == 8
    assert summary.total == 3
    assert summary.unprocessed == 5
    assert summary.succeeded == 3
    assert summary.stopped_early is True
    assert summary.forced is False

    persisted = json.loads(
        (Path(summary.run_directory) / "summary.json").read_text(encoding="utf-8")
    )
    assert persisted["unprocessed"] == 5
    assert persisted["stopped_early"] is True


@pytest.mark.asyncio
async def test_force_stop_cancels_in_flight_records(tmp_path: Path) -> None:
    input_path = make_input(tmp_path, rows=2)
    never_release = asyncio.Event()
    window_full = asyncio.Event()
    shutdown = ShutdownController()
    active = 0
    calls = 0
    cancellations = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, calls, cancellations
        active += 1
        calls += 1
        if active == 2:
            window_full.set()
        try:
            await never_release.wait()
            return httpx.Response(201, request=request)
        except asyncio.CancelledError:
            cancellations += 1
            raise
        finally:
            active -= 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        run_task = asyncio.create_task(
            ExecutionEngine(client).run(
                config=make_config(input_path, concurrency=2),
                input_path=input_path,
                output_root=tmp_path / "runs",
                shutdown=shutdown,
            )
        )
        await asyncio.wait_for(window_full.wait(), timeout=1)
        shutdown.request_stop()
        shutdown.request_stop()
        summary = await asyncio.wait_for(run_task, timeout=2)

    assert calls == 2
    assert cancellations == 2
    assert summary.input_total == 2
    assert summary.total == 0
    assert summary.unprocessed == 2
    assert summary.stopped_early is True
    assert summary.forced is True


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.asyncio
async def test_concurrent_workers_share_one_global_rate_limiter(tmp_path: Path) -> None:
    input_path = make_input(tmp_path, rows=3)
    fake_time = FakeTime()
    starts: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        starts.append(fake_time.clock())
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await ExecutionEngine(
            client,
            sleep=fake_time.sleep,
            clock=fake_time.clock,
        ).run(
            config=make_config(
                input_path,
                concurrency=3,
                requests_per_second=2,
            ),
            input_path=input_path,
            output_root=tmp_path / "runs",
        )

    assert summary.succeeded == 3
    assert sorted(starts) == pytest.approx([0.0, 0.5, 1.0])


@pytest.mark.asyncio
async def test_concurrent_results_preserve_source_row_numbers(tmp_path: Path) -> None:
    input_path = make_input(tmp_path, rows=4)

    async def handler(request: httpx.Request) -> httpx.Response:
        email = json.loads(request.content)["email"]
        index = int(email.removeprefix("user").split("@", maxsplit=1)[0])
        await asyncio.sleep((5 - index) * 0.001)
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await ExecutionEngine(client).run(
            config=make_config(input_path, concurrency=4),
            input_path=input_path,
            output_root=tmp_path / "runs",
        )

    rows = {
        json.loads(line)["row_number"]
        for line in (Path(summary.run_directory) / "results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    }
    assert rows == {1, 2, 3, 4}
