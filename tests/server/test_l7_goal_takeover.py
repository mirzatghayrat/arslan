"""L7-5h, the user's decision of 11-17 (a change to Q0): a new `/goal` takes over from a goal that isn't running.

The L7-7 bench's T8 (goal on, 0/6 over two rounds): turn 2's goal ended waiting for review (its "section 2 is shorter,
the others unchanged" check could not be judged from the file alone), so turn 3's `/goal` answered goal_exists and
never ran. A goal waiting for review, not started (also the row a late cancel leaves), paused, stuck or out of budget
is now left for the user to look over, keeping its record and card, and the new goal is set. Only a running goal
answers goal_exists.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from server.db.models import CompanionTask
from server.db.task_models import TaskEvent
from server.services import background_jobs, goal_command, runtime_messages
from server.services.goal_mode import GoalSpec
from server.services.task_repository import TaskError, repository
from tests.server import test_l7_goal_start as _start
from tests.server.test_l7_goal_start import CID, PROMPT, Model, _say

active, fresh, jobs, model = _start.active, _start.fresh, _start.jobs, _start.model   # its fixtures, as they are

NEXT = "Add a table of the key numbers to report.md"


async def _goals(execution_db) -> list[CompanionTask]:
    async with execution_db() as db:
        rows = (await db.scalars(select(CompanionTask).where(CompanionTask.conversation_id == CID)
                                 .order_by(CompanionTask.created_at))).all()
    return [row for row in rows if row.privacy.get("driver") == {"kind": "background", "goal": True}]


async def _set_state(row, **changes):
    async with repository() as repo:
        await repo._advance(await repo.get(row.id), "state_changed", changes=changes)


@pytest.mark.parametrize("state", [
    pytest.param({"pause_reason": "acceptance_review_required"}, id="review"),
    pytest.param({}, id="not-started"),
    pytest.param({"pause_reason": "goal_paused"}, id="paused"),
    pytest.param({"pause_reason": "goal_blocked"}, id="blocked"),
])
async def test_a_new_goal_takes_over_from_one_that_is_not_running(execution_db, active, model, jobs, state):
    await _say(f"/goal {PROMPT}")
    (old,) = await _goals(execution_db)
    old_spec = old.privacy["goal_spec"]
    if state:
        await _set_state(old, **state)
    line = await _say(f"/goal {NEXT}")
    assert line.endswith(runtime_messages.render("goal_left", "en")), line
    earlier, new = await _goals(execution_db)
    assert earlier.id == old.id and new.id != old.id
    assert (new.phase, new.pause_reason) == ("waiting_user", "goal_not_started")
    assert GoalSpec.model_validate(new.privacy["goal_spec"]).objective == NEXT
    # The earlier goal keeps its record: its spec, its row and its events, now waiting as "look over the result".
    assert (earlier.phase, earlier.pause_reason) == ("waiting_user", "acceptance_review_required")
    assert earlier.privacy["goal_spec"] == old_spec and earlier.privacy["goal_left_for"] == new.id
    async with execution_db() as db:
        kinds = (await db.scalars(select(TaskEvent.kind).where(TaskEvent.task_id == old.id))).all()
    assert kinds[-1] == "goal_left"
    # The new one starts as any goal does.
    await _say("/goal start confirm")
    assert [job.job_id for job in jobs] == [new.id]


async def test_the_earlier_goals_card_is_sent_again_reading_look_over_the_result(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    (old,) = await _goals(execution_db)
    await _say(f"/goal {NEXT}")
    frames = []
    await goal_command.publish(CID, frames.append)
    states = {frame["job_id"]: frame["goal_state"]["status"] for frame in frames}
    new = (await _goals(execution_db))[1]
    assert states == {old.id: "review", new.id: "not_started"}


@pytest.mark.parametrize("running", ["row", "job"])
async def test_a_running_goal_still_answers_goal_exists(execution_db, active, model, jobs, monkeypatch, running):
    await _say(f"/goal {PROMPT}")
    (old,) = await _goals(execution_db)
    if running == "row":
        await _set_state(old, phase="running", pause_reason=None)
    else:                                                 # queued behind other jobs: its row still waits
        monkeypatch.setattr(background_jobs, "goal_job", lambda task_id: object() if task_id == old.id else None)
    asked = len(model.requests)
    assert await _say(f"/goal {NEXT}") == runtime_messages.render("goal_exists", "en")
    assert len(model.requests) == asked and len(await _goals(execution_db)) == 1


class StartsMeanwhile(Model):
    """While the new goal is drafted, the earlier one is started (another window's Start)."""

    def __init__(self, execution_db):
        super().__init__()
        self.execution_db, self.armed = execution_db, False

    async def chat(self, system, user, history=None, tools=None, **kw):
        if self.armed:
            (old,) = await _goals(self.execution_db)
            await _set_state(old, phase="running", pause_reason=None)
        return await super().chat(system, user, history, tools, **kw)


async def test_a_goal_started_while_the_new_one_was_drafted_keeps_running_and_no_second_goal_is_set(
        execution_db, active, jobs, monkeypatch):
    from server.orchestrator import tool_loop
    drafter = StartsMeanwhile(execution_db)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: drafter)
    await _say(f"/goal {PROMPT}")
    drafter.armed = True
    with pytest.raises(TaskError, match="task_version_conflict"):
        await _say(f"/goal {NEXT}")
    (old,) = await _goals(execution_db)
    assert old.phase == "running" and "goal_left_for" not in old.privacy
