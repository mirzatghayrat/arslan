"""brain-P2 Task 6: weak-model acceptance (memory still forms without the model
ever calling remember) + dual-track provenance (agentic vs Tier0/distill writes,
in the SAME table, are distinguishable by querying).

Weak-model acceptance (task-book requirement): host tool exposure and spawn
equipment are entirely orthogonal to the pre-existing Tier0 auto-memory paths —
router-extraction (arslan.py:554/memory.save_facts) and distill
(learning_service.distill_from_event / distill_service.distill_meta_upflow)
never call recall/remember at all; they are plain backend functions triggered
by conversation flow / session-end, not model tool-calling. This test proves
that concretely: with "recall"/"remember" REMOVED from the host's tool list
(simulating a provider/config where second_brain was never wired) and a spawn
carrying no second_brain SpawnCapability (never equipped), a weak model that
never emits a tool call still gets its facts and learnings auto-formed, and not
one written row carries agentic provenance.

Dual-track provenance (Task 4 already asserts the agentic values in isolation —
tests/server/test_memory_scope_isolation.py::test_dual_track_provenance_distinguishable_from_distill.
This file EXTENDS that coverage: it writes one agentic row AND one live Tier0
row into the SAME table via each table's real production write path, then
queries both back and asserts their provenance actually differs — not just that
the agentic value equals the expected literal.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Learning, Spawn, UserFact
from server.orchestrator.tool_caller import ToolCaller, reset_caller, set_caller
from server.registry.memory_executors import RememberExecutor


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'dual.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest_asyncio.fixture(autouse=True)
async def _no_caller_leak():
    from server.orchestrator import tool_caller
    assert tool_caller.current_caller() is None
    yield
    assert tool_caller.current_caller() is None


async def _remember(args: dict, caller: ToolCaller) -> dict:
    token = set_caller(caller)
    try:
        return await RememberExecutor().execute(args)
    finally:
        reset_caller(token)


async def _seed_spawn(maker, spawn_id: int, name: str) -> None:
    async with maker() as db:
        db.add(Spawn(id=spawn_id, name=name, domain_category="d", system_prompt="p",
                     memory_facts=[]))
        await db.commit()


# ---------------------------------------------------------------------------
# weak-model acceptance: Tier0 still auto-forms memory with agentic tools
# entirely absent — and zero agentic pollution results.
# ---------------------------------------------------------------------------

async def test_weak_model_tier0_forms_memory_without_agentic_tools(maker, monkeypatch):
    from server.orchestrator import arslan, router, tool_loop
    from server.registry import executors as executors_module
    from tests.server.conftest import MockAdapter

    # "host not wired": recall/remember absent from EXECUTORS — arslan._arslan_tools()'s
    # `if k in EXECUTORS` filter then drops both keys from the host's tool list.
    trimmed = {k: v for k, v in executors_module.EXECUTORS.items()
              if k not in ("recall", "remember")}
    monkeypatch.setattr(executors_module, "EXECUTORS", trimmed)
    tools = await arslan._arslan_tools()
    assert {"recall", "remember"}.isdisjoint({t["key"] for t in tools})

    # "spawn not equipped": a fresh spawn with no SpawnCapability(second_brain) row —
    # wired_tools_for_spawn() naturally never includes recall/remember (Layer-3 gate;
    # they are not in _UNIVERSAL_SAFE_TOOLS, so equipment is opt-in, never ambient).
    await _seed_spawn(maker, 55, "分身55")
    from server.registry.service import wired_tools_for_spawn
    spawn_wired = await wired_tools_for_spawn(55, current_turn=1)
    assert {"recall", "remember"}.isdisjoint({t["key"] for t in spawn_wired})

    # Router-extraction Tier0 write (arslan.py:554/memory.save_facts), exercised
    # end-to-end via the REAL production entrypoint — a "weak model" that never
    # emits a tool_calls list (MockAdapter's default) still gets this write,
    # because save_facts is called directly off router.route()'s new_facts, not
    # via any tool call.
    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="answer",
            new_facts=[{"content": "weak-model 场景:用户偏好简体中文", "sensitive": False}],
        )

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    adapter = MockAdapter(stream_chunks=["ok"], chat_content="ok")  # tool_calls=[] by default
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    events: list = []
    await arslan.handle_user_message("conv-weak-model", "你好", events.append)
    assert adapter.chat_calls or adapter.chat_stream_calls   # the weak model DID run
    assert not adapter.tool_calls                            # ...and never called any tool

    async with maker() as db:
        fact_rows = (await db.execute(select(UserFact))).scalars().all()
    assert len(fact_rows) == 1
    assert fact_rows[0].provenance["source_kind"] == "router"   # Tier0, not agentic
    assert "actor" not in fact_rows[0].provenance                # agentic-only key absent

    # Distill Tier0 write (learning_service.distill_from_event), also exercised via
    # its REAL production entrypoint — structurally independent of tool wiring: it
    # is a session-end background function, never a model tool call.
    from server.services import learning_service

    class _Resp:
        content = "weak-model 场景下 distill 也照常出结果"

    class _StubAdapter:
        async def chat(self, system, user, **kw):
            return _Resp()

    async def _fake_build_adapter(*a, **kw):
        return _StubAdapter()

    monkeypatch.setattr(learning_service, "build_adapter", _fake_build_adapter)
    new_id = await learning_service.distill_from_event(
        conversation_id="conv-weak-model", spawn_id=55, spawn_name="分身55",
        signal_text="真实会话信号:用户请分身总结报告")
    assert new_id > 0

    async with maker() as db:
        fact_rows = (await db.execute(select(UserFact))).scalars().all()
        learning_rows = (await db.execute(select(Learning))).scalars().all()

    assert len(learning_rows) == 1
    assert learning_rows[0].source_kind == "distill"             # Tier0, not agentic
    assert "actor" not in (learning_rows[0].source_ref or {})     # agentic-only key absent

    # Zero agentic pollution across BOTH tables — recall/remember were never even
    # offered, so nothing in either table can carry agentic provenance.
    for f in fact_rows:
        assert f.provenance.get("source_kind") != "agentic"
        assert "actor" not in (f.provenance or {})
    for r in learning_rows:
        assert r.source_kind != "agentic"
        assert "actor" not in (r.source_ref or {})


# ---------------------------------------------------------------------------
# dual-track provenance: agentic and Tier0/distill writes in the SAME table are
# distinguishable by querying — both the fact (JSON provenance.actor) and the
# learning (source_ref.actor) mechanisms.
# ---------------------------------------------------------------------------

async def test_dual_track_fact_provenance_distinguishable(maker):
    """user_facts: one agentic write (RememberExecutor, provenance.actor) and one
    Tier0 write (memory.save_facts, source_kind='upflow' — distill's real
    call-site shape, distill_service.py:95) land in the SAME table. Querying
    each back and comparing proves the two tracks are distinguishable from the
    row alone, not merely by construction."""
    from server.orchestrator import memory

    agentic_out = await _remember(
        {"kind": "fact", "action": "append", "content": "轨道一:agentic host 直写"},
        ToolCaller(actor="host", spawn_id=None, conversation_id="c-agentic"))
    assert agentic_out["ok"] is True

    tier0_created = await memory.save_facts(
        [{"content": "轨道二:Tier0 upflow 上浮"}],
        provenance={"source_kind": "upflow", "spawn_id": 99})
    assert tier0_created

    async with maker() as db:
        agentic_row = await db.get(UserFact, agentic_out["id"])
        tier0_row = await db.get(UserFact, tier0_created[0].id)

    assert agentic_row.provenance["source_kind"] == "agentic"
    assert agentic_row.provenance["actor"] == "host"
    assert tier0_row.provenance["source_kind"] == "upflow"
    assert "actor" not in tier0_row.provenance                  # distill never sets "actor"
    assert agentic_row.provenance != tier0_row.provenance       # distinguishable, queried live


async def test_dual_track_learning_provenance_distinguishable(maker, monkeypatch):
    """learnings: one agentic write (RememberExecutor, source_ref.actor) and one
    Tier0 write (learning_service.distill_from_event, source_kind='distill' —
    the real session-distill call-site) land in the SAME table (same well,
    spawn_id=61). Querying each back proves the two tracks are distinguishable
    via source_kind/source_ref alone."""
    await _seed_spawn(maker, 61, "分身61")

    agentic_out = await _remember(
        {"kind": "learning", "action": "append", "content": "轨道一:agentic spawn 心得"},
        ToolCaller(actor="spawn", spawn_id=61, conversation_id="c-agentic"))
    assert agentic_out["ok"] is True

    from server.services import learning_service

    class _Resp:
        content = "轨道二:Tier0 distill 心得"

    class _StubAdapter:
        async def chat(self, system, user, **kw):
            return _Resp()

    async def _fake_build_adapter(*a, **kw):
        return _StubAdapter()

    monkeypatch.setattr(learning_service, "build_adapter", _fake_build_adapter)
    tier0_id = await learning_service.distill_from_event(
        conversation_id="c-tier0", spawn_id=61, spawn_name="分身61",
        signal_text="真实会话信号")
    assert tier0_id > 0

    async with maker() as db:
        agentic_row = await db.get(Learning, agentic_out["id"])
        tier0_row = await db.get(Learning, tier0_id)

    assert agentic_row.source_kind == "agentic"
    assert agentic_row.source_ref["actor"] == "spawn:61"
    assert tier0_row.source_kind == "distill"
    assert "actor" not in tier0_row.source_ref                  # distill never sets "actor"
    assert agentic_row.source_kind != tier0_row.source_kind     # distinguishable, queried live
