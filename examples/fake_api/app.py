from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel

app = FastAPI(title="BulkRelay Fake Target API")
_attempts: defaultdict[tuple[str, str], int] = defaultdict(int)


class UserIn(BaseModel):
    email: str
    first_name: str
    source: str


def _attempt(endpoint: str, email: str) -> int:
    key = (endpoint, email)
    _attempts[key] += 1
    return _attempts[key]


@app.post("/reset")
async def reset() -> dict[str, bool]:
    """Reset deterministic failure counters used by reliability demos."""
    _attempts.clear()
    return {"reset": True}


@app.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(user: UserIn) -> dict[str, Any]:
    """Predictable target used by the correctness examples."""
    if user.email == "reject@example.com":
        raise HTTPException(status_code=422, detail="fake API rejected this record")
    return {"created": True, "user": user.model_dump()}


@app.post("/unstable/users", status_code=status.HTTP_201_CREATED)
async def create_unstable_user(user: UserIn) -> dict[str, Any]:
    """Return 503 twice per email, then recover."""
    attempt = _attempt("unstable", user.email)
    if attempt <= 2:
        raise HTTPException(status_code=503, detail=f"temporary failure {attempt}")
    return {"created": True, "attempt": attempt, "user": user.model_dump()}


@app.post("/rate-limited/users", status_code=status.HTTP_201_CREATED)
async def create_rate_limited_user(user: UserIn, response: Response) -> dict[str, Any]:
    """Return one 429 with Retry-After per email, then recover."""
    attempt = _attempt("rate-limited", user.email)
    if attempt == 1:
        response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
        response.headers["Retry-After"] = "1"
        return {"detail": "retry later", "attempt": attempt}
    return {"created": True, "attempt": attempt, "user": user.model_dump()}


@app.post("/slow/users", status_code=status.HTTP_201_CREATED)
async def create_slow_user(user: UserIn) -> dict[str, Any]:
    """Sleep long enough for a low read timeout to trigger over a real socket."""
    await asyncio.sleep(2)
    return {"created": True, "user": user.model_dump()}


@app.post("/always-unavailable/users")
async def always_unavailable(user: UserIn) -> None:
    """Always return 503 for retry-exhaustion demos."""
    _attempt("always-unavailable", user.email)
    raise HTTPException(status_code=503, detail="still unavailable")
