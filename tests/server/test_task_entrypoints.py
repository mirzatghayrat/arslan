"""Production entry wrappers against an isolated durable task database."""
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from arslan.execution_budget import BudgetExceeded, current as budget
from server.db.models import CompanionTask, TaskAttempt
from server.services import personal_context as pc, task_context, task_service
from server.services.task_repository import TaskError, repository


@pytest.fixture
def active_context(monkeypatch):
    monkeypatch.setattr(task_context, "is_active", AsyncMock(return_value=True))
    async def load(cid, **kwargs):
        return pc.TaskMemoryContext(task_id="entry-task", run_id="initial", conversation_id=cid,
                                    no_learning=True, query=kwargs.get("retrieval_query") or kwargs.get("user_message", ""))
    monkeypatch.setattr(task_context, "load", load)


async def test_direct_expert_entry_persists_driver_and_resumes_same_budget(execution_db, active_context, monkeypatch):
    calls = []
    @task_context.scoped_dispatch
    async def expert(cid, spawn_id, brief, emit, **kwargs):
        assert pc.current().query == brief
        assert pc.current().explicit_save_digest is None
        calls.append((spawn_id, brief, budget().id, budget().tool_calls, pc.current().no_learning))
        budget().tool()
        task_service.current().pause_reason = "task_no_progress"
        return "Partial evidence, not completion"
    assert await expert("entry", 7, "Verify the supplied artifact", lambda event: None) == "Partial evidence, not completion"
    async with repository() as repo:
        row = await repo.get("entry-task")
        assert row.phase == "waiting_user" and row.pause_reason == "task_no_progress"
        assert row.privacy["driver"] == {"kind": "expert", "id": 7}
        version = row.version
    monkeypatch.setattr("server.orchestrator.arslan._dispatch_spawn", expert)
    await task_service.resume_turn("entry-task", version, "entry", lambda event: None)
    assert calls[1] == (7, "Verify the supplied artifact", calls[0][2], 1, True)
    async with execution_db() as db:
        assert len((await db.scalars(select(TaskAttempt))).all()) == 2
        row = await db.get(CompanionTask, "entry-task")
        assert row.budget["used"]["tool_calls"] == 2


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


async def test_refinement_keeps_original_goal_in_durable_spec(execution_db, active_context):
    @task_context.scoped_dispatch
    async def expert(cid, spawn_id, brief, emit, **kwargs):
        return None
    await expert("entry", 7, "Compare the supplied designs", lambda event: None,
                 instruction="Make the comparison shorter", user_message="Keep the accessibility findings")
    async with repository() as repo:
        spec = await repo.spec(await repo.get("entry-task"))
        assert "Compare the supplied designs" in spec.instruction
        assert "Make the comparison shorter" in spec.instruction
        assert "Keep the accessibility findings" in spec.instruction


@pytest.mark.parametrize("driver", [[], "expert", {}, {"kind": "expert", "id": True}])
def test_malformed_saved_driver_fails_closed(driver):
    with pytest.raises(TaskError, match="task_invalid_driver"):
        task_service.checked_driver(driver)


async def test_active_recipe_approval_resume_preserves_task_and_spent_budget(execution_db, active_context, monkeypatch):
    from server.api import recipes as api
    from server.services import recipes
    from tests.server.test_recipes import read, seed, spec
    execution_id, version_id = await seed(execution_db, spec(approval=True))
    calls = []
    async def dispatch(cid, **kwargs):
        budget().tool()
        calls.append((kwargs["task_brief"].split("\n")[0], budget().id))
        return {"full_output": calls[-1][0]}
    monkeypatch.setattr(recipes.dispatcher, "dispatch", dispatch)
    await recipes.execute(execution_id)
    task_id = f"recipe-task:{execution_id}"
    async with repository() as repo:
        row = await repo.get(task_id)
        assert row.phase == "waiting_user" and row.pause_reason == "task_input_required"
        assert row.privacy["driver"] == {"kind": "recipe", "id": execution_id, "version_id": version_id}
        assert row.budget["used"]["tool_calls"] == 2
    monkeypatch.setattr(recipes, "launch", lambda execution_id: None)
    await api.resume_execution(execution_id, api.Resume(approve_steps=["c"]))
    await recipes.execute(execution_id)
    assert [name for name, _ in calls].count("A") == 1 and len(calls) == 3
    assert len({identity for _, identity in calls}) == 1
    assert (await read(execution_db, execution_id)).status == "completed"
    async with repository() as repo:
        row = await repo.get(task_id)
        assert row.budget["used"]["tool_calls"] == 3
        assert row.pause_reason == "acceptance_review_required"


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
