import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, ArslanMessage, DistilledSession


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


async def test_distill_llm_failure_keeps_existing_and_no_marker(maker, monkeypatch):
    """A transient LLM failure (real path: build_adapter raises inside distill_facts) must
    leave memory_facts unchanged AND write NO DistilledSession marker, so it retries."""
    from server.services import distill_service
    async def boom_adapter(*a, **k):
        raise RuntimeError("llm down")
    monkeypatch.setattr(distill_service, "build_adapter", boom_adapter)
    await distill_service.distill_session("c1")   # must not raise
    async with maker() as s:
        facts = (await s.get(Spawn, 3)).memory_facts
        marks = (await s.execute(select(DistilledSession).where(
            DistilledSession.conversation_id == "c1", DistilledSession.spawn_id == 3))).scalars().all()
    assert facts == []          # unchanged
    assert len(marks) == 0      # NOT marked → retryable next session


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
# 整理层#10 段 A2 — discriminated outcomes + visible failure
#
# Before: every failure ended in logger.warning with nothing persisted, and the
# return values conflated outcomes at three levels (distill_session 0 = clean
# no-op = total failure; _distill_one False = 4 different things;
# distill_from_signals -> None could not report anything even in principle).
# The fixture seeds Spawn id=3 and conversation "c1".
# ---------------------------------------------------------------------------


async def _none(existing, signals):
    return None


async def test_one_spawn_exception_does_not_abort_the_others(maker, monkeypatch):
    """Today a raise inside _distill_one aborts the whole loop (no per-spawn try),
    leaving every remaining spawn markerless forever."""
    from server.services import distill_service

    async with maker() as s:
        s.add(Spawn(id=4, name="小强", domain_category="content", system_prompt="sp",
                    memory_facts=[]))
        s.add(ArslanMessage(conversation_id="c1", role="spawn_summary",
                            content="另一个产出", display_content="另一个产出", spawn_id=4))
        await s.commit()

    seen = []
    real = distill_service._distill_one

    async def _boom(cid, sid, **kw):
        seen.append(sid)
        if len(seen) == 1:
            raise RuntimeError("spawn blew up")
        return await real(cid, sid, **kw)

    monkeypatch.setattr(distill_service, "_distill_one", _boom)
    async def _one(existing, signals):
        return ["f"]
    monkeypatch.setattr(distill_service, "distill_facts", _one)

    report = await distill_service.distill_session_detailed("c1")
    assert len(seen) == 2, "the second spawn must still be attempted"
    assert any(o.reason == "exception" for o in report.outcomes)


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

    # seed material under a hermetic id so the guard is what stops it, not empty input
    async with maker() as s:
        s.add(ArslanMessage(conversation_id="evolution-replay", role="spawn_summary",
                            content="synthetic", display_content="synthetic", spawn_id=3))
        await s.commit()

    report = await distill_service.distill_session_detailed("evolution-replay")

    assert report.distilled == 0
    assert writes == [], f"hermetic traffic must write NOTHING, got {writes}"
    async with maker() as s:
        spawn = await s.get(Spawn, 3)
    assert spawn.memory_facts == []


async def _aw(v):
    return v


async def test_both_entry_points_go_through_memory_v2(maker, monkeypatch):
    """0.1.63 C2a-2: the session path and the signals path both reach _distill_v2, which proposes into the
    expert's scope and never reports "learned". With no personal context (learning not bound to a turn) it
    stops before any model call. A path that answered ok=True here would let complete_chat archive a
    transcript nothing was learned from."""
    from server.services import distill_service

    async def no_model(*a, **k):
        raise AssertionError("no model call without a memory context")
    monkeypatch.setattr(distill_service, "build_adapter", no_model)
    one = await distill_service._distill_one("c1", 3)
    signals = await distill_service.distill_from_signals(3, "用户消息:\n把报告写短点", conversation_id="c1")
    assert (one.ok, one.reason) == (False, "learning_disabled")
    assert (signals.ok, signals.reason) == (False, "learning_disabled")
