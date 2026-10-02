from __future__ import annotations

import pytest

from bulkrelay.execution.shutdown import ShutdownController, ShutdownRequest


def test_shutdown_controller_escalates_second_request() -> None:
    shutdown = ShutdownController()

    assert shutdown.request_stop() is ShutdownRequest.GRACEFUL
    assert shutdown.stop_requested is True
    assert shutdown.force_requested is False

    assert shutdown.request_stop() is ShutdownRequest.FORCE
    assert shutdown.force_requested is True


@pytest.mark.asyncio
async def test_force_waiter_unblocks_after_escalation() -> None:
    shutdown = ShutdownController()

    shutdown.request_stop()
    shutdown.request_stop()

    await shutdown.wait_for_force()
