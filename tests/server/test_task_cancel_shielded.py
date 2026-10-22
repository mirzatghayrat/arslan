"""A cancelled turn's task is recorded as cancelled even when the cancellation keeps coming.

Found while C2a put the test databases on memory v2 (every real turn then runs as a task): a window
that disconnected while its turn was still finishing left the task "running", and the
conversation's next message failed with TASK_REVIEW_REQUIRED (task_version_conflict: one active
task per conversation) until a restart. Cause: _run marked the task cancelled with an await inside
its `except CancelledError`, and a level-triggered cancel scope (anyio, which Starlette's websocket
handling uses) cancels that await too.
"""
import asyncio

import anyio

from server.services.task_repository import repository
from tests.server.test_job_checks_0159 import _answer_check, run_contract


async def _phase(task_id="job-checks"):
    async with repository() as repo:
        return (await repo.get(task_id)).phase


async def _eventually(predicate, seconds=3.0):
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.02)
    return False


async def test_a_task_cancelled_by_a_level_triggered_scope_ends_cancelled(execution_db):
    started = asyncio.Event()

    async def body(emit):
        started.set()
        await asyncio.Event().wait()             # a turn still working (or finishing) when cancelled

    async with anyio.create_task_group() as group:
        group.start_soon(run_contract, [_answer_check()], body)
        await started.wait()
        group.cancel_scope.cancel()              # re-delivered at every await inside the scope

    async def cancelled():
        return await _phase() == "cancelled"
    assert await _eventually(cancelled), await _phase()


async def test_the_next_turn_in_that_conversation_is_not_blocked(execution_db):
    started = asyncio.Event()

    async def body(emit):
        started.set()
        await asyncio.Event().wait()

    async with anyio.create_task_group() as group:
        group.start_soon(run_contract, [_answer_check()], body)
        await started.wait()
        group.cancel_scope.cancel()

    async def cancelled():
        return await _phase() == "cancelled"
    assert await _eventually(cancelled)

    async def answer(emit):
        return "Done."
    spec_id = "job-checks-2"
    from arslan.companion.contracts import TaskSpec
    from server.services import task_service
    spec = TaskSpec.model_validate({"id": spec_id, "instruction": "Check fixture", "locale": "en",
                                    "scope": {"kind": "task", "owner_id": "local", "task_id": spec_id},
                                    "acceptance": [_answer_check().model_dump()]})
    async with repository() as repo:
        created = await repo.create(spec, "validation")     # run_contract's conversation: one active task each
        started_row = await repo.start(spec.id, created["version"])
    await task_service._launch(started_row, lambda event: None, answer)
    assert await _phase(spec_id) == "succeeded"


async def test_the_runtime_is_cleaned_up_and_the_stop_checkpointed_too(execution_db):
    # ③Hands' review: _run's finally awaited the final checkpoint under `except Exception`; a re-delivered
    # cancel skipped the rest, leaving the runtime open and registered and the lease active.
    from sqlalchemy import select

    from server.db.task_models import TaskEvent
    from server.services import personal_context, task_service
    started, seen = asyncio.Event(), {}

    async def body(emit):
        seen["runtime"] = task_service.current()
        seen["lease"] = personal_context.current().lease
        started.set()
        await asyncio.Event().wait()

    async with anyio.create_task_group() as group:
        group.start_soon(run_contract, [_answer_check()], body)
        await started.wait()
        group.cancel_scope.cancel()

    runtime = seen["runtime"]

    async def closed():
        return runtime.closed
    assert await _eventually(closed)
    assert runtime.task_id not in task_service._runtimes
    assert not any(owner == runtime.task_id for owner in task_service._run_owners.values())
    assert seen["lease"].active is False
    assert task_service.current() is None

    async def stopped():
        async with execution_db() as db:
            kinds = (await db.scalars(select(TaskEvent.kind).where(TaskEvent.task_id == runtime.task_id))).all()
        return "attempt_stopped" in kinds
    assert await _eventually(stopped)


async def test_the_stop_step_still_runs_when_the_cancel_record_was_cancelled():
    from server.services import task_service
    record, ran = asyncio.get_running_loop().create_future(), []

    async def checkpoint():
        ran.append(True)
    record.cancel()
    await task_service._after(record, checkpoint)        # a factory: built only once it will run
    assert ran == [True]


async def test_a_cancel_aimed_at_the_stop_step_itself_is_not_swallowed():
    # ③Hands' re-review: _after swallowed every exception from the cancel record, including a
    # cancel of its own task (loop shutdown), and then ran the checkpoint anyway.
    import pytest

    from server.services import task_service
    record, ran = asyncio.get_running_loop().create_future(), []

    async def checkpoint():
        ran.append(True)
    step = asyncio.ensure_future(task_service._after(record, checkpoint))
    await asyncio.sleep(0)                       # waiting for the record
    step.cancel()
    with pytest.raises(asyncio.CancelledError):
        await step
    assert ran == []
