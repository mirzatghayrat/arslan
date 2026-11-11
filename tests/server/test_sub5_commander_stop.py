"""SUB5 (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md): a real stop for a commander whose own turn has ended
while its sub-sessions work on. Server only.

- POST /runs/{id}/cancel of the commander's ended turn stops everything under it (it answered 409 before).
- POST /background-jobs/{id}/stop of a sub-session's job stops the sub-sessions under it too.
- The island's one entry for a commander's sub-sessions has a Stop that stops them all while the commander is idle.

No tool table offers `start_sub_session` yet, so these start sub-sessions with `sub_sessions.start` and run the rest
for real, in SUB4's harness: their jobs and the summary turn through the background job runner with a scripted model,
and the HTTP routes. Every wait here is short, and the SUB5a fixture stops whatever is still running when a test
ends, so a failing test fails quickly.
"""
import asyncio
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI

from server import auth
from server.api.background_jobs import router as background_jobs_router
from server.api.desktop import router as desktop_router
from server.api.runs import router as runs_router
from server.db.models import Run
from server.services import background_jobs, sub_sessions
from tests.server.test_s64_0_outside_content_gaps import memory  # noqa: F401  (the fixture)
from tests.server.test_sub4_report import (  # noqa: F401  (the fixture)
    COVER, OUTLINE, ROOT, _Model, _children, _sink, _start, _steps, _summaries, _wait, runs)
from tests.server.test_sub5a_lifecycle import (  # noqa: F401  (the autouse fixture)
    THIRD, _by_goal, _fresh, _said, _states, _stop_line)

WAIT_S = 3.0


@pytest.fixture
async def api(runs, monkeypatch):  # noqa: F811
    monkeypatch.setattr(auth, "active_token", lambda: "sub5-token")
    app = FastAPI()
    for router in (runs_router, background_jobs_router, desktop_router):
        app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 headers={"Authorization": "Bearer sub5-token"}) as c:
        yield c


def _model(*held: str) -> _Model:
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(final="cover ready"),
                    THIRD: _steps(final="voice-over ready")}, summary=_steps(final="summed up"))
    for side in held:
        model.hold[side] = asyncio.Event()
    return model


async def _ended_turn(db, cid) -> int:
    """The commander's turn that started them, ended: its run row only, nothing registered."""
    async with db() as session:
        run = Run(conversation_id=cid, user_message="go", status="recorded", ended_at=datetime.utcnow())
        session.add(run)
        await session.commit()
    return run.id


def _asked(model) -> dict:
    return {side: len(requests) for side, requests in model.requests.items()}


async def _quiet(model, asked: dict) -> None:
    """Twenty polls later: nothing is at work, no summary is due, and the model was asked nothing more."""
    await asyncio.sleep(0.2)
    assert not background_jobs.unreported() and sub_sessions._summaries == {} and sub_sessions._reports == {}
    assert _asked(model) == asked


async def test_the_windows_stop_of_the_commanders_ended_turn_stops_its_sub_sessions_and_writes_the_line(
        runs, api, monkeypatch):  # noqa: F811
    """The voice-over has finished and its report waits for the outline, which works on; the turn that started them
    has ended. The window's stop of that turn stops the outline and the cover under it, drops the report with one
    line, and no summary turn follows. A second stop finds nothing at work: 409, as before."""
    _sink(ROOT)
    model = _model(OUTLINE, COVER)
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, THIRD)
    kid, done = _by_goal()[OUTLINE], _by_goal()[THIRD]
    await _wait(lambda: done.task.done() and sub_sessions._reports.get(ROOT), WAIT_S)
    grandchild = await sub_sessions.start(kid.conversation_id, COVER, outside_seen=False)
    await _wait(lambda: model.requests[OUTLINE] and model.requests[COVER], WAIT_S)
    run_id = await _ended_turn(runs, ROOT)
    assert (await api.post(f"/api/v1/runs/{run_id}/cancel")).status_code == 202
    stopped = [job for job in background_jobs._jobs.values() if job.conversation_id in (kid.conversation_id,
                                                                                         grandchild)]
    await _wait(lambda: all(job.task.done() for job in stopped), WAIT_S)
    assert [job.outcome for job in stopped] == ["stopped", "stopped"]
    await _quiet(model, _asked(model))
    assert _summaries() == [] and model.requests["summary"] == []
    assert await _said(runs, ROOT) == [(_stop_line(1), None)]
    assert await _states(runs, [kid.conversation_id, done.conversation_id, grandchild]) == {
        kid.conversation_id: None, done.conversation_id: None, grandchild: None}
    again = await api.post(f"/api/v1/runs/{run_id}/cancel")
    assert again.status_code == 409


async def test_an_ended_turn_with_nothing_under_it_at_work_still_answers_409(runs, api):  # noqa: F811
    run_id = await _ended_turn(runs, ROOT)
    response = await api.post(f"/api/v1/runs/{run_id}/cancel")
    assert response.status_code == 409 and "not cancellable" in response.json()["detail"]
    assert (await api.post("/api/v1/runs/999999/cancel")).status_code == 404
    assert await _said(runs, ROOT) == []


async def test_the_stop_of_an_ended_turn_also_stops_its_running_summary_turn(runs, api, monkeypatch):  # noqa: F811
    """Both reports are being summed up when the stop comes: the summary turn stops, the line counts both, and no
    second summary turn follows."""
    _sink(ROOT)
    model = _model("summary")
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, THIRD)
    await _wait(lambda: model.requests["summary"], WAIT_S)
    [summary] = _summaries()
    ids = [job.conversation_id for job in _children()]
    run_id = await _ended_turn(runs, ROOT)
    assert (await api.post(f"/api/v1/runs/{run_id}/cancel")).status_code == 202
    await _wait(lambda: summary.task.done(), WAIT_S)
    assert summary.outcome == "stopped"
    await _quiet(model, _asked(model))
    assert _summaries() == [summary] and len(model.requests["summary"]) == 1
    assert (_stop_line(2), None) in await _said(runs, ROOT)
    assert await _states(runs, ids) == dict.fromkeys(ids)


async def test_stopping_a_sub_sessions_job_stops_the_sub_sessions_under_it(runs, api, monkeypatch):  # noqa: F811
    """The outline's job is stopped where any job is (POST /background-jobs/{id}/stop): the cover under it stops too
    and reports nothing to it; the voice-over beside it works on. The outline's own stop still reports to the
    commander, as before."""
    _sink(ROOT)
    model = _model(OUTLINE, COVER, THIRD)
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, THIRD)
    kid, beside = _by_goal()[OUTLINE], _by_goal()[THIRD]
    grandchild = await sub_sessions.start(kid.conversation_id, COVER, outside_seen=False)
    [cover] = [job for job in background_jobs._jobs.values() if job.conversation_id == grandchild]
    await _wait(lambda: all(model.requests[side] for side in (OUTLINE, COVER, THIRD)), WAIT_S)
    assert (await api.post(f"/api/v1/background-jobs/{kid.job_id}/stop")).status_code == 200
    await _wait(lambda: kid.task.done() and cover.task.done(), WAIT_S)
    assert (kid.outcome, cover.outcome, beside.phase) == ("stopped", "stopped", "running")
    await asyncio.sleep(0.2)                                    # twenty polls
    assert kid.conversation_id not in sub_sessions._reports and kid.conversation_id not in sub_sessions._summaries
    assert [r["outcome"] for r in sub_sessions._reports[ROOT]] == ["stopped"]
    assert await _states(runs, [kid.conversation_id, grandchild, beside.conversation_id]) == {
        kid.conversation_id: sub_sessions.WORKING, grandchild: None, beside.conversation_id: sub_sessions.WORKING}
    assert len(model.requests[COVER]) == 1


async def test_stopping_a_conversations_own_job_leaves_its_sub_sessions_working(runs, api, monkeypatch):  # noqa: F811
    _sink(ROOT)
    model = _model(OUTLINE, "summary")
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE)
    [kid] = _children()
    own = await background_jobs.start(ROOT, "Tidy the notes", [], outside_seen=False)
    await _wait(lambda: model.requests[OUTLINE] and model.requests["summary"], WAIT_S)
    assert (await api.post(f"/api/v1/background-jobs/{own.job_id}/stop")).status_code == 200
    await _wait(lambda: own.task.done(), WAIT_S)
    await asyncio.sleep(0.1)
    assert (own.outcome, kid.phase) == ("stopped", "running")


async def test_an_idle_commanders_island_entry_stops_its_sub_sessions(runs, api, monkeypatch):  # noqa: F811
    """The commander is idle; the outline and the cover under it work. The island shows one entry for the commander,
    and its Stop (the island posts the entry's `job_id` to POST /background-jobs/{id}/stop) stops both: no report,
    no summary turn, and nothing runs again."""
    _sink(ROOT)
    model = _model(OUTLINE, COVER)
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE)
    [kid] = _children()
    grandchild = await sub_sessions.start(kid.conversation_id, COVER, outside_seen=False)
    [cover] = [job for job in background_jobs._jobs.values() if job.conversation_id == grandchild]
    await _wait(lambda: model.requests[OUTLINE] and model.requests[COVER], WAIT_S)
    feed = (await api.get("/api/v1/island/feed")).json()
    [entry] = feed["active"]
    assert entry["conversation_id"] == ROOT and entry["job_id"]
    assert (await api.post(f"/api/v1/background-jobs/{entry['job_id']}/stop")).status_code == 200
    await _wait(lambda: kid.task.done() and cover.task.done(), WAIT_S)
    assert (kid.outcome, cover.outcome) == ("stopped", "stopped")
    await _quiet(model, _asked(model))
    assert _summaries() == [] and model.requests["summary"] == [] and await _said(runs, ROOT) == []
    assert await _states(runs, [kid.conversation_id, grandchild]) == {kid.conversation_id: None, grandchild: None}
    assert (await api.get("/api/v1/island/feed")).json()["active"] == []
    again = await api.post(f"/api/v1/background-jobs/{entry['job_id']}/stop")
    assert again.status_code == 409 and again.json()["detail"] == {"code": "job_not_running"}
