"""Production entry wrappers against an isolated durable task database."""

import pytest
from sqlalchemy import select

from arslan.execution_budget import BudgetExceeded
from server.db.models import CompanionTask
from server.services import personal_context as pc, task_context, task_service
from server.services.task_repository import TaskError, repository


@pytest.fixture
def active_context(monkeypatch):
    async def load(cid, **kwargs):
        return pc.TaskMemoryContext(task_id="entry-task", run_id="initial", conversation_id=cid,
                                    no_learning=True, query=kwargs.get("retrieval_query") or kwargs.get("user_message", ""))
    monkeypatch.setattr(task_context, "load", load)


async def test_headless_entry_does_not_regrant_remember_authority(execution_db, active_context):
    ctx = pc.TaskMemoryContext(task_id="entry-task", run_id="initial", conversation_id="entry",
        explicit_save_digest="saved-command", explicit_save_ref="old-message", allow_global_save=True)
    async def body(emit):
        assert pc.current().explicit_save_digest is None
        assert pc.current().explicit_save_ref is None and not pc.current().allow_global_save
        raise BudgetExceeded("model_requests")
    with pc.bind(ctx), pytest.raises(BudgetExceeded):
        await task_context.execute_entry("entry", "remember old text", lambda event: None, body, headless=True)
    async with repository() as repo:
        row = await repo.get("entry-task")
        assert row.phase == "waiting_user" and row.pause_reason == "task_budget_exhausted"


@pytest.mark.parametrize("driver", [[], "expert", {}, {"kind": "expert", "id": True}])
def test_malformed_saved_driver_fails_closed(driver):
    with pytest.raises(TaskError, match="task_invalid_driver"):
        task_service.checked_driver(driver)


async def test_scheduled_pause_is_not_recorded_as_success(execution_db, active_context, monkeypatch):
    from server.db.models import ScheduledTask, ScheduledTaskRun
    from server.services import scheduler
    async with execution_db() as db:
        scheduled = ScheduledTask(name="Synthetic check", prompt="Check fixture", target="arslan",
                                  schedule_kind="interval", interval_s=3600, enabled=True)
        db.add(scheduled)
        await db.commit()
    async def paused(cid, prompt):
        assert pc.current().no_learning and pc.current().explicit_save_digest is None
        task_service.current().pause_reason = "task_no_progress"
    monkeypatch.setattr(scheduler, "run_arslan_turn", paused)
    await scheduler._fire(scheduled)
    async with execution_db() as db:
        outcome = (await db.scalars(select(ScheduledTaskRun))).one()
        row = await db.get(CompanionTask, "entry-task")
        assert outcome.outcome == "error"
        assert row.phase == "waiting_user" and row.pause_reason == "task_no_progress"
