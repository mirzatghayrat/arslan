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
                             runtime_messages, sub_sessions, task_service, turn_undo)
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
    monkeypatch.setattr(auth, "active_token", lambda: "sub5a-token")
    app = FastAPI()
    app.include_router(conversations_router, prefix="/api/v1")
    app.include_router(runs_router, prefix="/api/v1")
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
    assert [version for version, _ in runner.MIGRATIONS][-1] == "0091"


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
        assert await _states(runs, [kid.conversation_id, done.conversation_id, grandchild, elsewhere]) == {
            kid.conversation_id: None, done.conversation_id: None, grandchild: None, elsewhere: sub_sessions.WORKING}
    finally:
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
    """For each conversation: its context row, messages, events and grants still there."""
    out = {}
    async with db() as session:
        for cid in ids:
            out[cid] = (await session.get(ConversationContext, cid) is not None,
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
    assert got.status_code == 422 and got.json()["detail"] == {"code": "sub_sessions_choice_required",
                                                                "sub_sessions": 1}
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
    took sensitive data back. The kept sub-session's own row still says what it started with; what it read was
    stricter, and that is what it keeps. Its own sub-session stays under it."""
    child, grandchild = await _family(runs, cloud_memory_allowed=True, allow_sensitive=True)
    async with runs() as db:
        root = await db.get(ConversationContext, ROOT)
        root.no_memory, root.allow_sensitive = True, False
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
            True, True, False, True, False)
        assert await sub_sessions.effective_settings(db, row) == before
        grand = await db.get(ConversationContext, grandchild)
        assert (grand.kind, grand.parent_id) == ("sub", child)
        assert await sub_sessions.effective_settings(db, grand) == grand_before
    assert (await _left(runs, [ROOT]))[ROOT] == (False, 0, 0, 0)
    assert (await _left(runs, [child, grandchild])) == {child: (True, 1, 1, 1), grandchild: (True, 1, 1, 1)}
    listed = [c["conversation_id"] for c in (await client.get("/api/v1/conversations")).json()]
    assert listed == [child]


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
