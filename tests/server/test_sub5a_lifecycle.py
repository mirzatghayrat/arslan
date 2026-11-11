"""SUB5a (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md, SUB5): what a restart, the window's stop, a delete and
an undo do to sub-sessions. Server only.

No tool table offers `start_sub_session` yet, so these tests start sub-sessions with `sub_sessions.start` and run the
rest for real: their jobs and the summary turn through the background job runner with a scripted model (SUB4's
harness), the HTTP routes, and the boot pass.

A restart is a copy of the database taken while the work is in flight (`VACUUM INTO`, what the next process finds),
the old process's work thrown away, and main.py's boot passes run on the copy.
"""
import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server import auth, config
from server.api.conversations import router as conversations_router
from server.api.runs import router as runs_router
from server.db import session as db_session
from server.db.companion_models import ConversationContext
from server.db.migrations import runner
from server.db.models import ArslanMessage, ConversationEvent, PermissionGrant, Run
from server.db.task_models import CompanionTask
from server.orchestrator import memory as memory_mod
from server.registry import executors
from server.services import (approvals, background_jobs, checkpoints, execution_context, run_reaper, run_registry,
                             runtime_messages, sub_sessions, task_context, task_service, turn_undo)
from tests.server.test_s64_0_outside_content_gaps import _Run, memory  # noqa: F401  (the fixture)
from tests.server.test_sub4_report import (  # noqa: F401  (the fixture)
    COMMAND, COVER, OUTLINE, PAGE, ROOT, _Model, _cards, _children, _settled, _sink, _start, _steps, _summaries,
    _wait, _yes, runs)

THIRD = "Write the voice-over"
OTHER, OTHER_BRIEF = "c-other-commander", "Sketch the other storyboard"


@pytest.fixture(autouse=True)
async def _fresh(monkeypatch, execution_db):    # torn down before the database is
    monkeypatch.setattr(sub_sessions, "POLL_SECONDS", 0.01)
    for module in (background_jobs, approvals, sub_sessions):
        module._reset_for_tests()
    yield
    # What is still held stops here and ends while the test's loop runs.
    monkeypatch.setattr(sub_sessions, "ended", lambda job, text: None)    # a job cancelled here reports nothing
    for _ in range(5):                  # a summary cancelled mid-start may have started its job: until none is left
        tasks = [job.task for job in background_jobs._jobs.values() if job.task and not job.task.done()]
        tasks += [task for task in sub_sessions._summaries.values() if not task.done()]
        if not tasks:
            break
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    for module in (background_jobs, sub_sessions, approvals):
        module._reset_for_tests()
    from tests.server import test_sub4_report
    while test_sub4_report._SINKS:
        run_registry.detach_sink(*test_sub4_report._SINKS.pop())


@pytest.fixture
async def client(runs, monkeypatch):  # noqa: F811
    from server.api.companion import router as companion_router
    from server.api.phone import router as phone_router
    from server.api.proactive import router as proactive_router
    from server.api.scheduled_tasks import router as scheduled_router
    monkeypatch.setattr(auth, "active_token", lambda: "sub5a-token")
    app = FastAPI()
    for router in (conversations_router, runs_router, phone_router, companion_router, proactive_router,
                   scheduled_router):
        app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 headers={"Authorization": "Bearer sub5a-token"}) as c:
        yield c


@pytest.fixture
async def restart(runs, monkeypatch, tmp_path):  # noqa: F811
    """`await restart()`: the process dies now. Returns the next process's database, after its boot passes."""
    engines = []

    async def go():
        snapshot = tmp_path / f"after-restart-{len(engines)}.db"
        async with runs.kw["bind"].connect() as conn:
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.exec_driver_sql(f"VACUUM INTO '{snapshot}'")
        # The old process's work is thrown away against the old database, which nothing reads again.
        real = sub_sessions.ended
        monkeypatch.setattr(sub_sessions, "ended", lambda job, text: None)
        pending = [job.task for job in background_jobs._jobs.values() if job.task] + list(sub_sessions._summaries.values())
        for module in (background_jobs, sub_sessions, approvals):
            module._reset_for_tests()
        await asyncio.gather(*pending, return_exceptions=True)
        monkeypatch.setattr(sub_sessions, "ended", real)
        engine = db_session.build_engine(f"sqlite+aiosqlite:///{snapshot}")
        engines.append(engine)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
        # The next process's boot, in main.py's order.
        await run_reaper.mark_interrupted_runs()
        await task_service.recover_interrupted()
        await background_jobs.report_interrupted()
        return maker
    yield go
    for engine in engines:
        await engine.dispose()


def _line(count: int) -> str:
    return runtime_messages.render("sub_sessions_interrupted", "en", count=count)


def _stop_line(count: int) -> str:
    return runtime_messages.render("sub_sessions_stopped_reports", "en", count=count)


def _loads(monkeypatch) -> list[tuple]:
    """Every context load from here on: (conversation, no_memory, no_learning, sub_session), or (conversation,
    "refused", code)."""
    seen = []
    real = task_context.load

    async def load(conversation_id, **kw):
        try:
            ctx = await real(conversation_id, **kw)
        except Exception as exc:
            seen.append((conversation_id, "refused", getattr(exc, "code", type(exc).__name__)))
            raise
        seen.append((conversation_id, ctx.no_memory, ctx.no_learning, ctx.sub_session))
        return ctx
    monkeypatch.setattr(task_context, "load", load)
    return seen


async def _states(db, ids) -> dict:
    async with db() as session:
        return dict((await session.execute(select(ConversationContext.id, ConversationContext.sub_state).where(
            ConversationContext.id.in_(list(ids))))).all())


async def _said(db, cid) -> list[tuple[str, str | None]]:
    """What Arslan wrote in a conversation: (the text as shown, its job outcome)."""
    async with db() as session:
        rows = (await session.scalars(select(ArslanMessage).where(
            ArslanMessage.conversation_id == cid, ArslanMessage.role == "arslan").order_by(ArslanMessage.id))).all()
    return [(row.display_content or row.content, row.job_outcome) for row in rows]


async def _tasks(db) -> dict:
    async with db() as session:
        return {row.conversation_id: (row.phase, row.pause_reason)
                for row in (await session.scalars(select(CompanionTask))).all()}


async def _nothing_runs_again(model):
    seen = {side: len(requests) for side, requests in model.requests.items()}
    await asyncio.sleep(0.3)                                    # thirty polls
    assert background_jobs._jobs == {} and sub_sessions._summaries == {} and sub_sessions._reports == {}
    assert {side: len(requests) for side, requests in model.requests.items()} == seen


def _by_goal() -> dict:
    return {job.goal: job for job in _children()}


# -- the restart matrix ---------------------------------------------------------------------------------------------

async def test_a_restart_interrupts_a_running_and_a_queued_sub_session_and_tells_the_commander_once(
        runs, restart, monkeypatch):  # noqa: F811
    """Row 1. The outline runs; the cover is queued behind it and has no task row yet. After the restart the outline's
    task is closed as interrupted (and its own conversation says so), both record `interrupted`, and the commander
    gets one line for both. Nothing runs again."""
    monkeypatch.setattr(background_jobs, "MAX_CONCURRENT", 1)
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(final="cover ready")},
                   summary=_steps(final="summed up"))
    model.hold[OUTLINE] = asyncio.Event()
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, COVER)
    await _wait(lambda: model.requests[OUTLINE])
    outline, cover = _by_goal()[OUTLINE].conversation_id, _by_goal()[COVER].conversation_id
    assert _by_goal()[COVER].phase == "queued"
    db = await restart()
    assert await _states(db, [outline, cover]) == {outline: "interrupted", cover: "interrupted"}
    assert (await _tasks(db)) == {outline: ("cancelled", "process_interrupted")}
    assert await _said(db, ROOT) == [(_line(2), None)]
    assert [outcome for _, outcome in await _said(db, outline)] == ["interrupted"]
    await _nothing_runs_again(model)


async def test_a_restart_voids_a_sub_sessions_waiting_card(runs, restart, monkeypatch):  # noqa: F811
    """Row 2. The cover's network card waits in the commander's window. After the restart nobody can answer it, its
    command never runs, the cover records `interrupted`, and the commander gets one line."""
    runner = _Run()
    monkeypatch.setitem(executors.EXECUTORS, "run_command", runner)
    shown = _sink(ROOT, answer=False)
    model = _Model({COVER: _steps(PAGE, COMMAND, final="cover ready")}, summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(COVER)
    await _wait(lambda: _cards(shown))
    [card] = _cards(shown)
    cover = _by_goal()[COVER].conversation_id
    db = await restart()
    assert approvals.pending_cards(ROOT) == []
    assert approvals.answer({"type": "confirm_" + card["type"].removeprefix("propose_"), "call_id": card["call_id"],
                             "scope": "once"}) is False
    assert runner.runs == []
    assert await _states(db, [cover]) == {cover: "interrupted"}
    assert (await _tasks(db))[cover] == ("cancelled", "process_interrupted")
    assert await _said(db, ROOT) == [(_line(1), None)]
    await _nothing_runs_again(model)
    assert runner.runs == []


async def test_a_commander_waiting_on_reports_gets_one_line_and_no_summary_turn(runs, restart, monkeypatch):  # noqa: F811
    """Row 3. Both sub-sessions ended and their reports wait for the commander, which the user is talking to (its turn
    lock is held). Their jobs' rows say done; only their own rows say their reports were still owed."""
    from server.ws import arslan as ws_arslan
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(final="cover ready")},
                   summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    lock = ws_arslan._turn_lock(ROOT)
    await lock.acquire()
    try:
        await _start(OUTLINE, COVER)
        await _wait(lambda: len(_children()) == 2 and all(job.task.done() for job in _children()))
        assert ROOT in sub_sessions._summaries and _summaries() == []
        ids = [job.conversation_id for job in _children()]
        db = await restart()
    finally:
        lock.release()
    assert await _states(db, ids) == dict.fromkeys(ids, "interrupted")
    assert set((await _tasks(db)).values()) == {("succeeded", None)}
    assert await _said(db, ROOT) == [(_line(2), None)]
    await _nothing_runs_again(model)
    assert model.requests["summary"] == []


async def test_a_restart_during_the_summary_turn_closes_it_as_any_job_and_adds_no_line(runs, restart, monkeypatch):  # noqa: F811
    """Row 4. The summary turn was running: the commander gets the job's interrupted note only, never the
    sub-sessions' line, and nothing runs again."""
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(final="cover ready")},
                   summary=_steps(final="summed up"))
    model.hold["summary"] = asyncio.Event()
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, COVER)
    await _wait(lambda: model.requests["summary"])
    ids = [job.conversation_id for job in _children()]
    assert set((await _states(runs, ids)).values()) == {sub_sessions.SUMMING}
    db = await restart()
    assert await _states(db, ids) == dict.fromkeys(ids)
    note = runtime_messages.render("job_interrupted", "en", goal="Sum up what the sub-sessions reported")
    assert await _said(db, ROOT) == [(note, "interrupted")]
    assert (await _tasks(db))[ROOT] == ("cancelled", "process_interrupted")
    await _nothing_runs_again(model)


async def test_a_summed_up_sub_session_owes_nothing_and_a_later_restart_says_nothing(runs, restart, monkeypatch):  # noqa: F811
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready")}, summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE)
    [child] = _children()
    assert await _states(runs, [child.conversation_id]) == {child.conversation_id: sub_sessions.WORKING}
    await _wait(_settled)
    await _wait(lambda: not sub_sessions._summing)
    assert await _states(runs, [child.conversation_id]) == {child.conversation_id: None}     # cleared when it ended
    db = await restart()
    assert await _states(db, [child.conversation_id]) == {child.conversation_id: None}
    assert await _said(db, ROOT) == [("summed up", "done")]


def test_0091_adds_the_state_once_and_touches_nothing_else(tmp_path):
    from server.db.migrations.versions import _0091_sub_session_state as m0091
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'contexts.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE conversation_contexts (id VARCHAR(100) PRIMARY KEY, "
                                 "version INTEGER NOT NULL DEFAULT 1)")
            conn.exec_driver_sql("INSERT INTO conversation_contexts (id, version) VALUES ('c-1', 3)")
            m0091.upgrade_sync(conn)
            m0091.upgrade_sync(conn)
            columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(conversation_contexts)")]
            row = conn.exec_driver_sql("SELECT * FROM conversation_contexts").one()
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE conversation_contexts")
            m0091.upgrade_sync(conn)
            assert conn.exec_driver_sql("SELECT name FROM sqlite_master").all() == []
    finally:
        engine.dispose()
    assert columns == ["id", "version", "sub_state"] and tuple(row) == ("c-1", 3, None)
    versions = [version for version, _ in runner.MIGRATIONS]
    assert versions.index("0091") == versions.index("0090") + 1       # S6's 0092 comes after it


# -- the window's stop ------------------------------------------------------------------------------------------------

async def _live_turn(db, cid) -> tuple[int, asyncio.Task]:
    """A chat turn of `cid` in flight, as the window's stop finds one: its run row and its registered task."""
    async with db() as session:
        run = Run(conversation_id=cid, user_message="go", status="recording")
        session.add(run)
        await session.commit()
    turn = asyncio.ensure_future(asyncio.Event().wait())
    run_registry.register(run.id, cid, turn)
    return run.id, turn


async def test_the_windows_stop_stops_the_commanders_sub_sessions_and_theirs_and_no_summary_follows(
        runs, client, monkeypatch):  # noqa: F811
    """The voice-over had finished and its report waited for the outline: it goes with the stop too."""
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(final="cover ready"),
                    OTHER_BRIEF: _steps(final="other ready"), THIRD: _steps(final="voice-over ready")},
                   summary=_steps(final="summed up"))
    for side in (OUTLINE, COVER, OTHER_BRIEF):
        model.hold[side] = asyncio.Event()
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, THIRD)
    kid, done = _by_goal()[OUTLINE], _by_goal()[THIRD]
    await _wait(lambda: done.task.done() and sub_sessions._reports.get(ROOT))
    grandchild = await sub_sessions.start(kid.conversation_id, COVER, outside_seen=False)
    elsewhere = await sub_sessions.start(OTHER, OTHER_BRIEF, outside_seen=False)
    await _wait(lambda: all(model.requests[side] for side in (OUTLINE, COVER, OTHER_BRIEF)))
    run_id, turn = await _live_turn(runs, ROOT)
    try:
        assert (await client.post(f"/api/v1/runs/{run_id}/cancel")).status_code == 202
        await _wait(lambda: turn.done())
        stopped = [job for job in background_jobs._jobs.values() if job.conversation_id in (kid.conversation_id,
                                                                                             grandchild)]
        await _wait(lambda: all(job.task.done() for job in stopped))
        assert [job.outcome for job in stopped] == ["stopped", "stopped"]
        assert [job.phase for job in background_jobs._jobs.values() if job.conversation_id == elsewhere] == ["running"]
        await asyncio.sleep(0.2)                                # twenty polls
        assert _summaries() == [] and model.requests["summary"] == [] and ROOT not in sub_sessions._summaries
        assert sub_sessions._reports == {}
        # The voice-over's dropped report is the only one that had finished (the outline and the cover were
        # stopped): the commander is told, in one line, as a restart tells it.
        assert await _said(runs, ROOT) == [(_stop_line(1), None)]
        assert await _states(runs, [kid.conversation_id, done.conversation_id, grandchild, elsewhere]) == {
            kid.conversation_id: None, done.conversation_id: None, grandchild: None, elsewhere: sub_sessions.WORKING}
    finally:
        run_registry.unregister(run_id, ROOT)


async def test_the_stops_line_counts_a_finished_sub_session_that_is_still_reporting(runs, client, monkeypatch):  # noqa: F811
    """The outline's run has finished and it is still posting its result (its report isn't in yet) when the window
    stops the commander's turn. The stop can't stop a finished job, but its report goes with the stop: the line
    counts it, and no summary turn follows."""
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready")}, summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    posting, gate = asyncio.Event(), asyncio.Event()
    real = background_jobs._report

    async def slow(job, text):
        if job.parent_id == ROOT:
            posting.set()
            await gate.wait()
        return await real(job, text)
    monkeypatch.setattr(background_jobs, "_report", slow)
    await _start(OUTLINE)
    [kid] = _children()
    await asyncio.wait_for(posting.wait(), 10)
    assert kid.phase == "finished" and not kid.task.done() and ROOT not in sub_sessions._reports
    run_id, turn = await _live_turn(runs, ROOT)
    try:
        assert (await client.post(f"/api/v1/runs/{run_id}/cancel")).status_code == 202
        await _wait(lambda: turn.done())
        gate.set()
        await _wait(lambda: kid.task.done())
        await asyncio.sleep(0.2)                                # twenty polls
        assert kid.outcome == "done" and sub_sessions._reports == {} and ROOT not in sub_sessions._summaries
        assert model.requests["summary"] == []
        assert await _said(runs, ROOT) == [(_stop_line(1), None)]
        assert await _states(runs, [kid.conversation_id]) == {kid.conversation_id: None}
    finally:
        gate.set()
        run_registry.unregister(run_id, ROOT)


async def _refused(awaitable) -> str | None:
    """The refusal's code, or None when it started. Not pytest.raises: when its "did not raise" (a BaseException)
    ended this test, the run never exited."""
    try:
        await awaitable
    except sub_sessions.SubSessionError as exc:
        return exc.code
    return None


async def test_a_sub_session_the_stopped_turn_starts_afterwards_never_runs(runs, client, monkeypatch):  # noqa: F811
    """One being made when the stop comes (its brief being stored) never gets a job, and owes nothing; one the stopped
    turn asks for afterwards is refused before it is made. Another turn's still starts."""
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(final="cover ready")},
                   summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    run_id, turn = await _live_turn(runs, ROOT)
    entered, gate = asyncio.Event(), asyncio.Event()
    real = memory_mod.add_message

    async def slow(cid, role, content, **kw):
        if cid.startswith("sub-") and not gate.is_set():
            entered.set()
            await gate.wait()
        return await real(cid, role, content, **kw)
    monkeypatch.setattr(memory_mod, "add_message", slow)
    with execution_context.bind_run(run_id):
        starting = asyncio.ensure_future(sub_sessions.start(ROOT, OUTLINE, outside_seen=False))
    try:
        await entered.wait()
        assert (await client.post(f"/api/v1/runs/{run_id}/cancel")).status_code == 202
        gate.set()
        assert await _refused(starting) == "sub_session_stopped" and background_jobs._jobs == {}
        async with runs() as db:
            [child] = await sub_sessions.children(db, ROOT)
        assert await _states(runs, [child]) == {child: None}
        with execution_context.bind_run(run_id):
            later = sub_sessions.start(ROOT, COVER, outside_seen=False)
            assert await _refused(later) == "sub_session_stopped"
        async with runs() as db:
            assert await sub_sessions.children(db, ROOT) == [child]
        with execution_context.bind_run(run_id + 1):
            await sub_sessions.start(ROOT, COVER, outside_seen=False)
        assert [job.goal for job in _children()] == [COVER]
        run_registry.unregister(run_id, ROOT)
        await _wait(_settled)
    finally:
        run_registry.unregister(run_id, ROOT)
        turn.cancel()


# -- delete -----------------------------------------------------------------------------------------------------------

async def _family(db, **root):
    """ROOT, its sub-session and that one's own, each with a message, made the way SUB3 makes them (no jobs)."""
    async with db() as session:
        session.add(ConversationContext(id=ROOT, **root))
        await session.flush()
        child = (await sub_sessions.create_child(session, ROOT)).id
        grandchild = (await sub_sessions.create_child(session, child)).id
        for cid in (ROOT, child, grandchild):
            session.add(ArslanMessage(conversation_id=cid, role="user", content=f"words of {cid}"))
            session.add(ConversationEvent(conversation_id=cid, kind="memory", summary="noted"))
            session.add(PermissionGrant(conversation_id=cid, kind="network", target="*"))
        await session.commit()
    return child, grandchild


async def _left(db, ids) -> dict:
    """For each conversation: its context row (False when none, or only its tombstone, is left), messages, events and
    grants still there."""
    out = {}
    async with db() as session:
        for cid in ids:
            row = await session.get(ConversationContext, cid)
            out[cid] = (row is not None and row.kind != sub_sessions.DELETED,
                        *[await session.scalar(select(func.count()).select_from(model).where(model.conversation_id == cid))
                          for model in (ArslanMessage, ConversationEvent, PermissionGrant)])
    return out


@pytest.mark.parametrize("working", ["child", "grandchild"])
@pytest.mark.parametrize("choice", [None, "delete", "keep"])
async def test_a_commander_is_not_deleted_while_a_sub_session_under_it_works(runs, client, monkeypatch, working,  # noqa: F811
                                                                           choice):
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(final="cover ready")},
                   summary=_steps(final="summed up"))
    model.hold[COVER if working == "grandchild" else OUTLINE] = asyncio.Event()
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await memory_mod.add_message(ROOT, "user", "make a video")
    await _start(OUTLINE)
    [kid] = _children()
    if working == "grandchild":
        await sub_sessions.start(kid.conversation_id, COVER, outside_seen=False)
        await _wait(lambda: kid.task.done() and model.requests[COVER])
    else:
        await _wait(lambda: model.requests[OUTLINE])
    url = f"/api/v1/conversations/{ROOT}" + (f"?sub_sessions={choice}" if choice else "")
    got = await client.delete(url)
    assert got.status_code == 409 and got.json()["detail"]["code"] == "sub_sessions_running"
    assert (await _left(runs, [ROOT, kid.conversation_id]))[ROOT][:2] == (True, 1)
    assert all(job.phase != "finished" for job in background_jobs._jobs.values()
               if job.goal == (COVER if working == "grandchild" else OUTLINE))


async def test_a_commander_with_sub_sessions_needs_an_explicit_choice(runs, client):  # noqa: F811
    child, grandchild = await _family(runs)
    got = await client.delete(f"/api/v1/conversations/{ROOT}")
    # SUB5d: every level counts (child and grandchild), as the window's dialog says "its N sub-sessions".
    assert got.status_code == 422 and got.json()["detail"] == {"code": "sub_sessions_choice_required",
                                                                "sub_sessions": 2}
    assert (await client.delete(f"/api/v1/conversations/{ROOT}?sub_sessions=maybe")).status_code == 422
    assert set((await _left(runs, [ROOT, child, grandchild])).values()) == {(True, 1, 1, 1)}


async def test_deleting_a_commander_with_its_sub_sessions_takes_every_row_of_the_tree(runs, client):  # noqa: F811
    child, grandchild = await _family(runs)
    got = await client.delete(f"/api/v1/conversations/{ROOT}?sub_sessions=delete")
    assert got.status_code == 200
    assert got.json()["deleted"]["conversation_contexts"] == 3 and got.json()["deleted"]["arslan_messages"] == 3
    assert set((await _left(runs, [ROOT, child, grandchild])).values()) == {(False, 0, 0, 0)}
    await memory_mod.add_message(ROOT, "user", "a new conversation under the same id")
    async with runs() as db:
        assert await sub_sessions.tree(db, ROOT) == [ROOT]


async def test_an_ordinary_conversations_context_row_goes_with_it(runs, client):  # noqa: F811
    async with runs() as db:
        db.add(ConversationContext(id=OTHER, no_memory=True))
        db.add(ArslanMessage(conversation_id=OTHER, role="user", content="hello"))
        await db.commit()
    got = await client.delete(f"/api/v1/conversations/{OTHER}")
    assert got.status_code == 200 and got.json()["deleted"]["conversation_contexts"] == 1
    assert (await _left(runs, [OTHER]))[OTHER] == (False, 0, 0, 0)


async def test_kept_sub_sessions_become_chats_no_looser_than_they_were(runs, client):  # noqa: F811
    """The commander allowed cloud memory and sensitive data when its sub-session started, then turned memory off and
    took cloud memory and sensitive data back. The kept sub-session's own row still says what it started with; what
    it read was stricter, and that is what it keeps. Its own sub-session stays under it."""
    child, grandchild = await _family(runs, cloud_memory_allowed=True, allow_sensitive=True)
    async with runs() as db:
        root = await db.get(ConversationContext, ROOT)
        root.no_memory, root.cloud_memory_allowed, root.allow_sensitive = True, False, False
        await db.commit()
        own = await db.get(ConversationContext, child)
        assert (own.no_memory, own.allow_sensitive, own.cloud_memory_allowed) == (False, True, True)
        before = await sub_sessions.effective_settings(db, own)
        grand_before = await sub_sessions.effective_settings(db, await db.get(ConversationContext, grandchild))
    got = await client.delete(f"/api/v1/conversations/{ROOT}?sub_sessions=keep")
    assert got.status_code == 200 and got.json()["kept"] == [child]
    async with runs() as db:
        row = await db.get(ConversationContext, child)
        assert (row.kind, row.parent_id, row.sub_state, row.version) == ("chat", None, None, 2)
        assert (row.no_memory, row.no_learning, row.temporary, row.cloud_memory_allowed, row.allow_sensitive) == (
            True, True, False, False, False)
        assert await sub_sessions.effective_settings(db, row) == before
        grand = await db.get(ConversationContext, grandchild)
        assert (grand.kind, grand.parent_id) == ("sub", child)
        assert await sub_sessions.effective_settings(db, grand) == grand_before
    assert (await _left(runs, [ROOT]))[ROOT] == (False, 0, 0, 0)
    assert (await _left(runs, [child, grandchild])) == {child: (True, 1, 1, 1), grandchild: (True, 1, 1, 1)}
    # SUB5d: the Mac's list shows sub-sessions under their parent, so the kept child is top-level and its own
    # sub-session stays under it.
    listed = {c["conversation_id"]: c.get("parent_id") for c in (await client.get("/api/v1/conversations")).json()}
    assert listed == {child: None, grandchild: child}


async def test_a_phones_delete_naming_a_sub_session_gets_not_found_and_changes_nothing(runs, client):  # noqa: F811
    """The Bridge's `conversation.delete` is DELETE /conversations/<id> with nothing else; a 404 is its `not_found`."""
    child, grandchild = await _family(runs)
    for cid in (child, grandchild):
        for url in (f"/api/v1/conversations/{cid}", f"/api/v1/conversations/{cid}?sub_session=false"):
            got = await client.delete(url)
            assert got.status_code == 404 and got.json()["detail"] == "not_found"
    assert set((await _left(runs, [ROOT, child, grandchild])).values()) == {(True, 1, 1, 1)}


def _outcomes(sent: str) -> dict:
    return {cid: outcome for outcome, cid in re.findall(
        r"Report \d+ \(outcome: (\w+)\):.*?Sub-session (sub-[0-9a-f-]+)\.", sent, flags=re.S)}


async def test_a_deleted_sub_session_its_commander_waits_on_reports_stopped_and_the_others_as_usual(
        runs, client, monkeypatch):  # noqa: F811
    """The outline is still working and the cover is done (its report waits): both are deleted. The voice-over
    finishes later as usual. The summary gets the two deleted ones as stopped, with nothing they said."""
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(final="cover ready"),
                    THIRD: _steps(final="voice-over ready")}, summary=_steps(final="summed up"))
    model.hold[OUTLINE], model.hold[THIRD] = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, COVER, THIRD)
    jobs = _by_goal()
    await _wait(lambda: jobs[COVER].task.done() and model.requests[OUTLINE] and model.requests[THIRD])
    for goal in (COVER, OUTLINE):
        got = await client.delete(f"/api/v1/conversations/{jobs[goal].conversation_id}?sub_session=true")
        assert got.status_code == 200, got.text
    assert jobs[OUTLINE].outcome == "stopped" and model.requests["summary"] == []
    model.hold[THIRD].set()
    await _wait(_settled)
    [request] = model.requests["summary"]
    sent = json.dumps(request["user"], ensure_ascii=False)
    assert _outcomes(sent) == {jobs[OUTLINE].conversation_id: "stopped", jobs[COVER].conversation_id: "stopped",
                               jobs[THIRD].conversation_id: "done"}
    assert "voice-over ready" in sent and "cover ready" not in sent
    gone = [jobs[goal].conversation_id for goal in (COVER, OUTLINE)]
    assert set((await _left(runs, gone)).values()) == {(False, 0, 0, 0)}


async def test_deleting_a_commander_whose_summary_waits_drops_it(runs, client, monkeypatch):  # noqa: F811
    """The outline is done and its report waits while the user talks to the commander (its turn lock is held). The
    commander is deleted with it: once the lock is free, no summary turn runs in the deleted conversation."""
    from server.ws import arslan as ws_arslan
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready")}, summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    lock = ws_arslan._turn_lock(ROOT)
    await lock.acquire()
    try:
        await _start(OUTLINE)
        await _wait(lambda: all(job.task.done() for job in _children()) and ROOT in sub_sessions._summaries)
        got = await client.delete(f"/api/v1/conversations/{ROOT}?sub_sessions=delete")
        assert got.status_code == 200, got.text
    finally:
        lock.release()
    await asyncio.sleep(0.3)                                    # thirty polls
    assert [job for job in background_jobs._jobs.values() if job.conversation_id == ROOT] == []
    assert sub_sessions._summaries == {} and sub_sessions._reports == {} and model.requests["summary"] == []


# -- delete never loosens a job's settings ----------------------------------------------------------------------------

PRIVATE, PRIVATE_GOAL = "c-private", "Tidy the private notes"
PLAIN, PLAIN_GOAL = "c-plain", "Plan the week"


async def _private(db):
    """A conversation with memory and learning off, and a message."""
    async with db() as session:
        session.add(ConversationContext(id=PRIVATE, no_memory=True, no_learning=True))
        session.add(ArslanMessage(conversation_id=PRIVATE, role="user", content="hello"))
        await session.commit()


async def _queued_behind_the_outline(monkeypatch, model):
    """The only job slot is held by the outline; PRIVATE's job waits for it."""
    monkeypatch.setattr(background_jobs, "MAX_CONCURRENT", 1)
    model.hold[OUTLINE] = asyncio.Event()
    await _start(OUTLINE)
    await _wait(lambda: model.requests[OUTLINE])
    job = await background_jobs.start(PRIVATE, PRIVATE_GOAL, [], outside_seen=False)
    assert job.phase == "queued"
    return job


async def test_a_queued_job_of_a_deleted_conversation_is_stopped_before_its_row_goes(runs, client, monkeypatch):  # noqa: F811
    """It would read its settings when it gets its slot, and find none. It is stopped instead: it never loads a context
    and never asks the model."""
    seen = _loads(monkeypatch)
    model = _Model({OUTLINE: _steps(final="outline ready"), PRIVATE_GOAL: _steps(final="tidied")},
                   summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _private(runs)
    job = await _queued_behind_the_outline(monkeypatch, model)
    got = await client.delete(f"/api/v1/conversations/{PRIVATE}")
    assert got.status_code == 200 and got.json()["deleted"]["conversation_contexts"] == 1
    assert job.task.done() and job.outcome == "stopped"
    model.hold[OUTLINE].set()
    await _wait(_settled)
    assert [load for load in seen if load[0] == PRIVATE] == [] and model.requests[PRIVATE_GOAL] == []
    assert await _said(runs, PRIVATE) == []


async def test_a_job_that_finds_its_conversation_deleted_refuses_to_run(runs, client, monkeypatch):  # noqa: F811
    """The second half, alone: a job the delete could not stop (here, a stop that reaches nothing) gets its slot after
    the row went. Its context load refuses, so it never runs on an ordinary conversation's defaults; and so does a
    chat turn's."""
    seen = _loads(monkeypatch)
    model = _Model({OUTLINE: _steps(final="outline ready"), PRIVATE_GOAL: _steps(final="tidied")},
                   summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _private(runs)
    job = await _queued_behind_the_outline(monkeypatch, model)
    monkeypatch.setattr(background_jobs, "stop", lambda conversation_id, job_id: False)
    monkeypatch.setattr(sub_sessions, "STOP_WAIT_S", 0.05)
    assert (await client.delete(f"/api/v1/conversations/{PRIVATE}")).status_code == 200
    assert job.phase == "queued"
    model.hold[OUTLINE].set()
    await _wait(lambda: job.task.done())
    assert [load for load in seen if load[0] == PRIVATE] == [(PRIVATE, "refused", "conversation_deleted")]
    assert job.outcome == "blocked" and model.requests[PRIVATE_GOAL] == []
    from arslan.companion.memory import MemoryError
    with pytest.raises(MemoryError, match="conversation_deleted"):
        await task_context.load(PRIVATE, user_message="hello again")
    assert (await _left(runs, [PRIVATE]))[PRIVATE] == (False, 0, 0, 0)
    await _wait(_settled)                   # the outline's summary turn in ROOT ends before the teardown


async def test_an_ordinary_conversation_that_never_had_a_row_still_runs(runs, client, monkeypatch):  # noqa: F811
    """Most conversations have no context row until a setting changes: one that never had one is not a deleted one,
    also right after another conversation was deleted."""
    seen = _loads(monkeypatch)
    model = _Model({PLAIN_GOAL: _steps(final="planned")})
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _private(runs)
    assert (await client.delete(f"/api/v1/conversations/{PRIVATE}")).status_code == 200
    job = await background_jobs.start(PLAIN, PLAIN_GOAL, [], outside_seen=False)
    await _wait(lambda: job.task.done())
    assert job.outcome == "done" and len(model.requests[PLAIN_GOAL]) == 1
    assert seen == [(PLAIN, False, False, False)]


async def test_a_deleted_commanders_live_turn_cannot_start_a_sub_session(runs, client):  # noqa: F811
    """The commander's turn goes on after its conversation is deleted. A sub-session it asks for is refused: it would
    give the deleted commander a fresh row with the defaults and run under it."""
    async with runs() as db:
        db.add(ConversationContext(id=ROOT, no_memory=True))
        db.add(ArslanMessage(conversation_id=ROOT, role="user", content="make a video"))
        await db.commit()
    assert (await client.delete(f"/api/v1/conversations/{ROOT}")).status_code == 200
    assert await _refused(sub_sessions.start(ROOT, OUTLINE, outside_seen=False)) == "conversation_deleted"
    assert background_jobs._jobs == {}
    assert await _row(runs, ROOT) == TOMBSTONE
    async with runs() as db:
        assert await sub_sessions.children(db, ROOT) == []


async def test_a_delete_during_a_sub_sessions_start_waits_for_it_and_then_finds_it_at_work(
        runs, client, monkeypatch):  # noqa: F811
    """The child's row is committed and its brief is being stored, so it has no job yet. The delete waits for the start
    to finish, then finds its job and refuses (409): the child runs under its commander's row, memory off."""
    seen = _loads(monkeypatch)
    model = _Model({OUTLINE: _steps(final="outline ready")}, summary=_steps(final="summed up"))
    model.hold[OUTLINE] = asyncio.Event()
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    async with runs() as db:
        db.add(ConversationContext(id=ROOT, no_memory=True))
        await db.commit()
    entered, gate = asyncio.Event(), asyncio.Event()
    real = memory_mod.add_message

    async def slow(cid, role, content, **kw):
        if cid.startswith("sub-") and not gate.is_set():
            entered.set()
            await gate.wait()
        return await real(cid, role, content, **kw)
    monkeypatch.setattr(memory_mod, "add_message", slow)
    starting = asyncio.ensure_future(sub_sessions.start(ROOT, OUTLINE, outside_seen=False))
    await entered.wait()
    deleting = asyncio.ensure_future(client.delete(f"/api/v1/conversations/{ROOT}?sub_sessions=delete"))
    await asyncio.sleep(0.2)
    assert not deleting.done()
    gate.set()
    child = await starting
    got = await deleting
    assert got.status_code == 409 and got.json()["detail"]["code"] == "sub_sessions_running"
    await _wait(lambda: model.requests[OUTLINE])
    assert seen == [(child, True, True, True)]
    assert (await _left(runs, [ROOT, child]))[ROOT][0] and (await _left(runs, [child]))[child][0]
    model.hold[OUTLINE].set()
    await _wait(_settled)


async def test_a_sub_session_asked_for_while_the_delete_waits_for_the_conversations_job_is_refused(
        runs, client, monkeypatch):  # noqa: F811
    """Why the process's mark stays beside the tombstone. The delete has passed its checks and waits for PRIVATE's own
    job to end, so its tombstone isn't written yet. PRIVATE's live turn asks for a sub-session meanwhile: refused, so
    none lands under a conversation being deleted, outside the ids the delete takes."""
    model = _Model({PRIVATE_GOAL: _steps(final="tidied"), OUTLINE: _steps(final="outline ready")},
                   summary=_steps(final="summed up"))
    model.hold[PRIVATE_GOAL] = asyncio.Event()
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _private(runs)
    job = await background_jobs.start(PRIVATE, PRIVATE_GOAL, [], outside_seen=False)
    await _wait(lambda: model.requests[PRIVATE_GOAL])
    asked = asyncio.Event()

    def slow_stop(conversation_id, job_id):            # a stop that takes the whole wait
        asked.set()
        return False
    monkeypatch.setattr(background_jobs, "stop", slow_stop)
    monkeypatch.setattr(sub_sessions, "STOP_WAIT_S", 0.5)
    deleting = asyncio.ensure_future(client.delete(f"/api/v1/conversations/{PRIVATE}"))
    await asyncio.wait_for(asked.wait(), 10)
    assert not deleting.done()
    assert await _refused(sub_sessions.start(PRIVATE, OUTLINE, outside_seen=False)) == "conversation_deleted"
    assert (await deleting).status_code == 200
    async with runs() as db:
        assert await sub_sessions.children(db, PRIVATE) == []
    assert [j.conversation_id for j in background_jobs._jobs.values()] == [PRIVATE] and model.requests[OUTLINE] == []
    model.hold[PRIVATE_GOAL].set()
    await _wait(lambda: job.task.done())


async def test_a_deleted_sub_sessions_job_that_outlives_the_wait_is_refused_its_next_model_request(runs):  # noqa: F811
    """Its row is gone, so its tree can't be read: it would read as a tree of one that spent nothing, with no shared
    limit. Its next model request is refused instead."""
    sub_sessions._deleted.add("sub-gone")
    assert await _refused(sub_sessions.check_tree_spend("sub-gone")) == "conversation_deleted"


# -- a delete survives a restart --------------------------------------------------------------------------------------
#
# There is no conversations table: a conversation is its messages and, once a setting changes, its context row. A first
# message to an id nothing has seen makes one (the window's `thread-<uuid>`, the phone's `phone-<uuid>`, and a scheduled
# task's `scheduled-<id>` on each fire), so a missing row can't say "deleted". The delete leaves the row as a tombstone
# instead: kind "deleted", the strictest values, nothing else.

TOMBSTONE = {"kind": "deleted", "project_id": None, "parent_id": None, "no_memory": True, "no_learning": True,
             "temporary": False, "cloud_memory_allowed": False, "allow_sensitive": False, "pinned": False,
             "sub_state": None, "learns_after_message_id": None}


async def _row(db, cid) -> dict | None:
    async with db() as session:
        row = await session.get(ConversationContext, cid)
    return None if row is None else {name: getattr(row, name) for name in TOMBSTONE}


async def test_after_a_restart_a_deleted_conversation_is_still_refused_and_nothing_runs_on_the_defaults(
        runs, client, restart, monkeypatch):  # noqa: F811
    """PRIVATE had memory and learning off; PLAIN never had a row. Both are deleted, and the process restarts, which
    forgets its deleted marks. A stale window's turn to either, a job there, and a sub-session under either are
    refused; nothing loads a context, asks the model or writes a message there, and neither comes back in the list."""
    seen = _loads(monkeypatch)
    model = _Model({PRIVATE_GOAL: _steps(final="tidied"), PLAIN_GOAL: _steps(final="planned"),
                    OUTLINE: _steps(final="outline ready")}, summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _private(runs)
    async with runs() as db:
        db.add(ArslanMessage(conversation_id=PLAIN, role="user", content="hello"))
        await db.commit()
    for cid in (PRIVATE, PLAIN):
        assert (await client.delete(f"/api/v1/conversations/{cid}")).status_code == 200
    db = await restart()
    assert sub_sessions._deleted == set()                       # what the next process knows of this one: nothing
    ran = []

    @task_context.scoped_turn                                   # what the window's typed turn goes through
    async def turn(conversation_id, user_message, emit):
        ran.append(conversation_id)
    from arslan.companion.memory import MemoryError
    for cid, goal in ((PRIVATE, PRIVATE_GOAL), (PLAIN, PLAIN_GOAL)):
        with pytest.raises(MemoryError, match="conversation_deleted"):
            await turn(cid, "hello again", lambda event: None)
        # SUB5b: a job there is refused before it starts (`sub_sessions.placement`), not at its context load.
        assert await _refused(background_jobs.start(cid, goal, [], outside_seen=False)) == "conversation_deleted"
        assert await _refused(sub_sessions.start(cid, OUTLINE, outside_seen=False)) == "conversation_deleted"
        assert await _said(db, cid) == [] and await _row(db, cid) == TOMBSTONE
        async with db() as session:
            assert await sub_sessions.children(session, cid) == []
    assert ran == [] and background_jobs._jobs == {}
    assert {side: requests for side, requests in model.requests.items() if requests} == {}
    assert seen == [(cid, "refused", "conversation_deleted") for cid in (PRIVATE, PLAIN)]
    assert (await client.get("/api/v1/conversations")).json() == []


async def test_after_a_restart_the_phone_and_the_settings_cannot_bring_a_deleted_conversation_back(
        runs, client, restart):  # noqa: F811
    """The phone's new-chat and new-quick-question calls take an id with no messages, which is what a deleted one has:
    they find the tombstone and refuse, as they do any other kind. So do turning it into a chat, the pin and the
    settings, so the tombstone stays what it is."""
    from uuid import uuid4
    phone = f"phone-{uuid4()}"
    assert (await client.post(f"/api/v1/phone/conversations/{phone}/chat")).status_code == 200
    await memory_mod.add_message(phone, "user", "from the phone")
    assert (await client.delete(f"/api/v1/conversations/{phone}")).status_code == 200
    db = await restart()
    for kind in ("chat", "quick"):
        got = await client.post(f"/api/v1/phone/conversations/{phone}/{kind}")
        assert got.status_code == 409 and got.json()["detail"] == "conversation_exists"
    got = await client.post(f"/api/v1/phone/conversations/{phone}/update", json={"kind": "chat"})
    assert got.status_code == 404 and got.json()["detail"] == "not_found"
    got = await client.put(f"/api/v1/conversations/{phone}/pin", json={"pinned": True})
    assert got.status_code == 404 and got.json()["detail"] == {"code": "conversation_not_found"}
    async with db() as session:
        version = (await session.get(ConversationContext, phone)).version
    got = await client.put(f"/api/v1/conversations/{phone}/context",
                           json={"schema_version": 1, "expected_version": version})
    assert got.status_code == 404 and got.json()["detail"] == {"code": "conversation_not_found"}
    assert await _row(db, phone) == TOMBSTONE
    async with db() as session:
        assert (await session.get(ConversationContext, phone)).version == version
    # A fresh id is a new conversation, as before.
    fresh = f"phone-{uuid4()}"
    assert (await client.post(f"/api/v1/phone/conversations/{fresh}/chat")).status_code == 200


async def test_every_conversation_of_a_deleted_tree_is_left_a_tombstone_outside_any_tree(runs, client):  # noqa: F811
    """And a sub-session whose parent is a tombstone (none should be: it would have been deleted or kept with it) reads
    its chain as broken, so it fails closed."""
    child, grandchild = await _family(runs, cloud_memory_allowed=True, allow_sensitive=True)
    assert (await client.delete(f"/api/v1/conversations/{ROOT}?sub_sessions=delete")).status_code == 200
    for cid in (ROOT, child, grandchild):
        assert await _row(runs, cid) == TOMBSTONE
    sub_sessions._deleted.clear()                               # as a restart does: the tombstones alone refuse
    assert await _refused(sub_sessions.check_tree_spend(child)) == "conversation_deleted"
    async with runs() as db:
        assert await sub_sessions.tree(db, ROOT) == [ROOT] and await sub_sessions.children(db, child) == []
        db.add(ConversationContext(id="sub-stray", kind="sub", parent_id=ROOT, no_learning=True,
                                   cloud_memory_allowed=True, allow_sensitive=True))
        await db.commit()
        stray = await sub_sessions.effective_settings(db, await db.get(ConversationContext, "sub-stray"))
    assert (stray.no_memory, stray.cloud_memory_allowed, stray.allow_sensitive) == (True, False, False)


# -- what writes into a deleted conversation is told so ---------------------------------------------------------------

def _scheduled_turns(monkeypatch) -> list[str]:
    """The conversations a scheduled fire's turn ran in (the turn itself is a stub)."""
    from server.orchestrator import arslan as arslan_mod
    ran = []

    async def answer(conversation_id, prompt, emit):
        ran.append(conversation_id)
    monkeypatch.setattr(arslan_mod, "_handle_answer", answer)
    return ran


async def _fired() -> None:
    """Every fire the scheduler started has ended, and none of them crashed."""
    from server.services import scheduler
    for _ in range(50):
        pending = [task for task in scheduler._tasks if not task.done()]
        if not pending:
            break
        done = await asyncio.gather(*pending, return_exceptions=True)
        assert [result for result in done if isinstance(result, BaseException)] == []


async def _runs_of(db, task_id) -> list[tuple]:
    from server.db.models import ScheduledTaskRun
    async with db() as session:
        return [(row.outcome, row.reason) for row in (await session.scalars(
            select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task_id).order_by(ScheduledTaskRun.id))).all()]


async def test_a_scheduled_task_whose_conversation_was_deleted_pauses_once_and_says_why(
        runs, client, monkeypatch, caplog):  # noqa: F811
    """A task made before v0.1.64 writes into `scheduled-<id>`. That conversation is deleted, and the process restarts.
    The next tick's fire is refused before it runs, so the task pauses with a reason the Scheduled page shows, one
    run row says why, and the next ticks leave it alone: no retry, no crash in the log, nothing written there."""
    from datetime import datetime, timedelta

    from server.db.models import ScheduledTask
    from server.services import scheduler
    ran = _scheduled_turns(monkeypatch)
    async with runs() as db:
        task = ScheduledTask(name="daily", prompt="Sum up the day", schedule_kind="interval", interval_s=3600,
                             enabled=True, consecutive_failures=0, next_due_at=datetime.utcnow() - timedelta(minutes=1))
        db.add(task)
        await db.commit()
        cid = f"scheduled-{task.id}"
        db.add(ConversationContext(id=cid, no_memory=True, no_learning=True))
        db.add(ArslanMessage(conversation_id=cid, role="arslan", content="yesterday's summary"))
        await db.commit()
    assert (await client.delete(f"/api/v1/conversations/{cid}")).status_code == 200
    sub_sessions._deleted.clear()                               # as a restart does: the tombstone alone refuses
    try:
        for _ in range(3):
            await scheduler.tick()
            await _fired()
    finally:
        scheduler._tasks.clear()
    assert ran == [] and await _said(runs, cid) == []
    assert await _runs_of(runs, task.id) == [("error", "conversation_deleted")]
    [shown] = (await client.get("/api/v1/scheduled-tasks")).json()
    assert (shown["enabled"], shown["paused_reason"], shown["next_due_at"], shown["last_outcome"]) == (
        False, "conversation_deleted", None, "error")
    assert "scheduler task crashed" not in caplog.text


async def test_a_new_task_never_lands_on_a_deleted_tasks_conversation(runs, client, monkeypatch):  # noqa: F811
    """SQLite gives a new task the id of the newest deleted one. A task's own conversation is no longer named after
    that id, so the new one never writes into, or is refused by, what the old one left. Fire now on the old one,
    after its conversation was deleted, pauses it as a tick does. Saving a task with no conversation keeps its own."""
    ran = _scheduled_turns(monkeypatch)
    body = {"name": "daily", "prompt": "Sum up the day", "schedule_kind": "interval", "interval_s": 3600}
    first = (await client.post("/api/v1/scheduled-tasks", json=body)).json()
    old = first["conversation_id"]
    assert old.startswith("scheduled-") and old != f"scheduled-{first['id']}"
    edited = await client.put(f"/api/v1/scheduled-tasks/{first['id']}", json={"conversation_id": None})
    assert edited.status_code == 200 and edited.json()["conversation_id"] == old
    await memory_mod.add_message(old, "arslan", "yesterday's summary")
    assert (await client.delete(f"/api/v1/conversations/{old}")).status_code == 200
    sub_sessions._deleted.clear()
    from server.services import scheduler
    try:
        assert (await client.post(f"/api/v1/scheduled-tasks/{first['id']}/fire-now")).status_code == 202
        await _fired()
        assert await _runs_of(runs, first["id"]) == [("error", "conversation_deleted")]
        assert (await client.get("/api/v1/scheduled-tasks")).json()[0]["paused_reason"] == "conversation_deleted"
        assert (await client.delete(f"/api/v1/scheduled-tasks/{first['id']}")).status_code == 200
        again = (await client.post("/api/v1/scheduled-tasks", json=body)).json()
        assert again["id"] == first["id"]                       # the reuse this guards against
        assert again["conversation_id"] not in (old, f"scheduled-{again['id']}")
        assert (await client.post(f"/api/v1/scheduled-tasks/{again['id']}/fire-now")).status_code == 202
        await _fired()
    finally:
        scheduler._tasks.clear()
    assert ran == [again["conversation_id"]] and await _runs_of(runs, again["id"]) == [("ok", "")]
    assert await _said(runs, old) == []


async def test_accepting_an_inbox_item_for_a_deleted_conversation_is_refused_and_leaves_it_there(
        runs, client, monkeypatch):  # noqa: F811
    """Its job would be refused when it gets its slot, with the item already marked accepted: gone from the Inbox, and
    nothing said. The accept is refused instead, before the item is claimed."""
    from server.db.models import ProactiveItem
    from server.services import proactive_service

    async def configured():
        return True
    monkeypatch.setattr(proactive_service, "model_configured", configured)
    await _private(runs)
    async with runs() as db:
        item = ProactiveItem(kind="job_followup", fingerprint="fp:deleted", source_key="job:deleted",
                             title_key="title.job_followup", evidence=[{"key": "x", "params": {}}],
                             goal=PRIVATE_GOAL, conversation_id=PRIVATE)
        db.add(item)
        await db.commit()
    assert (await client.delete(f"/api/v1/conversations/{PRIVATE}")).status_code == 200
    sub_sessions._deleted.clear()
    got = await client.post(f"/api/v1/proactive/items/{item.id}/accept", json={})
    assert got.status_code == 422 and got.json()["detail"] == {"code": "conversation_deleted"}
    async with runs() as db:
        assert (await db.get(ProactiveItem, item.id)).status == "new"
    assert background_jobs._jobs == {}


async def test_a_delete_waits_for_its_job_that_has_finished_and_is_still_posting_its_result(
        runs, client, monkeypatch):  # noqa: F811
    """The job reads finished, and its result is on its way into the conversation. The delete waits for it, so the
    result goes with the rest and the conversation is not listed again."""
    model = _Model({PRIVATE_GOAL: _steps(final="the private result")})
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _private(runs)
    posting, gate = asyncio.Event(), asyncio.Event()
    real = memory_mod.add_message

    async def add_message(conversation_id, role, content, *args, **kwargs):
        if conversation_id == PRIVATE and role == "arslan" and not posting.is_set():
            posting.set()
            await gate.wait()
        return await real(conversation_id, role, content, *args, **kwargs)
    monkeypatch.setattr(memory_mod, "add_message", add_message)
    job = await background_jobs.start(PRIVATE, PRIVATE_GOAL, [], outside_seen=False)
    await asyncio.wait_for(posting.wait(), 10)
    assert job.phase == "finished"
    deleting = asyncio.ensure_future(client.delete(f"/api/v1/conversations/{PRIVATE}"))
    await asyncio.sleep(0.3)
    waited = not deleting.done()
    gate.set()
    assert (await deleting).status_code == 200 and waited
    await _wait(lambda: job.task.done())
    assert await _said(runs, PRIVATE) == []
    assert (await client.get("/api/v1/conversations")).json() == []


# -- undo -------------------------------------------------------------------------------------------------------------

@pytest.fixture
def folder(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(checkpoints, "_free_bytes", lambda path: 2 * checkpoints.MIN_FREE)
    work = tmp_path / "work"
    work.mkdir()
    (work / "outline.md").write_text("before")
    checkpoints._reset_for_tests()
    yield work.resolve()
    checkpoints._reset_for_tests()


async def test_undoing_the_turn_that_started_a_sub_session_keeps_it_and_its_files_follow_s3(
        runs, monkeypatch, folder):  # noqa: F811
    """S3's undo of the commander's turn takes back the commander's conversation only. The files go back through
    S3's undo across runs: the sub-session's later run on the same folder is listed and put back first."""
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready")}, summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await memory_mod.add_message(ROOT, "user", "make a video")
    async with runs() as db:
        turn = Run(conversation_id=ROOT, user_message="make a video", status="done")
        db.add(turn)
        await db.flush()
        db.add(ArslanMessage(conversation_id=ROOT, role="arslan", content="started a sub-session", run_id=turn.id))
        await db.commit()
    with execution_context.bind_run(turn.id):
        child = await sub_sessions.start(ROOT, OUTLINE, outside_seen=False)
    await _wait(_settled)
    async with runs() as db:
        child_run = await db.scalar(select(Run.id).where(Run.conversation_id == child))
    assert child_run > turn.id

    async def changed(run_id, text):
        await checkpoints.ensure(run_id, [folder])
        (folder / "outline.md").write_text(text)
        await checkpoints.finish(run_id)
    await changed(turn.id, "the commander's")
    await changed(child_run, "the sub-session's")
    assert checkpoints.summary(turn.id, 0)["later"] == [child_run]
    out = await turn_undo.undo(turn.id)
    assert out["conversation_id"] == ROOT and await _said(runs, ROOT) == []
    files = await checkpoints.restore_files(turn.id)
    assert files["later"] == [child_run] and (folder / "outline.md").read_text() == "before"
    async with runs() as db:
        row = await db.get(ConversationContext, child)
        assert (row.kind, row.parent_id) == ("sub", ROOT)
    assert [text for text, _ in await _said(runs, child)] == ["outline ready"]
