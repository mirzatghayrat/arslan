"""L7-5h, the user's decision and conditions of 11-17 (a change to Q0): a new `/goal` takes over from a goal that waits.

The L7-7 bench's T8 (goal on, 0/6 over two rounds): turn 2's goal ended waiting for review (its "section 2 is shorter,
the others unchanged" check can't be judged from the file alone), so turn 3's `/goal` answered goal_exists and never
ran.

The rule, decided by the command alone (goal_command.handle):
- acting on a goal, never a takeover: `/goal resume` and `/goal start` (each may name the goal's id), `/goal note`
  (the running goal), and Accept result (by the goal's own id);
- a new request: `/goal <objective>` takes over from a goal that waits; the earlier goal keeps its row, state, stop
  reason, checkpoints and card, and the reply says where it stopped and the exact command back to it;
- a plain chat message is a new request that sets no goal: it runs as a turn and changes no goal;
- while a goal runs, a new one answers goal_exists, as before.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from server.db.models import CompanionTask
from server.db.task_models import TaskEvent
from server.services import background_jobs, goal_command, runtime_messages
from server.services.goal_mode import GoalSpec
from server.services.task_repository import TaskError, repository
from tests.server import test_l7_goal_round as _round, test_l7_goal_start as _start
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


async def _events(execution_db, task_id) -> list[str]:
    async with execution_db() as db:
        return list((await db.scalars(select(TaskEvent.kind).where(TaskEvent.task_id == task_id)
                                      .order_by(TaskEvent.sequence))).all())


def _snapshot(row) -> tuple:
    return (row.phase, row.pause_reason, row.privacy["goal_spec"], row.results, row.budget)


# -- the rule: what acts on the waiting goal, and what is a new request ---------------------------------------------

async def test_goal_resume_acts_on_the_waiting_goal_and_never_takes_over(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    (old,) = await _goals(execution_db)
    await _set_state(old, pause_reason="goal_paused")
    assert await _say("/goal resume") == runtime_messages.render("goal_resumed", "en", objective=PROMPT)
    assert [job.job_id for job in jobs] == [old.id] and len(await _goals(execution_db)) == 1


async def test_goal_note_acts_on_the_running_goal_and_never_takes_over(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    (old,) = await _goals(execution_db)
    await _set_state(old, pause_reason="acceptance_review_required")
    before = await _goals(execution_db)
    assert await _say("/goal note the invoices are in inbox/") == runtime_messages.render("goal_not_running", "en")
    after = await _goals(execution_db)
    assert len(after) == 1 and _snapshot(after[0]) == _snapshot(before[0]) and after[0].version == before[0].version


async def _review_goal(execution_db, monkeypatch, tmp_path, model):
    """A real goal job that ended waiting for review (a check the judge could not say), as T8's turn 2 did, made this
    conversation's goal row."""
    (tmp_path / "answer.txt").write_text("6655.83")
    goal = _round._goal(_round._check(id="c1", kind="file_saved", path="answer.txt", phrases=()), _round._judged())
    _, task, record, _, _ = await _round._goal_turn(goal, monkeypatch, tmp_path, lambda n: "Summed.",
                                                    judge=lambda user: "null")
    assert (task.phase, task.pause_reason, record.status) == ("waiting_user", "acceptance_review_required", "review")
    async with repository() as repo:
        row = await repo.get(task.id)
        await repo._advance(row, "state_changed", changes={"conversation_id": CID, "privacy": {
            **row.privacy, "driver": {"kind": "background", "goal": True}, "goal_spec": goal.model_dump(mode="json")}})
    (old,) = await _goals(execution_db)
    from server.orchestrator import tool_loop
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)       # the drafting model again
    return old


async def test_accept_result_acts_on_the_waiting_goal_and_never_takes_over(execution_db, active, model, jobs,
                                                                          monkeypatch, tmp_path):
    old = await _review_goal(execution_db, monkeypatch, tmp_path, model)
    async with repository() as repo:
        assert await repo.accept_review(old.id, old.version)
    (accepted,) = await _goals(execution_db)
    assert accepted.phase == "succeeded" and model.requests == []


async def test_a_new_goal_is_a_new_request_and_takes_over_from_the_waiting_goal(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    (old,) = await _goals(execution_db)
    await _say(f"/goal {NEXT}")
    earlier, new = await _goals(execution_db)
    assert earlier.id == old.id and (new.phase, new.pause_reason) == ("waiting_user", "goal_not_started")
    assert GoalSpec.model_validate(new.privacy["goal_spec"]).objective == NEXT


async def test_a_plain_message_while_a_goal_waits_runs_as_a_turn_and_changes_no_goal(execution_db, active, model,
                                                                                     jobs, monkeypatch):
    from server.orchestrator import arslan
    from server.services import settings_service

    async def on(db):
        return True
    turns = []

    async def turn(conversation_id, user_message, emit, **kwargs):
        turns.append(user_message)
    monkeypatch.setattr(settings_service, "goal_mode", on)
    monkeypatch.setattr(arslan, "_handle_answer", turn)
    monkeypatch.setattr(arslan, "_after_turn_later", lambda *a, **k: None)
    await _say(f"/goal {PROMPT}")
    (old,) = await _goals(execution_db)
    await _set_state(old, pause_reason="acceptance_review_required")
    (before,) = await _goals(execution_db)
    await arslan.handle_user_message(CID, "Add a table of the key numbers to the report.", lambda event: None)
    assert turns == ["Add a table of the key numbers to the report."]
    (after,) = await _goals(execution_db)
    assert after.version == before.version and _snapshot(after) == _snapshot(before)


# -- the takeover reply, and nothing of the earlier goal lost ---------------------------------------------------------

@pytest.mark.parametrize("state,status,back", [
    pytest.param({"pause_reason": "acceptance_review_required"}, "review", "resume", id="review"),
    pytest.param({}, "not_started", "start", id="not-started"),
    pytest.param({"pause_reason": "goal_paused"}, "paused", "resume", id="paused"),
    pytest.param({"pause_reason": "goal_blocked"}, "blocked", "resume", id="blocked"),
])
async def test_the_reply_says_where_the_earlier_goal_stopped_that_it_is_kept_and_how_to_get_back(
        execution_db, active, model, jobs, state, status, back):
    await _say(f"/goal {PROMPT}")
    (old,) = await _goals(execution_db)
    if state:
        await _set_state(old, **state)
    (before,) = await _goals(execution_db)
    line = await _say(f"/goal {NEXT}")
    left = runtime_messages.render("goal_left", "en", objective=PROMPT, status=status, round=0,
                                   back=f"/goal {back} {old.id}")
    assert line.endswith("\n\n" + left), line
    assert PROMPT in left and f"stopped at {status}, round 0" in left and "kept as it was" in left
    assert f"send /goal {back} {old.id}" in left
    earlier, new = await _goals(execution_db)
    # Nothing of the earlier goal is lost: its state, its stop reason, its spec, its results, its budget.
    assert _snapshot(earlier) == _snapshot(before) and earlier.privacy["goal_left_for"] == new.id
    assert (await _events(execution_db, old.id))[-1] == "goal_left"


async def test_after_a_takeover_the_earlier_goal_resumes_by_the_command_the_reply_gave(execution_db, active, model,
                                                                                      jobs):
    await _say(f"/goal {PROMPT}")
    (old,) = await _goals(execution_db)
    await _set_state(old, pause_reason="goal_blocked")
    await _say(f"/goal {NEXT}")
    await _say(f"/goal resume {old.id}")
    (job,) = jobs
    assert job.job_id == old.id and job.goal_spec.objective == PROMPT
    # while it runs, the new goal waits: one goal runs at a time
    background_jobs._jobs[old.id] = job
    job.phase = "running"
    assert await _say("/goal start confirm") == runtime_messages.render("goal_exists", "en")


async def test_after_a_takeover_the_earlier_goal_not_started_starts_by_its_id(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    (old,) = await _goals(execution_db)
    await _say(f"/goal {NEXT}")
    await _say(f"/goal start confirm {old.id}")
    assert [job.job_id for job in jobs] == [old.id]


async def test_after_a_takeover_the_earlier_goal_can_still_be_accepted(execution_db, active, model, jobs,
                                                                      monkeypatch, tmp_path):
    old = await _review_goal(execution_db, monkeypatch, tmp_path, model)
    line = await _say(f"/goal {NEXT}")
    assert line.startswith("Goal set"), line
    earlier, new = await _goals(execution_db)
    assert earlier.id == old.id and (earlier.phase, earlier.pause_reason) == ("waiting_user",
                                                                             "acceptance_review_required")
    async with repository() as repo:
        assert await repo.accept_review(earlier.id, earlier.version)
    earlier, new = await _goals(execution_db)
    assert earlier.phase == "succeeded" and new.pause_reason == "goal_not_started"


async def test_both_cards_are_sent_the_earlier_one_as_it_was(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    (old,) = await _goals(execution_db)
    await _set_state(old, pause_reason="goal_paused")
    await _say(f"/goal {NEXT}")
    new = (await _goals(execution_db))[1]
    for frames in ([], None):
        if frames is None:
            frames = await goal_command.open_frames(CID)        # a window that opens later
        else:
            await goal_command.publish(CID, frames.append)
        states = {frame["job_id"]: (frame["goal_state"]["status"], frame["goal_state"]["left"]) for frame in frames}
        assert states == {old.id: ("paused", True), new.id: ("not_started", False)}



async def test_after_a_takeover_a_note_reaches_the_earlier_goal_once_it_runs_again(execution_db, active, model, jobs,
                                                                                  monkeypatch):
    from types import SimpleNamespace
    from server.services import steering
    await _say(f"/goal {PROMPT}")
    (old,) = await _goals(execution_db)
    await _set_state(old, pause_reason="goal_paused")
    await _say(f"/goal {NEXT}")
    await _say(f"/goal resume {old.id}")
    running = SimpleNamespace(job_id=old.id)
    monkeypatch.setattr(background_jobs, "goal_job", lambda task_id: running if task_id == old.id else None)
    boxes = []
    monkeypatch.setattr(steering, "put", lambda key, steer: boxes.append(key) or True)
    assert await _say("/goal note credits are in credits/") == runtime_messages.render("goal_noted", "en")
    assert boxes == [old.id]

# -- a running goal, as before -------------------------------------------------------------------------------------

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


def test_the_reply_line_is_in_all_six_languages_with_every_part():
    for locale in ("en", "zh", "ja", "es", "de", "fr"):
        text = runtime_messages.render("goal_left", locale, objective="OBJ", status="STATE", round=7, back="BACK")
        assert all(part in text for part in ("OBJ", "STATE", "7", "BACK")), (locale, text)
