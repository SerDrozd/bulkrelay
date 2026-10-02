from __future__ import annotations

import asyncio
from enum import StrEnum


class ShutdownRequest(StrEnum):
    GRACEFUL = "graceful"
    FORCE = "force"


class ShutdownController:
    """Coordinate cooperative and forced shutdown of a running job.

    The first request asks the scheduler to stop starting new records while
    allowing currently in-flight records to finish. A second request asks it
    to cancel the remaining in-flight tasks immediately.
    """

    def __init__(self) -> None:
        self._graceful = asyncio.Event()
        self._force = asyncio.Event()

    @property
    def stop_requested(self) -> bool:
        return self._graceful.is_set()

    @property
    def force_requested(self) -> bool:
        return self._force.is_set()

    def request_stop(self) -> ShutdownRequest:
        if not self._graceful.is_set():
            self._graceful.set()
            return ShutdownRequest.GRACEFUL

        self._force.set()
        return ShutdownRequest.FORCE

    async def wait_for_force(self) -> None:
        await self._force.wait()
