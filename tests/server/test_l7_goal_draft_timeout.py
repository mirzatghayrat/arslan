"""L7-5h (L7-7 bench r3, T2/T5/T9/T13): `/goal` drafted its checks under the 75 s per-call limit of a chat step.
DeepSeek's draft took 80-175 s, both attempts timed out, and the bare TimeoutError left the turn:
- task_service recorded it as `task_budget_exhausted` with the budget all but unused;
- the socket handler did not catch it, so the window got INTERNAL_ERROR and the socket closed with 1011.

Drafting now has the goal judge's limit and answers `goal_draft_failed` when it still times out. A timeout labels
the task `task_budget_exhausted` only when the task's own time has run out. The socket turns any timeout into
TASK_REVIEW_REQUIRED (a resumed task's turn too: it runs in the same `_turn`).
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import select

from arslan.execution_budget import current as current_budget, run_budget
from server.db.task_models import CompanionTask
from server.orchestrator import answer_salvage, arslan as arslan_turn, tool_loop
from server.services import personal_context as pc, runtime_messages, task_context, task_service, task_validation
from tests.server import test_cancel_record_race as _race, test_l7_goal_start as _start
from tests.server.test_cancel_record_race import _frames_until_end
from tests.server.test_l7_goal_start import CID, PROMPT, Model, _say

active, fresh, jobs = _start.active, _start.fresh, _start.jobs          # its fixtures, used here as they are
window_client = _race.window_client


async def _goal_rows(execution_db):
    async with execution_db() as db:
        rows = (await db.scalars(select(CompanionTask).where(CompanionTask.conversation_id == CID))).all()
    return [row for row in rows if row.privacy.get("driver") == {"kind": "background", "goal": True}]


async def test_drafting_has_the_goal_judges_time_not_a_chat_steps(execution_db, active, monkeypatch, jobs):
    limits = []
    real_within = answer_salvage.within

    async def within(awaitable, *, timeout):
        limits.append(timeout)
        return await real_within(awaitable, timeout=timeout)
    monkeypatch.setattr(answer_salvage, "within", within)
    model = Model()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    await _say(f"/goal {PROMPT}")
    assert len(model.requests) == 1 and model.requests[0]["system"].startswith("Draft the acceptance checks")
    assert limits == [task_validation._GOAL_JUDGE_TIMEOUT_S] and limits[0] > answer_salvage._CHAT_TIMEOUT_S
    assert len(await _goal_rows(execution_db)) == 1


class Stalls(Model):
    """Every drafting request runs out of time, as DeepSeek's did twice in a row."""

    async def chat(self, system, user, history=None, tools=None, **kw):
        self.requests.append({"system": system, "user": user, "tools": tools})
        raise TimeoutError


async def test_a_draft_that_times_out_twice_says_so_and_keeps_no_goal(execution_db, active, monkeypatch, jobs):
    model = Stalls()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    line = await _say(f"/goal {PROMPT}")
    assert line == runtime_messages.render("goal_draft_failed", "en")
    assert len(model.requests) == 2                                     # the one bounded retry, as before
    assert await _goal_rows(execution_db) == [] and jobs == []


async def _turn_row(execution_db) -> CompanionTask:
    async with execution_db() as db:
        (row,) = (await db.scalars(select(CompanionTask).where(CompanionTask.conversation_id == CID))).all()
    return row


@pytest.mark.parametrize("expired", [None, "clock", "spent"], ids=["time-left", "clock-fired", "time-spent"])
async def test_a_timeout_is_budget_exhausted_only_when_the_tasks_time_is_up(execution_db, active, expired):
    budget = run_budget()
    if expired == "clock":                                   # the task's own wall clock fires on the request
        budget.limits = replace(budget.limits, wall_seconds=0.2)

    async def turn(conversation_id, user_message, emit):
        if expired == "clock":
            await asyncio.sleep(5)
        if expired == "spent":                               # a request's own limit, met as the task's time ran out
            current_budget().started -= current_budget().limits.wall_seconds + 1
        raise TimeoutError
    with pc.bind(await task_context.load(CID, user_message="x")), pytest.raises(TimeoutError) as raised:
        await task_service.run_turn(turn, CID, "x", lambda event: None, _budget=budget)
    row = await _turn_row(execution_db)
    code = "task_budget_exhausted" if expired else "task_execution_failed"
    assert (row.pause_reason, row.phase) == (code, "waiting_user" if expired else "failed")
    assert raised.value.task_code == code                    # the socket sends what the task recorded


@pytest.mark.parametrize("code", [None, "task_budget_exhausted"])
def test_a_timeout_that_leaves_a_turn_is_a_review_frame_not_a_closed_socket(window_client, monkeypatch, code):
    async def times_out(*args, **kwargs):
        exc = TimeoutError()
        if code:
            exc.task_code = code
        raise exc
    monkeypatch.setattr(arslan_turn, "handle_user_message", times_out)
    expected = {"type": "error", "code": "TASK_REVIEW_REQUIRED", "message": code or "task_execution_failed",
                "recoverable": True}
    with window_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        for _ in range(2):                                   # the socket is still open for the next message
            window.send_json({"type": "user_message", "content": "Hi"})
            frames, waiting = _frames_until_end(window)
            assert not waiting and frames[-1] == expected, frames


def test_a_timeout_in_a_resumed_task_is_a_review_frame_too(window_client, monkeypatch):
    async def times_out(*args, **kwargs):
        exc = TimeoutError()
        exc.task_code = "task_execution_failed"
        raise exc
    monkeypatch.setattr(task_service, "resume_turn", times_out)
    with window_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        for _ in range(2):
            window.send_json({"type": "resume_task", "task_id": "t-1", "expected_version": 1})
            frames, waiting = _frames_until_end(window)
            assert not waiting and frames[-1] == {"type": "error", "code": "TASK_REVIEW_REQUIRED",
                                                  "message": "task_execution_failed", "recoverable": True}, frames
