from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from bulkrelay.config.models import JobConfig
from bulkrelay.execution.engine import ExecutionEngine
from bulkrelay.mapping.request_builder import MappingError


class UserIn(BaseModel):
    email: str
    first_name: str
    source: str


def build_fake_api(received: list[dict[str, str]]) -> FastAPI:
    app = FastAPI()

    @app.post("/users", status_code=status.HTTP_201_CREATED)
    async def create_user(user: UserIn) -> dict[str, bool]:
        if user.email == "reject@example.com":
            raise HTTPException(status_code=422, detail="fake rejection")
        received.append(user.model_dump())
        return {"created": True}

    return app


def make_config(input_path: Path) -> JobConfig:
    return JobConfig.model_validate(
        {
            "version": 1,
            "input": {"file": str(input_path)},
            "request": {
                "method": "POST",
                "url": "http://test/users",
                "headers": {"X-Demo": "bulkrelay"},
                "json": {
                    "email": {"from": "email"},
                    "first_name": {"from": "first_name"},
                    "source": {"value": "integration-test"},
                },
            },
            "retry": {"max_attempts": 1},
        }
    )


@pytest.mark.asyncio
async def test_vertical_slice_csv_to_post_to_report(tmp_path: Path) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text(
        "email,first_name\n"
        "alice@example.com,Alice\n"
        "bob@example.com,Bob\n"
        "reject@example.com,Rejected\n",
        encoding="utf-8",
    )

    received: list[dict[str, str]] = []
    transport = httpx.ASGITransport(app=build_fake_api(received))
    async with httpx.AsyncClient(transport=transport) as client:
        summary = await ExecutionEngine(client).run(
            config=make_config(csv_path),
            input_path=csv_path,
            output_root=tmp_path / "runs",
        )

    assert summary.total == 3
    assert summary.succeeded == 2
    assert summary.failed == 1
    assert [item["email"] for item in received] == ["alice@example.com", "bob@example.com"]

    run_dir = Path(summary.run_directory)
    results = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines()]
    assert [result["status_code"] for result in results] == [201, 201, 422]
    assert [result["classification"] for result in results] == [
        "success",
        "success",
        "http_client_error",
    ]

    persisted_summary = json.loads((run_dir / "summary.json").read_text())
    assert persisted_summary["failed"] == 1


@pytest.mark.asyncio
async def test_jsonl_executes_with_same_pipeline(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "customers.jsonl"
    jsonl_path.write_text(
        '{"email":"alice@example.com","first_name":"Alice"}\n'
        '{"email":"bob@example.com","first_name":"Bob"}\n',
        encoding="utf-8",
    )

    received: list[dict[str, str]] = []
    transport = httpx.ASGITransport(app=build_fake_api(received))
    async with httpx.AsyncClient(transport=transport) as client:
        summary = await ExecutionEngine(client).run(
            config=make_config(jsonl_path),
            input_path=jsonl_path,
            output_root=tmp_path / "runs",
        )

    assert summary.total == 2
    assert summary.failed == 0
    assert [item["email"] for item in received] == ["alice@example.com", "bob@example.com"]


@pytest.mark.asyncio
async def test_preflight_failure_causes_no_remote_side_effects(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "customers.jsonl"
    jsonl_path.write_text(
        '{"email":"alice@example.com","first_name":"Alice"}\n'
        '{"email":"bob@example.com"}\n',
        encoding="utf-8",
    )

    received: list[dict[str, str]] = []
    transport = httpx.ASGITransport(app=build_fake_api(received))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(MappingError, match=r"Input record 2.*first_name"):
            await ExecutionEngine(client).run(
                config=make_config(jsonl_path),
                input_path=jsonl_path,
                output_root=tmp_path / "runs",
            )

    assert received == []
    assert not (tmp_path / "runs").exists()


@pytest.mark.asyncio
async def test_result_classifies_server_error(tmp_path: Path) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text("email,first_name\na@example.com,Alice\n", encoding="utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="temporarily unavailable", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await ExecutionEngine(client).run(
            config=make_config(csv_path),
            input_path=csv_path,
            output_root=tmp_path / "runs",
        )

    result = json.loads(
        (Path(summary.run_directory) / "results.jsonl").read_text(encoding="utf-8").strip()
    )
    assert result["classification"] == "http_server_error"
    assert result["status_code"] == 503


@pytest.mark.asyncio
async def test_result_classifies_network_error(tmp_path: Path) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text("email,first_name\na@example.com,Alice\n", encoding="utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await ExecutionEngine(client).run(
            config=make_config(csv_path),
            input_path=csv_path,
            output_root=tmp_path / "runs",
        )

    result = json.loads(
        (Path(summary.run_directory) / "results.jsonl").read_text(encoding="utf-8").strip()
    )
    assert result["classification"] == "network_error"
    assert result["status_code"] is None
