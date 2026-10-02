from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

app = FastAPI(title="BulkRelay Fake Target API")


class UserIn(BaseModel):
    email: str
    first_name: str
    source: str


@app.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(user: UserIn) -> dict[str, Any]:
    """Predictable target used by examples and manual testing."""
    if user.email == "reject@example.com":
        raise HTTPException(status_code=422, detail="fake API rejected this record")
    return {"created": True, "user": user.model_dump()}
