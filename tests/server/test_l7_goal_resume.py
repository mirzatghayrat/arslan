"""L7-4: Resume as a re-queued job, the boot pass skipping goal rows, `resume_turn` refusing them, and the restart
matrix (docs/plans/0164/L7-goal-mode.md, "Resume re-queues the job", "Restart and app quit", Decisions Q0, Q3-Q5).

Offline: a scripted adapter stands in for the model, and the goal's rounds run through the real `run_native`. The
restarts use the real boot pass (`task_service.recover_interrupted`, then `background_jobs.report_interrupted`).
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from arslan.execution_budget import current as current_budget
from server.db.models import ArslanMessage, CompanionTask
from server.orchestrator import tool_loop
from server.services import background_jobs, task_service, task_validation
from server.services.goal_mode import GoalProgress, GoalSpec
from server.services.task_repository import TaskError, repository

from tests.server import test_l7_goal_start as start
from tests.server.test_l7_goal_start import CID, DRAFT, PROMPT, _row, _say

active, fresh, model = start.active, start.fresh, start.model        # L7-3's fixtures, shared

NOTES = {"criteria": [DRAFT["criteria"][0]]}          # notes.md names INV-07: one file_contains check


@pytest.fixture
def disk(monkeypatch, tmp_path):
    async def context(started_at):
        return {"roots": [tmp_path.resolve()], "workspace": tmp_path.resolve(), "since": None}
    monkeypatch.setattr(task_validation, "_disk_context", context)
    (tmp_path / "notes.md").write_text("nothing yet")
    return tmp_path


@pytest.fixture
def turns(monkeypatch):
    """Each goal turn's start: its saved goal record and budget, as the task runtime carries them in."""
    seen, native = [], tool_loop.run_native

    async def recorded(**kwargs):
        runtime = task_service.current()
        seen.append({"goal": runtime.progress.goal, "tool_calls": current_budget().tool_calls})
        return await native(**kwargs)
    monkeypatch.setattr(tool_loop, "run_native", recorded)

    async def never(*args, **kwargs):
        raise AssertionError("a goal never resumes through resume_turn")
    monkeypatch.setattr(task_service, "resume_turn", never)
    return seen


async def _finish(row_id: str) -> background_jobs.Job:
    job = background_jobs.goal_job(row_id)
    assert job is not None
    await asyncio.wait_for(job.task, 20)
    return job


async def _record(row_id: str) -> GoalProgress:
    async with repository() as repo:
        saved = await repo.latest_checkpoint(row_id)
    return GoalProgress.model_validate(saved["progress"]["goal"])


async def _blocked(execution_db, model) -> CompanionTask:
    """A goal blocked at round 3: notes.md never names INV-07, so no round makes progress."""
    model.draft = NOTES
    await _say(f"/goal {PROMPT}")
    row = await _row(execution_db)
    await _say("/goal start")
    await _finish(row.id)
    row = await _row(execution_db)
    assert (row.phase, row.pause_reason) == ("waiting_user", "goal_blocked")
    return row


async def _set(row_id: str, **changes) -> None:
    async with repository() as repo:
        await repo._advance(await repo.get(row_id), "state_changed", changes=changes)


async def _boot() -> None:
    await task_service.recover_interrupted()
    await background_jobs.report_interrupted()


# -- Resume re-queues the job ------------------------------------------------------------------------------------

async def test_resume_after_a_block_requeues_the_row_with_a_fresh_streak_and_the_seen_set_kept(
        execution_db, active, model, disk, turns):
    row = await _blocked(execution_db, model)
    before = await _record(row.id)
    assert (before.round, before.stall, before.status) == (3, 3, "blocked") and before.seen
    (disk / "notes.md").write_text("Reconciled INV-07")
    assert (await _say("/goal resume")).startswith("Goal resumed")
    job = await _finish(row.id)
    resumed = turns[-1]["goal"]
    assert (resumed.round, resumed.stall, resumed.status) == (3, 0, "active")
    assert resumed.seen == before.seen                  # returning to an old measure after Resume isn't progress
    after = await _record(row.id)
    assert after.round == 4 and after.status == "complete"
    assert (await _row(execution_db)).phase == "succeeded" and job.outcome == "done"


async def test_resume_without_progress_keeps_the_seen_set_so_an_old_measure_is_not_new(
        execution_db, active, model, disk, turns):
    row = await _blocked(execution_db, model)
    await _say("/goal resume")
    await _finish(row.id)
    record = await _record(row.id)
    # A fresh streak: three more rounds, none with a measure the seen set doesn't already hold.
    assert (record.round, record.stall, record.status) == (6, 3, "blocked")


@pytest.mark.parametrize("pause_reason", ["task_budget_exhausted", "process_interrupted"],
                         ids=["budget-limited", "interrupted in wrap-up"])
async def test_resume_gets_a_fresh_budget_of_the_goals_own_tier_and_cap(pause_reason, execution_db, active, model,
                                                                        disk, turns):
    row = await _blocked(execution_db, model)
    spent = dict(row.budget)
    spent["used"] = {**spent["used"], "tool_calls": spent["limits"]["tool_calls"]}
    await _set(row.id, budget=spent, pause_reason=pause_reason)
    (disk / "notes.md").write_text("Reconciled INV-07")
    await _say("/goal resume")
    await _finish(row.id)
    assert turns[-1]["tool_calls"] == 0
    row = await _row(execution_db)
    spec = GoalSpec.model_validate(row.privacy["goal_spec"])
    assert row.phase == "succeeded" and row.budget["limits"] == spent["limits"]
    assert row.budget["spend"]["usd_cap"] == spec.usd_cap          # never raised


async def test_resume_never_starts_a_goal_that_isnt_started(execution_db, active, model, disk, turns):
    model.draft = NOTES
    await _say(f"/goal {PROMPT}")
    row = await _row(execution_db)
    assert "not_started" in await _say("/goal resume")
    assert background_jobs.goal_job(row.id) is None and turns == []
    with pytest.raises(TaskError, match="task_cannot_start"):      # nor the job's own path, given a not-started row
        async with repository() as repo:
            await repo.resume_goal(row.id, row.version)
    assert ((await _row(execution_db)).pause_reason, len(model.requests)) == ("goal_not_started", 1)


async def test_the_goal_resume_path_runs_no_other_row(execution_db, active, monkeypatch):
    from server.services import personal_context as pc, task_context
    ctx = pc.TaskMemoryContext(task_id="plain", run_id="plain", conversation_id=CID, no_learning=True)

    async def attempt(emit):
        task_service.current().pause_reason = "task_no_progress"
        return "Partial"

    async def load(cid, **kwargs):
        return ctx
    monkeypatch.setattr(task_context, "load", load)
    await task_context.execute_entry(CID, "Plain work", lambda event: None, attempt, driver={"kind": "background"})
    async with repository() as repo:
        row = await repo.get("plain")
    with pytest.raises(TaskError, match="task_invalid_driver"):
        await task_service.prepare_resume("plain", row.version, CID, ctx, goal=True)


async def test_resume_turn_still_refuses_a_blocked_goal_row(execution_db, active, model, disk, monkeypatch):
    row = await _blocked(execution_db, model)
    from server.orchestrator import arslan
    answered = []

    async def answer(*args, **kwargs):
        answered.append(args)
    monkeypatch.setattr(arslan, "_handle_answer", answer)
    with pytest.raises(TaskError, match="task_invalid_driver"):
        await task_service.resume_turn(row.id, row.version, CID, lambda event: None)
    assert answered == [] and (await _row(execution_db)).version == row.version


# -- the boot pass and the restart matrix ------------------------------------------------------------------------

async def test_boot_leaves_an_interrupted_goal_interrupted_and_resume_reruns_that_round(
        execution_db, active, model, disk, turns):
    """Quit during a model or tool call, or between a verdict and its checkpoint: the last recorded round is the
    one resumed, and nothing cancels the row."""
    row = await _blocked(execution_db, model)
    plain = background_jobs.start_placed(CID, "Plain job", [], (None, None), outside_seen=False)
    await asyncio.wait_for(plain.task, 20)
    for task_id in (row.id, plain.job_id):              # both were running when the app quit
        await _set(task_id, phase="running", pause_reason=None)
    await _boot()
    goal, other = await _row(execution_db), None
    async with execution_db() as db:
        other = await db.get(CompanionTask, plain.job_id)
        notes = (await db.scalars(select(ArslanMessage).where(ArslanMessage.job_outcome == "interrupted"))).all()
    assert (goal.phase, goal.pause_reason) == ("waiting_user", "process_interrupted")
    assert other.phase == "cancelled" and len(notes) == 1            # a plain job is closed as before
    assert "interrupted, round 3" in await _say("/goal status")
    (disk / "notes.md").write_text("Reconciled INV-07")
    await _say("/goal resume")
    await _finish(row.id)
    assert turns[-1]["goal"].round == 3 and (await _record(row.id)).round == 4


@pytest.mark.parametrize("pause_reason", ["goal_paused", "goal_blocked", "task_budget_exhausted", "goal_not_started"])
async def test_boot_leaves_a_paused_blocked_budget_limited_or_not_started_goal_unchanged(
        pause_reason, execution_db, active, model, disk, turns):
    model.draft = NOTES
    await _say(f"/goal {PROMPT}")
    row = await _row(execution_db)
    if pause_reason != "goal_not_started":
        await _set(row.id, pause_reason=pause_reason)
    before = await _row(execution_db)
    await _boot()
    after = await _row(execution_db)
    assert (after.phase, after.pause_reason, after.version) == (before.phase, before.pause_reason, before.version)
    assert background_jobs.active() == [] and turns == []            # Q0, Q5: nothing runs after a restart


async def test_a_goal_completed_but_not_posted_is_posted_once_on_boot(execution_db, active, model, disk, turns):
    model.draft = NOTES
    (disk / "notes.md").write_text("Reconciled INV-07")
    await _say(f"/goal {PROMPT}")
    row = await _row(execution_db)
    await _say("/goal start")
    await _finish(row.id)

    async def posts():
        async with execution_db() as db:
            return (await db.scalars(select(ArslanMessage).where(ArslanMessage.conversation_id == CID,
                                                                 ArslanMessage.job_outcome == "done"))).all()
    assert len(await posts()) == 1
    await _boot()
    assert len(await posts()) == 1                      # posted when it finished: not again
    row = await _row(execution_db)
    privacy = {key: value for key, value in row.privacy.items() if key != "goal_posted"}
    await _set(row.id, privacy=privacy)                 # the quit came between "complete" and the post
    await _boot()
    posted = await posts()
    assert len(posted) == 2 and "Reconciled." in posted[-1].content
    await _boot()
    assert len(await posts()) == 2
