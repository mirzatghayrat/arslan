"""L7-6: the goal card's `goal_state` key on `job_update`, the frames of a goal with no job running, and the card's
chat lines `/goal pause`, `/goal edit` and `/goal from` (docs/plans/0164/L7-goal-mode.md, UI, "The frame").

Offline: a scripted adapter stands in for the model; the blocked goal's rounds run through the real `run_native`.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from server.services import background_jobs, goal_command, goal_mode
from server.services.goal_mode import GoalBlocker, GoalCheck, GoalProgress, GoalSpec

from tests.server import test_l7_goal_resume as resume
from tests.server import test_l7_goal_start as start
from tests.server.test_l7_goal_start import CID, PROMPT, _row, _say

active, fresh, model, jobs = start.active, start.fresh, start.model, start.jobs
disk, turns = resume.disk, resume.turns

JOB_KEYS = {"type", "job_id", "conversation_id", "goal", "phase", "step", "outcome", "detail", "budget", "run_id",
            "origin", "criteria"}


def _vector(name: str) -> dict:
    """The card's pinned vectors, read from the card itself, so the card and the code can't drift apart."""
    from pathlib import Path
    card = (Path(__file__).parents[2] / "docs/plans/0164/L7-goal-mode.md").read_text()
    line = next(line for line in card.splitlines() if line.strip().startswith(f"- {name}: `{{"))
    return json.loads(line.split("`", 2)[1])


# -- the frame -----------------------------------------------------------------------------------------------------

def test_a_job_that_is_not_a_goal_has_no_goal_state_and_its_frame_is_unchanged():
    job = background_jobs.Job(job_id="job-1", conversation_id=CID, goal="Tidy my notes",
                              acceptance=background_jobs.criteria_to_acceptance([{"description": "x", "kind": "judgement"}]))
    frame = job.frame()
    assert set(frame) == JOB_KEYS and "goal_state" not in frame
    assert json.dumps(frame, sort_keys=True) == json.dumps(job._frame(), sort_keys=True)


def _spec() -> GoalSpec:
    return GoalSpec(objective="Reconcile", usd_cap=2.0, checks=(
        GoalCheck(id="c1", description="Summary sheet saved", kind="file_saved", path="october-summary.xlsx"),
        GoalCheck(id="check-1", description="check: python3 check_totals.py", kind="check",
                  argv=("python3", "check_totals.py"), by_user=True)))


ITEMS = {"c1": {"check_id": "c1", "status": "passed", "code": "file_saved_assertion", "path": "october-summary.xlsx"},
         "check-1": {"check_id": "check-1", "status": "failed", "code": "code_test_assertion", "exit_code": 1,
                     "measure": {"digest": "0" * 64, "size": None}}}


def test_the_not_started_vector_round_trips():
    spec = GoalSpec(objective="Reconcile", usd_cap=2.0, checks=(
        GoalCheck(id="c1", description="Summary sheet saved", kind="file_saved", path="october-summary.xlsx"),
        GoalCheck(id="c2", description="Looks tidy", kind="judgement")))
    state = goal_mode.goal_state(spec, None, status="not_started", items={}, finished=False, spend_usd=None,
                                 cap_usd=2.0)
    assert json.loads(json.dumps(state)) == state == _vector("not started")


def test_the_active_and_blocked_vectors_round_trip():
    record = GoalProgress(status="active", round=3)
    state = goal_mode.goal_state(_spec(), record, status="active", items=ITEMS, finished=False, spend_usd=0.41,
                                 cap_usd=2.0)
    assert json.loads(json.dumps(state)) == state == _vector("active, round 3")
    step = "Type the amount of INV-1052 in a note."
    blocked = goal_mode.goal_state(_spec(), record.model_copy(update={
        "status": "blocked", "round": 6, "blocker": GoalBlocker(code="no_progress"), "step": step}),
        status="blocked", items=ITEMS, finished=True, spend_usd=0.41, cap_usd=2.0)
    assert blocked == {**_vector("active, round 3"), "status": "blocked", "round": 6,
                       "blocker": {"code": "no_progress", "files": []}, "step": step}


def test_a_check_with_no_receipt_is_pending_while_running_and_not_reached_once_stopped():
    running = goal_mode.goal_state(_spec(), None, status="active", items={}, finished=False, spend_usd=None,
                                   cap_usd=None)
    stopped = goal_mode.goal_state(_spec(), None, status="interrupted", items={}, finished=True, spend_usd=None,
                                   cap_usd=None)
    assert {c["status"] for c in running["checks"]} == {"pending"}
    assert {c["status"] for c in stopped["checks"]} == {"not_reached"}
    assert running["met"] == 0 and running["total"] == 2


# -- a goal with no job running ------------------------------------------------------------------------------------

async def test_no_goal_row_means_no_frame(execution_db, active, model):
    assert await goal_command.open_frames(CID) == []


async def test_a_goal_set_but_not_started_is_a_queued_job_update_with_its_flags(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    (frame,) = await goal_command.open_frames(CID)
    row = await _row(execution_db)
    assert frame["job_id"] == row.id and frame["phase"] == "queued" and frame["goal"] == PROMPT
    state = frame["goal_state"]
    assert state["status"] == "not_started" and state["round"] == 0 and state["spend_usd"] is None
    assert [c["id"] for c in state["checks"] if c["flagged"]] == ["c3", "c4", "c5"]
    assert [c["id"] for c in frame["criteria"]] == [c["id"] for c in state["checks"]]
    await _say("/goal start confirm")
    assert await goal_command.open_frames(CID) == []        # the job's own frame says it now


async def test_a_blocked_goal_frame_carries_its_round_blocker_step_and_receipts(execution_db, active, model, disk,
                                                                                turns):
    row = await resume._blocked(execution_db, model)
    job = background_jobs._jobs[row.id]
    live = job.frame()["goal_state"]
    assert (live["status"], live["round"], live["blocker"]) == ("blocked", 3, {"code": "no_progress", "files": []})
    assert live["step"] and live["checks"][0]["receipt"]["code"] == "file_contains_assertion"
    (frame,) = await goal_command.open_frames(CID)          # as after a restart: from the row and its checkpoint
    assert (frame["phase"], frame["outcome"], frame["detail"]) == ("finished", "blocked", "goal_blocked")
    assert {k: frame["goal_state"][k] for k in ("status", "round", "blocker", "step")} == {
        k: live[k] for k in ("status", "round", "blocker", "step")}
    assert frame["goal_state"]["checks"][0]["status"] == "failed"


# -- the card's chat lines -----------------------------------------------------------------------------------------

async def test_pause_stops_the_running_goal_and_it_waits_as_paused_for_resume(execution_db, active, model, disk,
                                                                              monkeypatch):
    model.draft = resume.NOTES
    gate = asyncio.Event()
    answer = model.chat

    async def slow(system, user, **kw):
        if not system.startswith("Draft the acceptance checks"):
            await gate.wait()
        return await answer(system, user, **kw)
    monkeypatch.setattr(model, "chat", slow)
    await _say(f"/goal {PROMPT}")
    await _say("/goal start")
    for _ in range(50):
        await asyncio.sleep(0.02)
    assert background_jobs.goal_job((await _row(execution_db)).id) is not None
    assert await _say("/goal pause") == "Goal paused. Send /goal resume to go on."
    row = await _row(execution_db)
    assert (row.phase, row.pause_reason, row.cancel_requested) == ("waiting_user", "goal_paused", False)
    assert background_jobs._jobs[row.id].frame()["goal_state"]["status"] == "paused"
    (frame,) = await goal_command.open_frames(CID)
    assert frame["goal_state"]["status"] == "paused" and frame["outcome"] == "stopped"
    gate.set()
    assert (await _say("/goal resume")).startswith("Goal resumed")
    await resume._finish(row.id)


async def test_stop_is_not_pause_a_stopped_goal_is_cleared(execution_db, active, model, disk, monkeypatch):
    model.draft = resume.NOTES
    gate = asyncio.Event()
    answer = model.chat

    async def slow(system, user, **kw):
        if not system.startswith("Draft the acceptance checks"):
            await gate.wait()
        return await answer(system, user, **kw)
    monkeypatch.setattr(model, "chat", slow)
    await _say(f"/goal {PROMPT}")
    await _say("/goal start")
    row = await _row(execution_db)
    for _ in range(50):
        await asyncio.sleep(0.02)
    assert background_jobs.stop(CID, row.id)
    await asyncio.wait_for(background_jobs._jobs[row.id].task, 15)
    assert (await _row(execution_db)).phase == "cancelled"
    assert background_jobs._jobs[row.id].frame()["goal_state"]["status"] == "cleared"


async def test_pause_with_no_running_goal_says_so(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    assert "No goal is running" in await _say("/goal pause")
    assert (await _row(execution_db)).pause_reason == "goal_not_started"


EDIT = "/goal edit\nobjective: Reconcile the invoices\nc1: notes.md names INV-07 and INV-08\nc4 (mine): it looks nice\n" \
       "new: the totals add up\ncheck: python3 tests/run_checks.py"


async def test_edit_keeps_each_kept_checks_condition_and_waits_for_start(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    before = await _row(execution_db)
    line = await _say(EDIT)
    assert line.startswith("Goal edited, not started") and jobs == []
    row = await _row(execution_db)
    assert (row.phase, row.pause_reason, row.spec_revision) == ("waiting_user", "goal_not_started",
                                                                 before.spec_revision + 1)
    spec = GoalSpec.model_validate(row.privacy["goal_spec"])
    by_id = {check.id: check for check in spec.checks}
    assert list(by_id) == ["c1", "c4", "c2", "check-1"]           # c2, c3 and c5 removed; the added one is c2 now
    assert (by_id["c1"].kind, by_id["c1"].path, by_id["c1"].description) == (
        "file_contains", "notes.md", "notes.md names INV-07 and INV-08")
    assert by_id["c4"].user_confirmed and by_id["c2"].kind == "judgement" and not by_id["c2"].user_confirmed
    assert goal_mode.unverifiable(spec) == ("c2",)                 # an added check is flagged until it is yours
    assert spec.objective == "Reconcile the invoices\ncheck: python3 tests/run_checks.py"
    assert len(model.requests) == 1                                # an edit drafts nothing


async def test_edit_start_applies_the_edit_and_starts(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    line = await _say("/goal edit start\nobjective: Reconcile\nc1: notes.md names INV-07")
    assert line.startswith("Goal started") and len(jobs) == 1
    assert [check.id for check in jobs[0].goal_spec.checks] == ["c1"]


async def test_an_edit_line_it_cant_use_changes_nothing(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    before = await _row(execution_db)
    assert "can't be used" in await _say("/goal edit\nobjective: x\nzz: not a check of this goal")
    assert (await _row(execution_db)).spec_revision == before.spec_revision


async def test_keep_going_until_met_sets_a_not_started_goal_from_the_jobs_checks(execution_db, active, model, jobs):
    job = background_jobs.Job(job_id="job-done", conversation_id=CID, goal="Tidy the notes", phase="finished",
                              outcome="partial", acceptance=background_jobs.criteria_to_acceptance([
                                  {"description": "notes saved", "kind": "file_saved", "target": "notes.md"},
                                  {"description": "reads well", "kind": "judgement"}]))
    background_jobs._jobs[job.job_id] = job
    line = await _say("/goal from job-done")
    assert line.startswith("Goal set, not started") and jobs == [] and model.requests == []   # no drafting
    spec = GoalSpec.model_validate((await _row(execution_db)).privacy["goal_spec"])
    assert spec.objective == "Tidy the notes"
    assert [(c.kind, c.path) for c in spec.checks] == [("file_saved", "notes.md"), ("judgement", None)]
    assert goal_mode.unverifiable(spec) == ("c2",)


@pytest.mark.parametrize("change", [{"phase": "running"}, {"conversation_id": "other"}, {"parent_id": "p"}])
async def test_keep_going_needs_a_finished_plain_job_of_this_conversation(execution_db, active, model, jobs, change):
    job = background_jobs.Job(job_id="job-x", conversation_id=CID, goal="Tidy", phase="finished",
                              acceptance=background_jobs.criteria_to_acceptance([]))
    for key, value in change.items():
        setattr(job, key, value)
    background_jobs._jobs[job.job_id] = job
    assert "can't be continued as a goal" in await _say("/goal from job-x")


# -- round 1 review ------------------------------------------------------------------------------------------------

async def test_after_an_edit_a_flagged_check_not_marked_yours_still_blocks_start(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    line = await _say("/goal edit start\nobjective: Reconcile\nc1: notes.md names INV-07\nnew: it reads well")
    assert line.startswith("Not started") and "it reads well" in line and jobs == []
    row = await _row(execution_db)
    assert row.pause_reason == "goal_not_started"
    assert not any(check.user_confirmed for check in GoalSpec.model_validate(row.privacy["goal_spec"]).checks)


async def test_editing_a_running_goal_pauses_it_then_applies_the_edit(execution_db, active, model, disk, monkeypatch):
    model.draft = resume.NOTES
    gate = asyncio.Event()
    answer = model.chat

    async def slow(system, user, **kw):
        if not system.startswith("Draft the acceptance checks"):
            await gate.wait()
        return await answer(system, user, **kw)
    monkeypatch.setattr(model, "chat", slow)
    await _say(f"/goal {PROMPT}")
    await _say("/goal start")
    row = await _row(execution_db)
    for _ in range(50):
        await asyncio.sleep(0.02)
    assert background_jobs.goal_job(row.id) is not None
    line = await _say("/goal edit\nobjective: Reconcile only October\nc1: notes.md names INV-07")
    assert line.startswith("Goal edited, not started") and background_jobs.goal_job(row.id) is None
    after = await _row(execution_db)
    assert (after.phase, after.pause_reason, after.spec_revision) == ("waiting_user", "goal_not_started",
                                                                       row.spec_revision + 1)
    assert GoalSpec.model_validate(after.privacy["goal_spec"]).objective == "Reconcile only October"
    gate.set()


async def test_keep_going_never_trusts_a_check_line_in_the_jobs_own_goal(execution_db, active, model, jobs):
    """A model-started job's goal is the model's words: a `check:` line in it is never the user's command."""
    job = background_jobs.Job(job_id="job-m", conversation_id=CID, goal="check: python3 evil.py", phase="finished",
                              outcome="partial", acceptance=background_jobs.criteria_to_acceptance([
                                  {"description": "notes saved", "kind": "file_saved", "target": "notes.md"}]))
    background_jobs._jobs[job.job_id] = job
    assert (await _say("/goal from job-m")).startswith("Goal set, not started")
    spec = GoalSpec.model_validate((await _row(execution_db)).privacy["goal_spec"])
    assert not any(check.kind == "check" for check in spec.checks)
    assert [check.id for check in spec.checks] == ["c1"]


async def test_after_an_edit_and_start_the_card_shows_no_old_round_blocker_or_step(execution_db, active, model, disk,
                                                                                   turns):
    row = await resume._blocked(execution_db, model)
    await _say("/goal edit\nobjective: Reconcile\nc1: notes.md names INV-07")
    record, items, _ = await goal_command.saved(row.id)
    assert record is None and items == {}
    (frame,) = await goal_command.open_frames(CID)
    assert (frame["goal_state"]["round"], frame["goal_state"]["blocker"], frame["goal_state"]["step"]) == (0, None, None)


def test_the_phone_status_drops_goal_state_so_its_free_text_cant_break_the_snapshot():
    from server.api.phone import _clean_job
    lone = chr(0xD800)
    # The contracts refuse a lone surrogate; free text reaching the frame some other way must still not break it.
    check = GoalCheck.model_construct(id="c1", description=f"One{lone} row", kind="judgement", path=None, phrases=(),
                                      minimum=None, argv=(), outputs=(), by_user=False, user_confirmed=False)
    spec = GoalSpec.model_construct(objective="Tidy", checks=(check,), protected=None, tier="standard", usd_cap=None)
    job = background_jobs.Job("j", CID, "Tidy", goal_mode.acceptance(spec), phase="running", goal_spec=spec)
    cleaned = _clean_job(job.frame())
    assert "goal_state" not in cleaned and cleaned["criteria"][0]["description"] == "One row"
    json.dumps(cleaned).encode("utf-8")
