from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from bulkrelay.config.models import JobConfig
from bulkrelay.execution.engine import ExecutionEngine


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
    config = JobConfig.model_validate(
        {
            "version": 1,
            "input": {"file": str(csv_path)},
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
        }
    )

    received: list[dict[str, str]] = []
    transport = httpx.ASGITransport(app=build_fake_api(received))
    async with httpx.AsyncClient(transport=transport) as client:
        summary = await ExecutionEngine(client).run(
            config=config,
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

    persisted_summary = json.loads((run_dir / "summary.json").read_text())
    assert persisted_summary["failed"] == 1
