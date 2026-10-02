from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class RateLimiter:
    """Pace request starts to a global requests-per-second ceiling."""

    def __init__(
        self,
        requests_per_second: float | None,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        self._interval = None if requests_per_second is None else 1.0 / requests_per_second
        self._sleep = sleep
        self._clock = clock
        self._next_available_at: float | None = None
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._interval is None:
            return

        async with self._lock:
            now = self._clock()
            target = now if self._next_available_at is None else max(now, self._next_available_at)
            delay = target - now
            if delay > 0:
                await self._sleep(delay)

            actual_start = self._clock()
            self._next_available_at = max(target, actual_start) + self._interval
