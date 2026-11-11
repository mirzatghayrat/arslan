"""SUB5b with SUB5a (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md, SUB5): what a restart and a delete do to a job
an Inbox follow-up starts in a sub-session.

SUB5a's harness: real jobs through the background job runner with a scripted model, the HTTP routes (the Inbox's
accept, the conversation delete) and main.py's boot passes on a copy of the database taken in flight.

1. A follow-up started in a sub-session owes its parent a report again (`sub_state` working, as `sub_sessions.start`
   writes it), so a restart while it runs gives the commander its one line.
2. A deleted tree's open Inbox reminders stay where they are, and accepting one is refused (`conversation_deleted`),
   also after a restart: every row of the tree is a tombstone.
3. A stop that lands while a sub-session's placement is read (`sub_sessions.placement`, a database read) is still
   honoured: SUB5a's second stop check comes after that read, with no await between it and the job's start.
"""
import asyncio
from datetime import datetime

import pytest

from server.db.models import ProactiveItem
from server.services import background_jobs, execution_context, proactive_service, run_registry, sub_sessions
from tests.server.test_s64_0_outside_content_gaps import memory  # noqa: F401  (the fixture)
from tests.server.test_sub4_report import (  # noqa: F401  (the fixture)
    COVER, OUTLINE, ROOT, _children, _Model, _settled, _sink, _start, _steps, _wait, runs)
from tests.server.test_sub5a_lifecycle import (  # noqa: F401  (the fixtures)
    _family, _fresh, _line, _live_turn, _nothing_runs_again, _refused, _said, _states, client, restart)

GOAL = "Continue the outline the sub-session left unfinished"


@pytest.fixture(autouse=True)
def _model_configured(monkeypatch):
    async def configured():
        return True
    monkeypatch.setattr(proactive_service, "model_configured", configured)


async def _reminder(db, cid) -> int:
    """An open `job_followup` for `cid`, as the detector leaves one."""
    async with db() as session:
        item = ProactiveItem(kind="job_followup", fingerprint=f"job:{cid}", source_key=f"job:{cid}",
                             title_key="title.job_followup", evidence=[{"key": "job.goal"}], goal=GOAL, status="new",
                             conversation_id=cid, created_at=datetime.utcnow())
        session.add(item)
        await session.commit()
        return item.id


async def test_a_restart_during_a_follow_up_in_a_sub_session_gives_the_commander_its_line(
        runs, client, restart, monkeypatch):  # noqa: F811
    """The sub-session's first job was summed up, so it owed nothing. The Inbox's follow-up there owes its parent a
    report again: a restart while it runs records it interrupted, and the commander gets one line. Nothing reruns."""
    _sink(ROOT)
    model = _Model({GOAL: _steps(final="continued"), OUTLINE: _steps(final="outline ready")},
                   summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE)
    [first] = _children()
    kid = first.conversation_id
    await _wait(_settled)
    await _wait(lambda: not sub_sessions._summing)
    assert await _states(runs, [kid]) == {kid: None}
    model.hold[GOAL] = asyncio.Event()
    got = await client.post(f"/api/v1/proactive/items/{await _reminder(runs, kid)}/accept", json={})
    assert got.status_code == 200, got.text
    assert background_jobs._jobs[got.json()["job_id"]].parent_id == ROOT
    await _wait(lambda: model.requests[GOAL])
    assert await _states(runs, [kid]) == {kid: sub_sessions.WORKING}
    db = await restart()
    assert await _states(db, [kid]) == {kid: sub_sessions.INTERRUPTED}
    assert await _said(db, ROOT) == [("summed up", "done"), (_line(1), None)]
    await _nothing_runs_again(model)


@pytest.mark.parametrize("restarted", [False, True], ids=["same-process", "after-a-restart"])
async def test_a_deleted_trees_open_reminders_are_refused_at_accept_and_left_in_the_inbox(
        runs, client, restarted):  # noqa: F811
    child, grandchild = await _family(runs)
    items = {cid: await _reminder(runs, cid) for cid in (child, grandchild)}
    assert (await client.delete(f"/api/v1/conversations/{ROOT}?sub_sessions=delete")).status_code == 200
    if restarted:
        sub_sessions._deleted.clear()                    # what a restart forgets; the tombstones hold
    for item_id in items.values():
        got = await client.post(f"/api/v1/proactive/items/{item_id}/accept", json={})
        assert got.status_code == 422 and got.json()["detail"] == {"code": "conversation_deleted"}
    async with runs() as db:
        assert {(await db.get(ProactiveItem, item_id)).status for item_id in items.values()} == {"new"}
    assert background_jobs._jobs == {}


async def test_a_stop_while_a_new_sub_sessions_placement_is_read_refuses_it(runs, client, monkeypatch):  # noqa: F811
    """SUB5a's case (`test_a_sub_session_the_stopped_turn_starts_afterwards_never_runs`) with the pause in
    `placement`'s read: the stop lands there, and the start goes on past it. It is refused, no job is made, the model
    is never asked for its brief, and its row doesn't end `working`. Another turn's still starts, reading its placement
    once (SUB5c, #805's mutant N2: a second read, through `background_jobs.start` after the check, is an await the
    check no longer covers). A start this lets through by mistake is stopped and awaited before the test ends, so a
    regression fails here instead of leaving a job running past the test (#805's hang)."""
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(final="cover ready")},
                   summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    run_id, turn = await _live_turn(runs, ROOT)
    entered, gate = asyncio.Event(), asyncio.Event()
    real = sub_sessions.placement
    reads: dict[str, int] = {}

    async def slow(cid):
        reads[cid] = reads.get(cid, 0) + 1
        if cid.startswith(sub_sessions.CHILD_PREFIX) and not gate.is_set():
            entered.set()
            await gate.wait()
        return await real(cid)
    monkeypatch.setattr(sub_sessions, "placement", slow)
    with execution_context.bind_run(run_id):
        starting = asyncio.ensure_future(sub_sessions.start(ROOT, OUTLINE, outside_seen=False))
    try:
        await entered.wait()
        assert (await client.post(f"/api/v1/runs/{run_id}/cancel")).status_code == 202
        gate.set()
        assert await _refused(starting) == "sub_session_stopped"
        assert background_jobs._jobs == {}
        async with runs() as db:
            [child] = await sub_sessions.children(db, ROOT)
        assert await _states(runs, [child]) == {child: None}
        with execution_context.bind_run(run_id + 1):
            other = await sub_sessions.start(ROOT, COVER, outside_seen=False)
        assert [job.goal for job in _children()] == [COVER] and reads[other] == 1
        run_registry.unregister(run_id, ROOT)
        await _wait(_settled)
        assert model.requests[OUTLINE] == [] and await _states(runs, [child]) == {child: None}
    finally:
        run_registry.unregister(run_id, ROOT)
        turn.cancel()
        if not starting.done():
            starting.cancel()
        jobs = [job.task for job in background_jobs._jobs.values() if job.task is not None and not job.task.done()]
        for task in (*jobs, *sub_sessions._summaries.values()):
            task.cancel()
        await asyncio.wait({starting, turn, *jobs, *sub_sessions._summaries.values()}, timeout=10)
