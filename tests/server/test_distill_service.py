import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, ArslanMessage, DistilledSession, Feedback, UserFact


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


async def test_distill_nested_upflow_persists_without_session_lock(maker, monkeypatch, caplog):
    """Nested-session regression (brain-P1 Task 3): rerouting distill_meta_upflow
    through memory.save_facts introduced session NESTING that didn't exist before —
    _distill_one holds an OUTER session open (uncommitted) while distill_meta_upflow
    opens INNER sessions (list_facts for the prompt context + save_facts for the
    write, each committing on its own). Given this repo's 'database is locked'
    nested-session flake history, drive the REAL production entry (distill_session
    -> _distill_one -> distill_meta_upflow) end-to-end and lock down that:
      (a) the upflow UserFact persisted, carrying mandatory provenance + valid_from,
      (b) no 'database is locked' / distill_meta_upflow failure was logged,
      (c) the per-spawn distill still committed: DistilledSession marker +
          spawn.memory_facts, proving the outer transaction survived the nesting.
    """
    from server.services import distill_service

    async def fake_distill_facts(existing, signals):
        return ["用户偏好更简短的输出"]

    monkeypatch.setattr(distill_service, "distill_facts", fake_distill_facts)

    # Stub ONLY the meta-upflow LLM call (distill_facts is already stubbed, so the
    # sole remaining build_adapter reach is inside distill_meta_upflow).
    class _MetaAdapter:
        async def chat(self, system, user, **kw):
            class _R:
                content = "用户偏口语、忌硬广"
            return _R()

    async def _fake_build_adapter(*a, **k):
        return _MetaAdapter()

    monkeypatch.setattr(distill_service, "build_adapter", _fake_build_adapter)

    import logging
    with caplog.at_level(logging.WARNING):
        n = await distill_service.distill_session("c1")

    assert n == 1  # the one producing spawn was distilled

    # (b) no lock / no swallowed upflow failure — the nested commit went clean
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "database is locked" not in joined
    assert "distill_meta_upflow" not in joined  # its except-branch warning never fired

    async with maker() as s:
        # (a) upflow fact persisted through the nested save_facts, with provenance
        facts = (await s.execute(
            select(UserFact).where(UserFact.source == "upflow"))).scalars().all()
        assert len(facts) == 1
        assert facts[0].content == "用户偏口语、忌硬广"
        assert facts[0].provenance == {"source_kind": "upflow", "spawn_id": 3}
        assert facts[0].valid_from is not None

        # (c) the outer per-spawn transaction also committed
        spawn = await s.get(Spawn, 3)
        assert spawn.memory_facts == ["用户偏好更简短的输出"]
        marks = (await s.execute(select(DistilledSession).where(
            DistilledSession.conversation_id == "c1",
            DistilledSession.spawn_id == 3))).scalars().all()
        assert len(marks) == 1


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


async def test_outcome_reasons_are_discriminated(maker, monkeypatch):
    from server.services import distill_service
    from server.services.distill_service import DistillOutcome

    # spawn gone
    out = await distill_service._distill_one("c1", 99999)
    assert isinstance(out, DistillOutcome)
    assert out.ok is False and out.reason == "no_spawn"

    # nothing to distill: real spawn, conversation with no messages
    out = await distill_service._distill_one("empty-conv", 3)
    assert out.ok is False and out.reason == "nothing_to_distill"

    # llm failure
    monkeypatch.setattr(distill_service, "distill_facts", _none)
    out = await distill_service._distill_one("c1", 3)
    assert out.ok is False and out.reason == "llm_failed"

    # already distilled (the marker written by the llm-failure path? no — write one)
    async with maker() as s:
        s.add(DistilledSession(conversation_id="c1", spawn_id=3))
        await s.commit()
    out = await distill_service._distill_one("c1", 3)
    assert out.ok is False and out.reason == "already_distilled"


async def test_llm_failure_logs_a_visible_distill_failed_event(maker, monkeypatch):
    """The user must be able to SEE that distillation failed — not only a server log."""
    from server.db.models import ConversationEvent
    from server.services import distill_service

    monkeypatch.setattr(distill_service, "distill_facts", _none)
    await distill_service.distill_session("c1")

    async with maker() as s:
        kinds = (await s.execute(
            select(ConversationEvent.kind).where(
                ConversationEvent.conversation_id == "c1"))).scalars().all()
    assert "distill_failed" in kinds, (
        "a failed distillation must leave persisted evidence, not only a log line")


async def test_distill_session_keeps_its_int_contract(maker, monkeypatch):
    """distill_session stays `-> int`: the REST endpoint, the frontend toast
    (App.tsx: res.distilled_spawns > 0) and three existing tests depend on it.
    The richer report is a SEPARATE function."""
    from server.services import distill_service

    async def _one(existing, signals):
        return ["f"]
    monkeypatch.setattr(distill_service, "distill_facts", _one)
    n = await distill_service.distill_session("c1")
    assert isinstance(n, int) and n == 1


async def test_detailed_report_exposes_per_spawn_failures(maker, monkeypatch):
    from server.services import distill_service

    monkeypatch.setattr(distill_service, "distill_facts", _none)
    report = await distill_service.distill_session_detailed("c1")
    assert report.distilled == 0
    assert [o.reason for o in report.outcomes] == ["llm_failed"]


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
