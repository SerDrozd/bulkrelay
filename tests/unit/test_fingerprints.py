from __future__ import annotations

from pathlib import Path

from bulkrelay.config.models import JobConfig
from bulkrelay.state.fingerprints import fingerprint_file, fingerprint_job


def make_config(input_file: str) -> JobConfig:
    return JobConfig.model_validate(
        {
            "version": 1,
            "input": {"file": input_file},
            "request": {
                "method": "POST",
                "url": "https://api.example.com/users",
                "headers": {"Authorization": "Bearer secret-value"},
                "json": {"email": {"from": "email"}},
            },
            "retry": {"statuses": [503, 429]},
        }
    )


def test_file_fingerprint_changes_with_content(tmp_path: Path) -> None:
    path = tmp_path / "users.csv"
    path.write_text("email\na@example.com\n", encoding="utf-8")
    first = fingerprint_file(path)

    path.write_text("email\nb@example.com\n", encoding="utf-8")
    second = fingerprint_file(path)

    assert first != second


def test_job_fingerprint_ignores_input_location_but_not_request_semantics() -> None:
    first = make_config("old/customers.csv")
    moved = make_config("new/customers.csv")
    changed = make_config("new/customers.csv").model_copy(
        update={
            "request": make_config("new/customers.csv").request.model_copy(
                update={"headers": {"Authorization": "Bearer another-secret"}}
            )
        }
    )

    assert fingerprint_job(first) == fingerprint_job(moved)
    assert fingerprint_job(first) != fingerprint_job(changed)
