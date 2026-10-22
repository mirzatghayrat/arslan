import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, ArslanMessage


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'ds.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with m() as s:
        s.add(Spawn(id=3, name="小美", domain_category="content", system_prompt="sp", memory_facts=[]))
        s.add(ArslanMessage(conversation_id="c1", role="user", content="把报告写短点"))
        s.add(ArslanMessage(conversation_id="c1", role="spawn_summary", content="短报告", display_content="短报告", spawn_id=3))
        await s.commit()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def test_distill_from_signals_noop_on_llm_failure(maker, monkeypatch):
    """distill_facts returning None (LLM failure) leaves memory_facts untouched."""
    from server.services import distill_service
    async def fake_distill_facts(existing, signals):
        return None
    monkeypatch.setattr(distill_service, "distill_facts", fake_distill_facts)
    await distill_service.distill_from_signals(3, "signals")
    async with maker() as s:
        facts = (await s.get(Spawn, 3)).memory_facts
    assert facts == []


# ---------------------------------------------------------------------------
# 整理层#10 段 A4 — sealing guard, upflow provenance, usage accounting
# ---------------------------------------------------------------------------


async def test_hermetic_conversation_writes_nothing_at_all(maker, monkeypatch):
    """Synthetic eval traffic must never be learned from. This was previously safe only
    by ACCIDENT (replay never persists ArslanMessage rows, so the candidate query came
    back empty) — an accident any new caller could break. Assert on the whole WRITE SET,
    not one member of it."""
    from server.orchestrator import memory
    from server.services import distill_service, memory_temporal

    writes = []
    monkeypatch.setattr(memory, "save_facts",
                        lambda *a, **k: writes.append("save_facts") or _aw([]))
    monkeypatch.setattr(memory_temporal, "execute_supersede",
                        lambda *a, **k: writes.append("supersede") or _aw(None))

    async def _facts(existing, signals):
        writes.append("llm")
        return ["never"]
    monkeypatch.setattr(distill_service, "distill_facts", _facts)

    # Real signals, under a hermetic id, inside a context that WOULD let the expert learn
    # (its own scope, cloud memory allowed): so the guard is what stops it, not empty input
    # or a missing context.
    from server.services import personal_context as pc
    ctx = pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="evolution-replay",
                               expert_id="3", cloud_memory_allowed=True)
    with pc.bind(ctx):
        outcome = await distill_service.distill_from_signals(3, "synthetic",
                                                             conversation_id="evolution-replay")

    assert outcome.ok is False
    assert writes == [], f"hermetic traffic must write NOTHING, got {writes}"
    async with maker() as s:
        spawn = await s.get(Spawn, 3)
    assert spawn.memory_facts == []


async def _aw(v):
    return v


async def test_the_signals_path_goes_through_memory_v2(maker, monkeypatch):
    """0.1.63 C2a-2: the signals path reaches _distill_v2, which proposes into the expert's scope and never
    reports "learned". With no personal context (learning not bound to a turn) it stops before any model
    call. A path that answered ok=True here would let complete_chat archive a transcript nothing was learned
    from. (The session path went with C8-4.)"""
    from server.services import distill_service

    async def no_model(*a, **k):
        raise AssertionError("no model call without a memory context")
    monkeypatch.setattr(distill_service, "build_adapter", no_model)
    signals = await distill_service.distill_from_signals(3, "用户消息:\n把报告写短点", conversation_id="c1")
    assert (signals.ok, signals.reason) == (False, "learning_disabled")
