"""tests/server/test_run_registry.py"""
import asyncio

import pytest

from server.services import run_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    run_registry._tasks.clear()
    run_registry._by_conversation.clear()
    yield
    run_registry._tasks.clear()
    run_registry._by_conversation.clear()


@pytest.mark.asyncio
async def test_register_lookup_unregister():
    async def _work():
        await asyncio.sleep(30)

    task = asyncio.create_task(_work())
    run_registry.register(7, "conv-a", task)
    assert run_registry.get(7) is task
    assert run_registry.active_for("conv-a") == [7]

    run_registry.unregister(7, "conv-a")
    assert run_registry.get(7) is None
    assert run_registry.active_for("conv-a") == []
    task.cancel()


@pytest.mark.asyncio
async def test_cancel_returns_true_once_then_false():
    async def _work():
        await asyncio.sleep(30)

    task = asyncio.create_task(_work())
    run_registry.register(8, "conv-b", task)
    assert run_registry.cancel(8) is True
    # second cancel: task already cancelling — still True until unregistered
    run_registry.unregister(8, "conv-b")
    assert run_registry.cancel(8) is False  # unknown run id
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancel_finished_task_returns_false():
    async def _noop():
        return 1

    task = asyncio.create_task(_noop())
    await task
    run_registry.register(9, "conv-c", task)
    assert run_registry.cancel(9) is False  # task already done — nothing to cancel
