"""L7-3: `/goal` in chat, criteria drafting, the flag for checks Arslan can't verify, the not-started state and Start,
goal jobs under their own steer key, and the status mapping (docs/plans/0164/L7-goal-mode.md, "How it's set: one
entry point", "Checks Arslan can't verify", Decisions Q0-Q3, Method).

Offline: a scripted adapter stands in for the model. With no goal set the turn is unchanged; the z3 guard tests
(test_tool_offer_table, test_gate_order, test_turn_*, test_command_gate_refusals) cover that, unchanged.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from arslan.models import LLMResponse
from server.db.models import CompanionTask
from server.orchestrator import tool_loop
from server.services import (background_jobs, goal_command, goal_mode, personal_context as pc, runtime_messages,
                             task_context, task_validation)
from server.services.goal_mode import STATUS_PHASE, GoalSpec

CID = "goal-chat"
PROMPT = "Reconcile the synthetic invoices into notes.md and make report.md read well"
CHECK = "check: python3 tests/run_checks.py outputs: tests/revealed/test_step_*.py"
DRAFT = {"criteria": [
    {"description": "notes.md names INV-07", "kind": "file_contains", "path": "notes.md", "phrases": ["INV-07"]},
    {"description": "report.md reads well", "kind": "judgement", "path": "report.md"},       # the user named it
    {"description": "the summary is clear", "kind": "judgement", "path": "summary.md"},     # drafting added it
    {"description": "it looks nice", "kind": "judgement"},
    {"description": "mentions the total", "kind": "file_contains", "phrases": ["TOTAL"]},   # no file
    {"description": "run the tests", "kind": "check", "argv": ["rm", "-rf", "/"]},            # never from drafting
]}


@pytest.fixture(autouse=True)
def fresh():
    background_jobs._reset_for_tests()
    yield
    background_jobs._reset_for_tests()


@pytest.fixture
def active(monkeypatch):
    async def load(cid, **kwargs):
        identity = str(uuid.uuid4())
        return pc.TaskMemoryContext(task_id=identity, run_id=f"turn-{identity}", conversation_id=cid,
                                    no_memory=True, no_learning=True, query=kwargs.get("user_message", ""))
    monkeypatch.setattr(task_context, "load", load)

    async def english():
        return "en"
    monkeypatch.setattr(runtime_messages, "selected_locale", english)


class Model:
    """Drafting answers `draft`; a goal job's turn answers `answer`. Every request is kept, with its tools."""

    def __init__(self, draft=DRAFT, answer="Reconciled."):
        self.draft, self.answer, self.requests = draft, answer, []

    async def chat(self, system, user, history=None, tools=None, **kw):
        self.requests.append({"system": system, "user": user, "tools": tools})
        if system.startswith("Draft the acceptance checks"):
            return LLMResponse(usage={}, content=json.dumps(self.draft))
        return LLMResponse(usage={}, content=self.answer)


@pytest.fixture
def model(monkeypatch):
    adapter = Model()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    return adapter


@pytest.fixture
def jobs(monkeypatch):
    """Start goal queues the job; here its run only records that it was queued."""
    queued = []

    async def run(job):
        queued.append(job)
    monkeypatch.setattr(background_jobs, "_run", run)
    return queued


async def _say(text: str) -> str:
    rest = goal_command.parse(text)
    assert rest is not None, text
    line = await goal_command.handle(CID, rest)
    await asyncio.sleep(0)              # a queued job's task gets its first step
    return line


async def _row(execution_db) -> CompanionTask:
    async with execution_db() as db:
        rows = (await db.scalars(select(CompanionTask).where(CompanionTask.conversation_id == CID))).all()
    (row,) = [row for row in rows if row.privacy.get("driver") == {"kind": "background", "goal": True}]
    return row


# -- the flag and drafting ----------------------------------------------------------------------------------------

def test_drafting_never_writes_a_check_line_and_flags_what_arslan_cant_verify():
    checks = goal_command.drafted_checks(json.dumps(DRAFT), PROMPT)
    by_id = {check.id: check for check in checks}
    assert [check.kind for check in checks] == ["file_contains", "judgement", "judgement", "judgement", "judgement"]
    assert not any(check.kind == "check" or check.outputs for check in checks)
    assert by_id["c2"].by_user and not by_id["c3"].by_user            # only a path the user's objective names
    spec = GoalSpec(objective=PROMPT, checks=checks)
    assert goal_mode.unverifiable(spec) == ("c3", "c4", "c5")


def test_the_users_check_lines_are_theirs_with_their_declared_outputs_and_a_folder_is_refused():
    (line,) = goal_command.user_checks(f"{PROMPT}\n{CHECK}")
    assert (line.kind, line.by_user, line.argv) == ("check", True, ("python3", "tests/run_checks.py"))
    assert line.outputs == ("tests/revealed/test_step_*.py",)
    with pytest.raises(ValueError):
        goal_command.user_checks(f"{PROMPT}\ncheck: python3 run.py outputs: tests/revealed/")


@pytest.mark.parametrize("status", sorted(STATUS_PHASE))
def test_each_goal_status_reads_back_from_its_row(status):
    phase, reason = STATUS_PHASE[status]
    assert goal_mode.status_of(phase, reason) == status


# -- not started until Start (Q0) ---------------------------------------------------------------------------------

async def test_setting_a_goal_drafts_once_with_no_tools_and_runs_nothing(execution_db, active, model, jobs):
    line = await _say(f"/goal {PROMPT}\n{CHECK}")
    assert len(model.requests) == 1 and model.requests[0]["tools"] is None
    assert jobs == [] and background_jobs.active() == []
    row = await _row(execution_db)
    assert (row.phase, row.pause_reason) == ("waiting_user", "goal_not_started")
    assert row.privacy["driver"] == {"kind": "background", "goal": True}
    spec = GoalSpec.model_validate(row.privacy["goal_spec"])
    assert [check.id for check in spec.checks if check.kind == "check"] == ["check-1"]
    assert "Nothing runs until" in line and "⚠ c4: it looks nice" in line
    assert "not_started" in await _say("/goal status")


async def test_start_with_a_flagged_check_lists_it_and_start_confirm_makes_it_the_users(execution_db, active, model,
                                                                                         jobs):
    await _say(f"/goal {PROMPT}")
    refused = await _say("/goal start")
    assert jobs == [] and "c3" in refused and "c4" in refused and "/goal start confirm" in refused
    row = await _row(execution_db)
    assert (row.phase, row.pause_reason) == ("waiting_user", "goal_not_started")
    started = await _say("/goal start confirm")
    assert started.startswith("Goal started") and len(jobs) == 1
    job = jobs[0]
    assert job.job_id == row.id and job.goal == PROMPT
    confirmed = {check.id for check in job.goal_spec.checks if check.user_confirmed}
    assert confirmed == {"c3", "c4", "c5"} and goal_mode.unverifiable(job.goal_spec) == ()
    assert {check["id"]: check["evaluator"] for check in job.acceptance}["c4"] == "human"   # never the model's
    row = await _row(execution_db)
    assert row.spec_revision == 2 and row.pause_reason == "goal_not_started"
    assert GoalSpec.model_validate(row.privacy["goal_spec"]) == job.goal_spec


async def test_a_goal_of_only_the_users_own_checks_is_refused_at_start(execution_db, active, model, jobs):
    model.draft = {"criteria": [{"description": "the user is happy", "kind": "judgement"}]}
    await _say("/goal Make the user happy")
    assert "nothing for Arslan" in await _say("/goal start confirm") and jobs == []


async def test_a_second_goal_waits_for_the_first_to_be_cleared(execution_db, active, model, jobs):
    await _say(f"/goal {PROMPT}")
    assert "already has a goal" in await _say("/goal Another thing")
    assert await _say("/goal clear") == "Goal cleared."
    assert (await _row(execution_db)).phase == "cancelled"
    assert "Goal set" in await _say("/goal Another thing")


async def test_a_note_reaches_only_a_running_goal(execution_db, active, model, jobs):
    assert "No goal is running" in await _say("/goal note the invoices are in inbox/")


# -- `/goal` only where the user typed it ------------------------------------------------------------------------

async def test_slash_goal_is_plain_text_in_a_scheduled_prompt_or_a_resumed_instruction(execution_db, monkeypatch):
    """`_handle_answer` (the scheduler's and `resume_turn`'s entry) never parses `/goal`, with the setting on."""
    from server.orchestrator import arslan
    from server.services import host_run, settings_service
    reached = []

    async def on(db):
        return True

    async def body(conversation_id, user_message, emit, **kwargs):
        reached.append(user_message)

    async def execute(conversation_id, user_message, emit, body, **kwargs):
        return await body(emit)
    monkeypatch.setattr(settings_service, "goal_mode", on)
    monkeypatch.setattr(arslan, "_handle_answer_body", body)
    monkeypatch.setattr(host_run, "execute", execute)
    await arslan._handle_answer(CID, "/goal start confirm", lambda event: None)
    assert reached == ["/goal start confirm"]


async def test_a_start_background_work_goal_string_is_a_plain_job(execution_db, active, jobs):
    job = background_jobs.start_placed(CID, "/goal Sort the invoices", [], (None, None), outside_seen=False)
    await asyncio.sleep(0)
    assert job.goal_spec is None and job.goal == "/goal Sort the invoices"


# -- a goal job end to end: Start runs the row it set, under its own steer key -------------------------------------

async def test_start_runs_the_goal_row_it_set_as_a_job_with_its_own_steer_key(execution_db, active, model,
                                                                              monkeypatch, tmp_path):
    (tmp_path / "notes.md").write_text("Reconciled INV-07")

    async def disk(started_at):
        return {"roots": [tmp_path.resolve()], "workspace": tmp_path.resolve(), "since": None}
    monkeypatch.setattr(task_validation, "_disk_context", disk)
    model.draft = {"criteria": [DRAFT["criteria"][0]]}
    seen = []
    native = tool_loop.run_native

    async def recorded(**kwargs):
        seen.append({key: kwargs.get(key) for key in ("goal", "steer_key", "steerable")})
        return await native(**kwargs)
    monkeypatch.setattr(tool_loop, "run_native", recorded)
    await _say(f"/goal {PROMPT}")
    row = await _row(execution_db)
    await _say("/goal start")
    job = background_jobs.goal_job(row.id)
    assert job is not None
    await asyncio.wait_for(job.task, 10)
    assert seen and seen[0]["steer_key"] == row.id and seen[0]["steerable"] is True
    assert seen[0]["goal"] == GoalSpec.model_validate(row.privacy["goal_spec"])
    row = await _row(execution_db)
    assert row.phase == "succeeded" and job.outcome == "done"
    assert "complete" in await _say("/goal status")


async def test_the_benchs_two_messages_set_then_start_the_goal_through_the_chat(execution_db, active, model, jobs,
                                                                                monkeypatch):
    """L7-0's driver: `/goal <prompt>` (its `check:` line the user's), then `/goal start confirm` without editing
    the drafted checks; from the phone (`chat.send`) as from the Mac. Each reply is one host line, no turn."""
    from server.orchestrator import arslan
    from server.services import settings_service

    async def on(db):
        return True

    async def no_turn(*args, **kwargs):
        raise AssertionError("a /goal command never reaches the turn")
    monkeypatch.setattr(settings_service, "goal_mode", on)
    monkeypatch.setattr(arslan, "_handle_answer", no_turn)
    monkeypatch.setattr(arslan, "_after_turn_later", lambda *a, **k: None)
    events = []
    await arslan.handle_user_message(CID, f"/goal {PROMPT}\n{CHECK}", events.append, source="phone")
    await arslan.handle_user_message(CID, "/goal start confirm", events.append, source="phone")
    await asyncio.sleep(0)
    ends = [event for event in events if event["type"] == "stream_end"]
    assert len(ends) == 2 and all(isinstance(event["message_id"], int) for event in ends)
    assert len(model.requests) == 1 and model.requests[0]["tools"] is None
    (job,) = jobs
    assert job.origin == "phone" and "check-1" in {check.id for check in job.goal_spec.checks}
    assert job.job_id == (await _row(execution_db)).id
