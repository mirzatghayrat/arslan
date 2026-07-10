"""E1: shared step-evidence builder (trace_evidence.build_evidence).

Renders a Run's RunStep rows as one compact line per step for judge prompts:
    [kind] tool=<name> args=<args_summary> → ok|err <result summary>
Per-step ≤200 chars, total ≤2000 chars (…[truncated] when cut), empty steps → ""
(no fabricated evidence), and it must never raise on malformed step detail.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, Run, RunStep
from server.services.trace_evidence import STEP_CAP, TOTAL_CAP, build_evidence


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def _seed_run(Session, steps: list[dict]) -> int:
    async with Session() as db:
        run = Run(conversation_id="c1", spawn_name="Mermer", user_message="查天气",
                  status="recorded", task_tokens=0)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        for i, s in enumerate(steps):
            db.add(RunStep(run_id=run.id, seq=i, **s))
        await db.commit()
        return run.id


async def test_format_one_line_per_step(memdb):
    run_id = await _seed_run(memdb, [
        {"kind": "route", "ref": {"spawn_name": "Mermer"}, "detail": {}},
        {"kind": "tool_call", "ref": {"tool": "web_search", "ok": True},
         "detail": {"args_summary": "q=上海天气", "summary": "3 results"}},
        {"kind": "tool_call", "ref": {"tool": "run_python", "ok": False},
         "detail": {"args_summary": "print(1)", "summary": "", "error": "boom"}},
        {"kind": "dispatch", "ref": {"spawn_name": "Mermer"},
         "detail": {"output_preview": "今天上海晴"}},
    ])
    ev = await build_evidence(run_id)
    lines = ev.split("\n")
    assert len(lines) == 4
    assert lines[0].startswith("[route]")
    assert lines[1] == "[tool_call] tool=web_search args=q=上海天气 → ok 3 results"
    assert "[tool_call] tool=run_python args=print(1) → err" in lines[2]
    assert "boom" in lines[2]
    assert lines[3].startswith("[dispatch]")
    assert "今天上海晴" in lines[3]


async def test_per_step_truncation(memdb):
    long_summary = "长" * 500
    run_id = await _seed_run(memdb, [
        {"kind": "tool_call", "ref": {"tool": "web_search", "ok": True},
         "detail": {"args_summary": "q", "summary": long_summary}},
    ])
    ev = await build_evidence(run_id)
    assert len(ev) <= STEP_CAP
    assert "…[truncated]" in ev


async def test_total_truncation(memdb):
    steps = [
        {"kind": "tool_call", "ref": {"tool": f"tool_{i}", "ok": True},
         "detail": {"args_summary": "a" * 100, "summary": "b" * 80}}
        for i in range(40)
    ]
    run_id = await _seed_run(memdb, steps)
    ev = await build_evidence(run_id)
    assert len(ev) <= TOTAL_CAP
    assert ev.endswith("…[truncated]")
    # the first step must still be present in full
    assert "tool=tool_0" in ev


async def test_empty_steps_yield_empty_string(memdb):
    run_id = await _seed_run(memdb, [])
    assert await build_evidence(run_id) == ""


async def test_missing_run_yields_empty_string(memdb):
    assert await build_evidence(999999) == ""


async def test_malformed_detail_never_raises(memdb):
    run_id = await _seed_run(memdb, [
        # ref/detail explicitly None
        {"kind": "tool_call", "ref": None, "detail": None},
        # non-dict JSON payloads
        {"kind": "tool_call", "ref": "not-a-dict", "detail": [1, 2, 3]},
        # weird value types inside otherwise-valid dicts
        {"kind": "tool_call", "ref": {"tool": {"nested": True}, "ok": "yes"},
         "detail": {"args_summary": {"x": 1}, "summary": 42}},
        # one good step so we can assert output still renders
        {"kind": "tool_call", "ref": {"tool": "web_search", "ok": True},
         "detail": {"args_summary": "q", "summary": "fine"}},
    ])
    ev = await build_evidence(run_id)  # must not raise
    assert "tool=web_search" in ev
