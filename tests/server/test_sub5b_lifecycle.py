"""SUB5b with SUB5a (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md, SUB5): what a restart and a delete do to a job
an Inbox follow-up starts in a sub-session.

SUB5a's harness: real jobs through the background job runner with a scripted model, the HTTP routes (the Inbox's
accept, the conversation delete) and main.py's boot passes on a copy of the database taken in flight.

1. A follow-up started in a sub-session owes its parent a report again (`sub_state` working, as `sub_sessions.start`
   writes it), so a restart while it runs gives the commander its one line.
2. A deleted tree's open Inbox reminders stay where they are, and accepting one is refused (`conversation_deleted`),
   also after a restart: every row of the tree is a tombstone.
"""
import asyncio
from datetime import datetime

import pytest

from server.db.models import ProactiveItem
from server.services import background_jobs, proactive_service, sub_sessions
from tests.server.test_s64_0_outside_content_gaps import memory  # noqa: F401  (the fixture)
from tests.server.test_sub4_report import (  # noqa: F401  (the fixture)
    OUTLINE, ROOT, _children, _Model, _settled, _sink, _start, _steps, _wait, runs)
from tests.server.test_sub5a_lifecycle import (  # noqa: F401  (the fixtures)
    _family, _fresh, _line, _nothing_runs_again, _said, _states, client, restart)

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
