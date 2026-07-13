import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, ArslanMessage, DistilledSession, Feedback


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


async def test_distill_writes_facts_and_marks(maker, monkeypatch):
    from server.services import distill_service
    async def fake_distill_facts(existing, signals):
        return ["用户偏好更简短的输出"]
    monkeypatch.setattr(distill_service, "distill_facts", fake_distill_facts)
    await distill_service.distill_session("c1")
    async with maker() as s:
        spawn = await s.get(Spawn, 3)
        marks = (await s.execute(select(DistilledSession).where(
            DistilledSession.conversation_id == "c1", DistilledSession.spawn_id == 3))).scalars().all()
    facts, marks = spawn.memory_facts, marks
    assert facts == ["用户偏好更简短的输出"] and len(marks) == 1


async def test_distill_includes_per_conversation_feedback(maker, monkeypatch):
    """👍/👎 Feedback rows keyed by the conversation_id must be folded into the distill
    signals (the loop closed in this round: thumbs now feed evolution)."""
    from server.services import distill_service
    captured = {}
    async def fake_distill_facts(existing, signals):
        captured["signals"] = signals
        return ["x"]
    monkeypatch.setattr(distill_service, "distill_facts", fake_distill_facts)
    async with maker() as s:
        s.add(Feedback(spawn_id=3, session_id="c1", user_action="thumbs_up", quality_signal=1))
        s.add(Feedback(spawn_id=3, session_id="c1", user_action="thumbs_down", quality_signal=-1))
        # A row from a DIFFERENT conversation must NOT leak in.
        s.add(Feedback(spawn_id=3, session_id="other-conv", user_action="thumbs_up", quality_signal=1))
        await s.commit()
    await distill_service.distill_session("c1")
    assert "👍" in captured["signals"]
    assert "👎" in captured["signals"]
    # exactly 1 up + 1 down from c1, the other-conv up excluded
    assert "👍×1" in captured["signals"]
    assert "👎×1" in captured["signals"]


async def test_distill_idempotent(maker, monkeypatch):
    from server.services import distill_service
    calls = {"n": 0}
    async def fake_distill_facts(existing, signals):
        calls["n"] += 1
        return ["x"]
    monkeypatch.setattr(distill_service, "distill_facts", fake_distill_facts)
    await distill_service.distill_session("c1")
    await distill_service.distill_session("c1")   # second pass: already marked
    assert calls["n"] == 1   # distilled once


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


async def test_distill_from_signals_merges_into_memory_facts(maker, monkeypatch):
    """Ephemeral sandbox sessions distill from an in-memory signals string (no DB
    transcript), merging into the spawn's memory_facts. No DistilledSession marker."""
    from server.services import distill_service
    captured = {}
    async def fake_distill_facts(existing, signals):
        captured["existing"] = existing
        captured["signals"] = signals
        return ["用户偏好更紧凑的开头"]
    monkeypatch.setattr(distill_service, "distill_facts", fake_distill_facts)

    await distill_service.distill_from_signals(3, "用户消息:\n把开头改紧凑\n\n分身产出:\n紧凑版")
    async with maker() as s:
        facts = (await s.get(Spawn, 3)).memory_facts
    assert facts == ["用户偏好更紧凑的开头"]
    assert "把开头改紧凑" in captured["signals"]


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
