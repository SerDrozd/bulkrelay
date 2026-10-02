from __future__ import annotations

import pytest

from bulkrelay.execution.rate_limit import RateLimiter


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.mark.asyncio
async def test_rate_limiter_spaces_request_starts() -> None:
    fake = FakeTime()
    limiter = RateLimiter(2.0, sleep=fake.sleep, clock=fake.clock)

    starts: list[float] = []
    for _ in range(3):
        await limiter.acquire()
        starts.append(fake.clock())

    assert starts == [0.0, 0.5, 1.0]
    assert fake.sleeps == [0.5, 0.5]


@pytest.mark.asyncio
async def test_disabled_rate_limiter_never_sleeps() -> None:
    fake = FakeTime()
    limiter = RateLimiter(None, sleep=fake.sleep, clock=fake.clock)

    await limiter.acquire()
    await limiter.acquire()

    assert fake.sleeps == []
