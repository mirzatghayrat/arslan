"""INB6 (v0.1.64): each run's record holds what the progress page and the Scheduled page need.

- A scheduled fire records the run it made, on its scheduled_task_runs row and its timeline event, so
  the Scheduled page can open each run. The scheduler wrote None there, whatever the turn recorded.
- read_file and search_files steps keep every path they read in `detail.paths`. `result_raw` is cut at
  RUN_RAW_CAP, which drops most of a search's matches.
- The four diagnostics count the user's own run kinds (run_kinds.USER_RUN_KINDS), as GET /runs does.
  They counted only 'live', which no turn has written since host runs became the default (2026-09-14).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, ConversationEvent, Run, RunStep, ScheduledTask, ScheduledTaskRun
from server.orchestrator import arslan, run_trace
from server.services import run_recorder, scheduler
from server.services.run_recorder import RUN_RAW_CAP


@pytest.fixture
async def memdb(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda run_id: None)
    yield Session
    for t in list(scheduler._tasks):
        t.cancel()
    scheduler._tasks.clear()
    await engine.dispose()


async def _drain() -> None:
    for _ in range(50):
        tasks = [t for t in scheduler._tasks if not t.done()]
        if not tasks:
            break
        await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.sleep(0)


def _turn_body(ending: str):
    """Stands in for arslan._handle_answer_body, under the real _handle_answer: host_run.execute records the
    run and links it to the fire's task, as in production. The turn ends as asked: fine, with an error
    frame, or raising."""
    async def fake_body(conversation_id, user_message, emit, **kwargs):
        emit({"type": "stream_chunk", "content": "done"})
        if ending == "error":
            emit({"type": "error", "message": "the model failed"})
        if ending == "raise":
            raise RuntimeError("the turn broke")
        return "done"
    return fake_body


@pytest.mark.parametrize("ending,outcome", [("fine", "ok"), ("error", "error"), ("raise", "error")])
async def test_a_scheduled_fire_records_the_run_it_made(memdb, monkeypatch, ending, outcome):
    async with memdb() as db:
        task = ScheduledTask(name="weekly", prompt="summarise the week", schedule_kind="interval",
                             interval_s=3600, enabled=True, consecutive_failures=0,
                             next_due_at=datetime.utcnow() - timedelta(minutes=1))
        db.add(task)
        await db.commit()
        task_id = task.id
    monkeypatch.setattr(arslan, "_handle_answer_body", _turn_body(ending))

    await scheduler.tick()
    await _drain()

    async with memdb() as db:
        made = list((await db.execute(select(Run.id))).scalars().all())
        row = (await db.execute(select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task_id))).scalar_one()
        events = (await db.execute(select(ConversationEvent)
                                   .where(ConversationEvent.kind == "scheduled_fire"))).scalars().all()
    assert len(made) == 1                              # the fire's turn recorded one host run
    assert row.outcome == outcome
    assert row.run_id == made[0]                       # a failed fire opens too: that is the run to look at
    if outcome == "ok":
        assert [event.ref["run_id"] for event in events] == made


async def test_read_and_search_steps_keep_every_path_they_read(memdb):
    rec = await run_recorder.RunRecorder.start(
        conversation_id="c", spawn_id=None, spawn_name="Arslan", user_message="find it", kind="host")
    matches = [{"path": f"~/Arslan/src/module_{i:02}.py", "line": i, "text": "needle " + "x" * 80}
               for i in range(60)]
    now = datetime.utcnow()
    calls = [("read_file", {"path": "notes/a.md"}, {"ok": True, "path": "~/Arslan/notes/a.md", "content": "y" * 5000}),
             ("search_files", {"query": "needle"},
              {"ok": True, "query": "needle", "matches": matches + [matches[0]], "truncated": True}),
             ("read_file", {"path": "gone.md"}, {"ok": False, "error": "file not found: ~/Arslan/gone.md"}),
             ("web_search", {"query": "q"}, {"ok": True, "results": []})]
    rec._events = [event for tool, _, result in calls for event in (
        (now, {"type": "tool_call", "tool": tool, "args_summary": "{}"}),
        (now, {"type": "tool_result", "tool": tool, "ok": result["ok"], "summary": ""}))]
    with run_trace.collecting():
        for tool, args, result in calls:
            run_trace.record(tool=tool, args=args, result=result, ok=result["ok"],
                             error=result.get("error"), ms=None)
        run_id = await rec.finalize(
            summary_message_id=None, full_output="OUT", model="m", provider="p", tokens_in=1, tokens_out=1,
            tokens_estimated=False, error_kind=None, error_text=None, system_prompt=None, injected_kb=None)

    async with memdb() as db:
        steps = (await db.execute(select(RunStep).where(RunStep.run_id == run_id, RunStep.kind == "tool_call")
                                  .order_by(RunStep.seq))).scalars().all()
    read, search, missing, web = (step.detail for step in steps)
    assert read["paths"] == ["~/Arslan/notes/a.md"]
    assert search["paths"] == [match["path"] for match in matches]      # each file once, in the order found
    assert len(search["result_raw"]) <= RUN_RAW_CAP
    assert matches[-1]["path"] not in search["result_raw"]              # what the raw cut alone would lose
    assert "paths" not in missing                                       # nothing was read
    assert "paths" not in web


async def test_the_four_diagnostics_count_host_runs_and_still_skip_replays(client):
    async with client.db_maker() as db:
        for i in range(3):
            db.add(Run(conversation_id="c", spawn_id=None, spawn_name="Arslan", user_message=f"host {i}",
                       status="scored", task_tokens=10, total_ms=100, kind="host", error_kind="timeout"))
            db.add(Run(conversation_id="c", spawn_id=9, spawn_name="Replay", user_message=f"replay {i}",
                       status="replayed", task_tokens=10, total_ms=100, kind="replay", error_kind="timeout"))
        await db.commit()

    catalog = (await client.get("/api/v1/runs/catalog", params={"range": "all"})).json()
    vitals = (await client.get("/api/v1/runs/vitals", params={"range": "all"})).json()
    timeline = (await client.get("/api/v1/runs/timeline", params={"range": "all"})).json()
    anomalies = (await client.get("/api/v1/runs/anomalies", params={"range": "all"})).json()

    assert catalog["fleet"]["run_count"] == 3
    assert [spawn["spawn_name"] for spawn in catalog["spawns"]] == ["Arslan"]
    assert vitals["total"] == 3
    assert [spawn["spawn_name"] for spawn in timeline["spawns"]] == ["Arslan"]
    assert {(item["kind"], item["spawn_name"]) for item in anomalies} == {("error_rate", "Arslan")}
