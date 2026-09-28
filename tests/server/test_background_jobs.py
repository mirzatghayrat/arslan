"""0.1.42 background work: the conversation stays free while a job runs.

Offline: a scripted adapter stands in for the model. No paid calls.
"""
import asyncio
import time
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from arslan.execution_budget import current as current_budget
from arslan.models import LLMResponse
from server.db.models import ArslanMessage, CompanionTask
from server.orchestrator import tool_loop
from server.registry.task_tools import StartBackgroundWorkExecutor
from server.services import (approvals, background_jobs, desktop_status, personal_context as pc, run_registry,
                             runtime_messages,
                             task_context, task_service)

CID = "conv-bg"
PHRASE = "tidy-report-ready"


@pytest.fixture(autouse=True)
def fresh():
    background_jobs._reset_for_tests()
    approvals._reset_for_tests()
    desktop_status._reset_for_tests()
    yield
    background_jobs._reset_for_tests()
    approvals._reset_for_tests()


@pytest.fixture
def active(monkeypatch):
    monkeypatch.setattr(task_context, "is_active", AsyncMock(return_value=True))

    async def load(cid, **kwargs):
        identity = str(uuid.uuid4())
        return pc.TaskMemoryContext(task_id=identity, run_id=f"turn-{identity}", conversation_id=cid,
                                    no_memory=True, no_learning=True,
                                    query=kwargs.get("retrieval_query") or kwargs.get("user_message", ""))
    monkeypatch.setattr(task_context, "load", load)


@pytest.fixture
def frames():
    seen = []
    run_registry.attach_sink(CID, seen.append)
    yield seen
    run_registry.detach_sink(CID, seen.append)


class JobAdapter:
    """Background system prompts wait on `gate`; everything else answers at once."""

    def __init__(self, gate: asyncio.Event | None = None, text=f"Done: {PHRASE}"):
        self.gate, self.text, self.job_calls, self.running, self.peak = gate, text, 0, 0, 0

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        if "BACKGROUND" in str(system):
            self.job_calls += 1
            self.running += 1
            self.peak = max(self.peak, self.running)
            try:
                if self.gate is not None:
                    await asyncio.wait_for(self.gate.wait(), 5)
            finally:
                self.running -= 1
            return LLMResponse(content=self.text, tool_calls=[], usage={})
        return LLMResponse(content="ok", tool_calls=[], usage={})


async def _wait(predicate, seconds=5.0):
    deadline = asyncio.get_running_loop().time() + seconds
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


def _criteria():
    return [{"description": f"The result says {PHRASE}", "kind": "mentions", "target": PHRASE}]


async def test_a_job_runs_as_its_own_task_and_posts_one_result(execution_db, active, frames, monkeypatch):
    adapter = JobAdapter()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    job = await background_jobs.start(CID, "Tidy my notes into a report", _criteria())
    await _wait(lambda: job.phase == "finished")
    assert job.outcome == "done", (job.detail, job.results)
    async with execution_db() as db:
        task = await db.get(CompanionTask, job.job_id)
        assert task.privacy["driver"] == {"kind": "background"} and task.phase == "succeeded"
        messages = (await db.scalars(select(ArslanMessage).where(ArslanMessage.conversation_id == CID))).all()
    assert [m.content for m in messages] == [f"Done: {PHRASE}"]
    updates = [f for f in frames if f["type"] == "job_update" and f["job_id"] == job.job_id]
    assert [u["phase"] for u in updates][0] == "queued" and updates[-1]["outcome"] == "done"
    assert updates[-1]["criteria"] == [{"id": "criterion-1", "description": f"The result says {PHRASE}",
                                        "status": "passed"}]
    assert not any(f["type"] in {"stream_start", "stream_chunk"} for f in frames), "a job never types into the chat"
    assert any(f["type"] == "job_spoken" and f["outcome"] == "done" for f in frames)
    assert desktop_status.snapshot()["events"][-1]["kind"] == "turn_finished"


async def test_the_starting_turn_ends_before_the_job_and_shares_nothing_with_it(execution_db, active, monkeypatch):
    gate = asyncio.Event()
    adapter = JobAdapter(gate)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    seen = {}

    async def turn(conversation_id, user_message, emit):
        seen["turn_task"] = task_service.current().task_id
        seen["turn_budget"] = current_budget().id
        seen["tool"] = await StartBackgroundWorkExecutor().execute({"goal": "Tidy my notes", "criteria": _criteria()})
        return "Started it in the background; done means the report says so."   # the one-line reply

    ctx = await task_context.load(CID, user_message="tidy my notes")
    with pc.bind(ctx):
        await asyncio.wait_for(task_service.run_turn(turn, CID, "tidy my notes", lambda e: None), 3)
    result = seen["tool"]
    assert result["ok"] and result["job_id"].startswith("job-") and result["queued"] is False
    job = background_jobs._jobs[result["job_id"]]
    await _wait(lambda: adapter.job_calls == 1)
    assert job.phase == "running", "the turn returned while the job was still working"
    async with execution_db() as db:
        turn_row = await db.get(CompanionTask, seen["turn_task"])
        assert turn_row.phase == "succeeded"          # the turn delivered its answer and is done
        job_row = await db.get(CompanionTask, job.job_id)
        assert job_row.id != turn_row.id and job_row.budget["id"] != seen["turn_budget"]
    gate.set()
    await _wait(lambda: job.phase == "finished")
    assert job.outcome == "done"


async def test_no_more_than_the_limit_run_at_once(execution_db, active, monkeypatch):
    gate = asyncio.Event()
    adapter = JobAdapter(gate)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setattr(background_jobs, "MAX_CONCURRENT", 2)
    jobs = [await background_jobs.start(CID, f"job {i}", _criteria()) for i in range(3)]
    await _wait(lambda: adapter.running == 2)
    await asyncio.sleep(0.05)
    assert sorted(job.phase for job in jobs) == ["queued", "running", "running"]
    gate.set()
    await _wait(lambda: all(job.phase == "finished" for job in jobs))
    assert adapter.peak == 2 and all(job.outcome == "done" for job in jobs)


async def test_a_stopped_job_says_stopped_and_posts_no_filler(execution_db, active, frames, monkeypatch):
    gate = asyncio.Event()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: JobAdapter(gate))
    job = await background_jobs.start(CID, "long work", _criteria())
    await _wait(lambda: job.phase == "running")
    assert not background_jobs.stop("other-conversation", job.job_id)   # scoped to its conversation
    assert background_jobs.stop(CID, job.job_id)
    await _wait(lambda: job.phase == "finished")
    assert job.outcome == "stopped"
    async with execution_db() as db:
        assert (await db.scalars(select(ArslanMessage))).all() == []


async def test_an_answer_missing_the_criterion_is_not_done(execution_db, active, monkeypatch):
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: JobAdapter(text="I made a start."))
    job = await background_jobs.start(CID, "write the report", _criteria())
    await _wait(lambda: job.phase == "finished")
    assert job.outcome in {"partial", "blocked"} and job.outcome != "done"


def test_outcome_words():
    assert background_jobs.outcome_of("succeeded", {}, None) == "done"
    assert background_jobs.outcome_of("cancelled", {}, None) == "stopped"
    partly = {"answer-delivered": "passed", "criterion-1": "passed", "criterion-2": "failed"}
    assert background_jobs.outcome_of("waiting_user", partly, "task_validation_failed") == "partial"
    assert background_jobs.outcome_of("waiting_user", {"answer-delivered": "failed"}, "task_input_required") == "blocked"
    assert background_jobs.outcome_of("failed", {}, "task_execution_failed") == "blocked"


def test_criteria_always_keep_one_non_model_check_and_map_checkable_kinds():
    checks = background_jobs.criteria_to_acceptance([
        {"description": "Saved as resume.md", "kind": "file_saved", "target": "resume.md"},
        {"description": "Read three sources", "kind": "sources_read", "minimum": 3},
        {"description": "Reads naturally", "kind": "judgement"},
        {"description": "   "}] + [{"description": f"extra {i}"} for i in range(9)])
    assert checks[0]["id"] == "answer-delivered" and checks[0]["evaluator"] == "deterministic"
    assert checks[1]["rule"] == {"kind": "artifact", "target": "resume.md"}
    assert checks[2]["rule"] == {"kind": "research_sources", "minimum": 3}
    assert checks[3]["evaluator"] == "model"
    assert len(checks) <= 1 + background_jobs.MAX_CRITERIA


async def test_background_tools_exist_only_in_a_turn_never_inside_a_job(execution_db, active, monkeypatch):
    from server.orchestrator.arslan import _arslan_tools, _background_tools
    keys = {"start_background_work", "background_status", "stop_background_work"}
    seen = {}

    async def turn(conversation_id, user_message, emit):
        seen["turn"] = {t["key"] for t in await _arslan_tools()}
        token = background_jobs._inside_job.set("job-x")
        try:
            seen["job"] = {t["key"] for t in await _arslan_tools()}
        finally:
            background_jobs._inside_job.reset(token)
        seen["body"] = {t["key"] for t in await _background_tools()}
        return "ok"

    ctx = await task_context.load(CID, user_message="x")
    with pc.bind(ctx):
        await task_service.run_turn(turn, CID, "x", lambda e: None)
    assert keys <= seen["turn"]
    assert not keys & seen["job"] and not keys & seen["body"] and "ask_user_choice" not in seen["body"]


async def test_cards_are_answered_by_call_id_and_kind_and_time_out_to_no(monkeypatch):
    sent = []
    run_registry.attach_sink(CID, sent.append)
    try:
        waiting = asyncio.create_task(approvals.ask(CID, {"type": "propose_schedule", "call_id": "c1",
                                                          "name": "n", "when": "daily"}))
        await _wait(lambda: sent)
        assert approvals.pending_cards(CID) == [sent[0]]
        assert desktop_status.snapshot()["awaiting"] == 1
        assert not approvals.answer({"type": "confirm_run_command", "call_id": "c1"}), "wrong kind"
        assert not approvals.answer({"type": "confirm_schedule", "call_id": "other"})
        assert approvals.answer({"type": "confirm_schedule", "call_id": "c1"})
        assert await waiting is True
        assert approvals.pending_cards(CID) == [] and desktop_status.snapshot()["awaiting"] == 0
        monkeypatch.setattr(approvals, "TIMEOUT_S", 0.05)
        assert await approvals.ask(CID, {"type": "propose_schedule", "call_id": "c2",
                                         "name": "n", "when": "daily"}) is False
    finally:
        run_registry.detach_sink(CID, sent.append)


async def test_job_commands_never_reuse_session_grants_and_remote_always_asks(monkeypatch):
    from server.services import settings_service
    monkeypatch.setattr(settings_service, "shell_confirm_policy", AsyncMock(return_value="ask_risky"))
    asked = []

    async def ask(cid, frame):
        asked.append(frame["type"])
        return False
    monkeypatch.setattr(approvals, "ask", ask)
    confirm = approvals.JobConfirmations(CID)
    assert await confirm.command("git", ["status"]) is True          # LOW under ask_risky, as in the foreground
    assert await confirm.command("git", ["status"], remote_host="box") is False
    assert asked == ["propose_run_command"]


def test_migration_0054_lets_jobs_run_beside_a_turn_but_never_two_turns(tmp_path):
    """Upgrade a database carrying the 0053 index, then exercise the new one."""
    import sqlite3
    from server.db.migrations.versions._0054_background_jobs_index import upgrade_sync
    import sqlalchemy as sa
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE companion_tasks (id TEXT PRIMARY KEY, owner_id TEXT, conversation_id TEXT,"
                   " phase TEXT, privacy TEXT)")
        db.execute("CREATE UNIQUE INDEX uq_companion_active_conversation ON companion_tasks"
                   " (owner_id, conversation_id) WHERE phase IN ('running','verifying')")
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        upgrade_sync(connection)
    with sqlite3.connect(path) as db:
        insert = "INSERT INTO companion_tasks VALUES (?, 'local', 'c', 'running', ?)"
        db.execute(insert, ("turn", '{"driver": {"kind": "host"}}'))
        db.execute(insert, ("job-1", '{"driver": {"kind": "background"}}'))
        db.execute(insert, ("job-2", '{"driver": {"kind": "background"}}'))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(insert, ("second-turn", '{"driver": {"kind": "host"}}'))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(insert, ("legacy-turn", "{}"))     # no recorded driver counts as a turn


# ── end to end over the real websocket ─────────────────────────────────────────
from tests.server.test_run_command_confirm_flow import _collect_until, _stub_answer_route, app_client  # noqa: E402,F401


def test_the_conversation_answers_while_a_job_is_still_working(app_client, monkeypatch):  # noqa: F811
    import threading
    release = threading.Event()
    state = {"job_calls": 0}

    class Adapter:
        async def chat(self, system, user, history=None, tools=None, temperature=0.7):
            if "BACKGROUND" in str(system):
                state["job_calls"] += 1
                while not release.is_set():
                    await asyncio.sleep(0.01)
                return LLMResponse(content=f"Report finished: {PHRASE}", tool_calls=[], usage={})
            said = str(user)
            if "tidy" in said and not any("start_background_work" in str(h) for h in history or []):
                return LLMResponse(content=None, usage={}, tool_calls=[{"id": "c1", "function": {
                    "name": "start_background_work",
                    "arguments": {"goal": "Tidy my notes into a report", "criteria": _criteria()}}}])
            if "tidy" in said:
                return LLMResponse(content="Started it in the background.", tool_calls=[], usage={})
            return LLMResponse(content="Hello! I'm here.", tool_calls=[], usage={})

    async def load(cid, **kwargs):
        identity = str(uuid.uuid4())
        return pc.TaskMemoryContext(task_id=identity, run_id=f"turn-{identity}", conversation_id=cid,
                                    no_memory=True, no_learning=True, query=kwargs.get("user_message", ""))
    monkeypatch.setattr(task_context, "is_active", AsyncMock(return_value=True))
    monkeypatch.setattr(task_context, "load", load)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())
    _stub_answer_route(monkeypatch)
    try:
        with app_client.websocket_connect("/ws/arslan/main") as ws:
            ws.receive_json()
            ws.receive_json()
            ws.send_json({"type": "user_message", "content": "please tidy my notes"})
            first = _collect_until(ws, "stream_end", max_frames=400)
            assert any(f.get("type") == "job_update" for f in first), [(f.get("type"), f.get("tool")) for f in first]
            deadline = time.monotonic() + 5
            while state["job_calls"] == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert state["job_calls"] == 1, "the job started"
            started = time.monotonic()
            ws.send_json({"type": "user_message", "content": "hi"})
            second = _collect_until(ws, "stream_end", max_frames=400)
            assert time.monotonic() - started < 3, "answered while the job was still working"
            assert "Hello" in "".join(f.get("content") or "" for f in second if f.get("type") == "stream_chunk")
            job = next(iter(background_jobs._jobs.values()))
            assert job.phase == "running"
            release.set()
            result = _collect_until(ws, "message", max_frames=400)
            assert not any(f.get("type") == "task_state" and f.get("task_id") == job.job_id for f in second + result), \
                "a job's own task frames never masquerade as the conversation's turn"
            assert PHRASE in result[-1]["content"] and result[-1]["job_id"] == job.job_id
    finally:
        release.set()


def test_a_background_card_is_answered_over_the_socket_and_resent_on_reconnect(app_client):  # noqa: F811
    frame = {"type": "propose_schedule", "call_id": "bg-card", "name": "Weekly digest", "when": "weekly"}
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.receive_json()
        waiting = app_client.portal.start_task_soon(approvals.ask, "main", frame)
        # broadcast at once, marked as a job's card (the UI hides "remember" for it)
        assert ws.receive_json() == frame | {"background": True}
    with app_client.websocket_connect("/ws/arslan/main") as ws:   # a tab that opened later
        replay = [ws.receive_json() for _ in range(3)]
        assert frame | {"background": True} in replay, "a pending background card is shown to a reconnecting tab"
        ws.send_json({"type": "confirm_run_command", "call_id": "bg-card"})   # wrong kind: ignored
        ws.send_json({"type": "confirm_schedule", "call_id": "bg-card"})
        assert waiting.result(timeout=5) is True


def test_the_jobs_endpoint_lists_running_work_and_stops_it_by_id(app_client):  # noqa: F811
    gate = asyncio.Event()

    async def hold():
        await gate.wait()

    job = background_jobs.Job(job_id="job-api", conversation_id="main", goal="long work", acceptance=[])
    job.phase = "running"
    background_jobs._jobs[job.job_id] = job
    job.task = app_client.portal.start_task_soon(hold)
    listed = app_client.get("/api/v1/background-jobs").json()
    assert listed["active"] == 1 and listed["jobs"][0]["job_id"] == "job-api"
    assert app_client.get("/api/v1/background-jobs", params={"conversation_id": "other"}).json()["jobs"] == []
    assert app_client.post("/api/v1/background-jobs/nope/stop").status_code == 404
    assert app_client.post("/api/v1/background-jobs/job-api/stop").status_code == 200
    assert job.task.cancelled() or job.task.done()
    job.phase = "finished"
    assert app_client.post("/api/v1/background-jobs/job-api/stop").status_code == 409


def test_a_reconnecting_tab_gets_running_job_cards_but_not_finished_ones(app_client):  # noqa: F811
    for job_id, phase in (("job-live", "running"), ("job-done", "finished")):
        job = background_jobs.Job(job_id=job_id, conversation_id="main", goal=job_id, acceptance=[])
        job.phase = phase
        background_jobs._jobs[job_id] = job
    frame = {"type": "propose_schedule", "call_id": "marker", "name": "n", "when": "w"}
    waiting = app_client.portal.start_task_soon(approvals.ask, "main", frame)
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        seen = []
        while not seen or seen[-1].get("call_id") != "marker":
            seen.append(ws.receive_json())
        jobs = [f["job_id"] for f in seen if f.get("type") == "job_update"]
        assert jobs == ["job-live"], "a finished job is in the history as its result; its card is not re-sent"
        ws.send_json({"type": "cancel_schedule", "call_id": "marker"})
    assert waiting.result(timeout=5) is False


def test_old_finished_jobs_are_forgotten_but_running_ones_never(monkeypatch):
    monkeypatch.setattr(background_jobs, "KEEP_FINISHED", 2)
    for i in range(4):
        job = background_jobs.Job(job_id=f"done-{i}", conversation_id=CID, goal="g", acceptance=[])
        job.phase = "finished"
        background_jobs._jobs[job.job_id] = job
    live = background_jobs.Job(job_id="live", conversation_id=CID, goal="g", acceptance=[])
    live.phase = "running"
    background_jobs._jobs["live"] = live
    background_jobs._forget_old_finished()
    assert set(background_jobs._jobs) == {"done-3", "live"}   # room left for the job about to start


async def test_a_restart_closes_interrupted_jobs_and_says_so_once(execution_db, monkeypatch):
    from server.services.task_repository import repository
    from tests.server.test_task_repository import spec
    monkeypatch.setattr(runtime_messages, "selected_locale", AsyncMock(return_value="en"))
    async with repository() as repo:
        for identity, driver in (("job-cut", "background"), ("turn-cut", "host")):
            created = await repo.create(spec(identity, instruction=f"Goal of {identity}"), CID,
                                        privacy={"driver": {"kind": driver}})
            await repo.start(identity, created["version"])
    async with repository() as repo:
        assert await repo.recover_interrupted() == 2          # what a restart finds
    assert await background_jobs.report_interrupted() == 1
    async with execution_db() as db:
        messages = (await db.scalars(select(ArslanMessage))).all()
        job = await db.get(CompanionTask, "job-cut")
        turn = await db.get(CompanionTask, "turn-cut")
    assert [(m.job_outcome, "Goal of job-cut" in m.content, "interrupted" in m.content) for m in messages] == [
        ("interrupted", True, True)]
    assert job.phase == "cancelled"
    assert (turn.phase, turn.pause_reason) == ("waiting_user", "process_interrupted"), "a chat turn keeps its own recovery"
    assert await background_jobs.report_interrupted() == 0   # said once


async def test_a_result_keeps_its_outcome_in_history(execution_db, active, frames, monkeypatch):
    from server.ws.arslan import _history
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: JobAdapter())
    job = await background_jobs.start(CID, "Tidy my notes into a report", _criteria())
    await _wait(lambda: job.phase == "finished")
    await _wait(lambda: any(f.get("type") == "job_spoken" for f in frames))
    rows = await _history(CID)
    assert [r["job_outcome"] for r in rows if r["role"] == "arslan"] == [job.outcome]


def test_migration_0055_adds_the_outcome_column_once(tmp_path):
    import sqlalchemy as sa
    from server.db.migrations.versions._0055_message_job_outcome import upgrade_sync
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE arslan_messages (id INTEGER PRIMARY KEY, content TEXT)"))
        connection.execute(sa.text("INSERT INTO arslan_messages (content) VALUES ('kept')"))
        upgrade_sync(connection)
        upgrade_sync(connection)   # idempotent
        rows = connection.execute(sa.text("SELECT content, job_outcome FROM arslan_messages")).all()
    assert rows == [("kept", None)]
