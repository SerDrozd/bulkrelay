from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from bulkrelay.config.models import JobConfig
from bulkrelay.execution.engine import ExecutionEngine
from bulkrelay.execution.shutdown import ShutdownController
from bulkrelay.state.run_state import ResumeError


def make_input(tmp_path: Path, rows: int = 4) -> Path:
    path = tmp_path / "customers.csv"
    path.write_text(
        "email,first_name\n"
        + "".join(
            f"user{index}@example.com,User{index}\n" for index in range(1, rows + 1)
        ),
        encoding="utf-8",
    )
    return path


def make_config(input_path: Path, *, url: str = "http://test/users") -> JobConfig:
    return JobConfig.model_validate(
        {
            "version": 1,
            "input": {"file": str(input_path)},
            "request": {
                "method": "POST",
                "url": url,
                "json": {
                    "email": {"from": "email"},
                    "first_name": {"from": "first_name"},
                },
            },
            "execution": {"concurrency": 1},
            "retry": {"max_attempts": 1},
        }
    )


@pytest.mark.asyncio
async def test_resume_skips_persisted_rows_and_finishes_same_run(tmp_path: Path) -> None:
    input_path = make_input(tmp_path)
    config = make_config(input_path)
    shutdown = ShutdownController()
    first_calls: list[str] = []

    async def first_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        first_calls.append(payload["email"])
        shutdown.request_stop()
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(first_handler)) as client:
        first = await ExecutionEngine(client).run(
            config=config,
            input_path=input_path,
            output_root=tmp_path / "runs",
            shutdown=shutdown,
            config_path=tmp_path / "job.yaml",
        )

    assert first.stopped_early is True
    assert first.total == 1
    assert first_calls == ["user1@example.com"]
    run_directory = Path(first.run_directory)

    manifest = json.loads((run_directory / "run.json").read_text(encoding="utf-8"))
    checkpoint = json.loads(
        (run_directory / "checkpoint.json").read_text(encoding="utf-8")
    )
    assert manifest["state"] == "stopped"
    assert checkpoint["processed"] == 1
    assert checkpoint["unprocessed"] == 3

    resumed_calls: list[str] = []

    async def resumed_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        resumed_calls.append(payload["email"])
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(resumed_handler)) as client:
        resumed = await ExecutionEngine(client).run(
            config=config,
            input_path=input_path,
            output_root=tmp_path / "ignored",
            resume_from=run_directory,
            config_path=tmp_path / "job.yaml",
        )

    assert resumed.resumed is True
    assert resumed.run_directory == str(run_directory)
    assert resumed.total == 4
    assert resumed.succeeded == 4
    assert resumed.unprocessed == 0
    assert resumed_calls == [
        "user2@example.com",
        "user3@example.com",
        "user4@example.com",
    ]

    results = [
        json.loads(line)
        for line in (run_directory / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [result["row_number"] for result in results] == [1, 2, 3, 4]

    manifest = json.loads((run_directory / "run.json").read_text(encoding="utf-8"))
    checkpoint = json.loads(
        (run_directory / "checkpoint.json").read_text(encoding="utf-8")
    )
    assert manifest["state"] == "completed"
    assert manifest["resume_count"] == 1
    assert checkpoint["processed"] == 4
    assert checkpoint["unprocessed"] == 0


@pytest.mark.asyncio
async def test_resume_refuses_changed_input_before_http(tmp_path: Path) -> None:
    input_path = make_input(tmp_path, rows=2)
    config = make_config(input_path)
    shutdown = ShutdownController()

    async def first_handler(request: httpx.Request) -> httpx.Response:
        shutdown.request_stop()
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(first_handler)) as client:
        first = await ExecutionEngine(client).run(
            config=config,
            input_path=input_path,
            output_root=tmp_path / "runs",
            shutdown=shutdown,
        )

    input_path.write_text(
        input_path.read_text(encoding="utf-8") + "new@example.com,New\n",
        encoding="utf-8",
    )
    changed_config = make_config(input_path)
    calls = 0

    async def should_not_run(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(should_not_run)) as client:
        with pytest.raises(ResumeError, match="Input file changed"):
            await ExecutionEngine(client).run(
                config=changed_config,
                input_path=input_path,
                output_root=tmp_path / "ignored",
                resume_from=Path(first.run_directory),
            )

    assert calls == 0


@pytest.mark.asyncio
async def test_resume_refuses_changed_job_config(tmp_path: Path) -> None:
    input_path = make_input(tmp_path, rows=2)
    config = make_config(input_path)
    shutdown = ShutdownController()

    async def first_handler(request: httpx.Request) -> httpx.Response:
        shutdown.request_stop()
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(first_handler)) as client:
        first = await ExecutionEngine(client).run(
            config=config,
            input_path=input_path,
            output_root=tmp_path / "runs",
            shutdown=shutdown,
        )

    changed_config = make_config(input_path, url="http://test/other-users")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(201))) as client:
        with pytest.raises(ResumeError, match="configuration changed"):
            await ExecutionEngine(client).run(
                config=changed_config,
                input_path=input_path,
                output_root=tmp_path / "ignored",
                resume_from=Path(first.run_directory),
            )


@pytest.mark.asyncio
async def test_resume_refuses_completed_run(tmp_path: Path) -> None:
    input_path = make_input(tmp_path, rows=1)
    config = make_config(input_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        complete = await ExecutionEngine(client).run(
            config=config,
            input_path=input_path,
            output_root=tmp_path / "runs",
        )
        with pytest.raises(ResumeError, match="already completed"):
            await ExecutionEngine(client).run(
                config=config,
                input_path=input_path,
                output_root=tmp_path / "ignored",
                resume_from=Path(complete.run_directory),
            )


@pytest.mark.asyncio
async def test_resume_refuses_duplicate_rows_in_result_journal(tmp_path: Path) -> None:
    input_path = make_input(tmp_path, rows=2)
    config = make_config(input_path)
    shutdown = ShutdownController()

    async def first_handler(request: httpx.Request) -> httpx.Response:
        shutdown.request_stop()
        return httpx.Response(201, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(first_handler)) as client:
        first = await ExecutionEngine(client).run(
            config=config,
            input_path=input_path,
            output_root=tmp_path / "runs",
            shutdown=shutdown,
        )

    run_directory = Path(first.run_directory)
    results_path = run_directory / "results.jsonl"
    first_line = results_path.read_text(encoding="utf-8").splitlines()[0]
    with results_path.open("a", encoding="utf-8") as handle:
        handle.write(first_line + "\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(201))) as client:
        with pytest.raises(ResumeError, match="duplicate row_number 1"):
            await ExecutionEngine(client).run(
                config=config,
                input_path=input_path,
                output_root=tmp_path / "ignored",
                resume_from=run_directory,
            )
