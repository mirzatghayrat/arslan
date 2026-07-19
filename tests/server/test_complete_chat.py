import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ChatMessage, Spawn


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'cl.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with m() as s:
        s.add(Spawn(id=1, name="小美", domain_category="content", system_prompt="sp", memory_facts=[]))
        s.add(ChatMessage(spawn_id=1, role="user", content="把开头改紧凑"))
        s.add(ChatMessage(spawn_id=1, role="assistant", content="好的,改紧凑版"))
        await s.commit()
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def test_complete_chat_distills_then_archives(maker, monkeypatch):
    from server.services import chat_lifecycle, distill_service
    captured = {}
    async def fake_distill(spawn_id, signals, **kw):
        captured["spawn_id"] = spawn_id
        captured["signals"] = signals
        return distill_service.DistillOutcome(ok=True, spawn_id=spawn_id)
    monkeypatch.setattr(distill_service, "distill_from_signals", fake_distill)

    n, _ok = await chat_lifecycle.complete_chat(1)
    async with maker() as s:
        active = (await s.execute(select(ChatMessage).where(
            ChatMessage.spawn_id == 1, ChatMessage.archived == False))).scalars().all()  # noqa: E712
        archived = (await s.execute(select(ChatMessage).where(
            ChatMessage.spawn_id == 1, ChatMessage.archived == True))).scalars().all()  # noqa: E712
    active, archived = len(active), len(archived)
    assert captured["spawn_id"] == 1
    assert "把开头改紧凑" in captured["signals"]
    assert n == 2 and active == 0 and archived == 2


async def test_complete_chat_empty_is_noop(maker, monkeypatch):
    from server.services import chat_lifecycle, distill_service
    called = {"n": 0}
    async def fake_distill(spawn_id, signals, **kw):
        called["n"] += 1
        return distill_service.DistillOutcome(ok=True, spawn_id=spawn_id)
    monkeypatch.setattr(distill_service, "distill_from_signals", fake_distill)
    # archive everything first, then completing again should distill nothing
    await chat_lifecycle.complete_chat(1)
    second, _ok2 = await chat_lifecycle.complete_chat(1)
    assert second == 0
    assert called["n"] == 1  # only the first (non-empty) completion distilled


# ---------------------------------------------------------------------------
# 整理层#10 段 A3 — a failed distillation must NOT archive the source messages
#
# Before: complete_chat archived unconditionally, so a silent LLM failure moved the
# transcript out of the active window with NOTHING learned from it — real,
# unrecoverable data loss, not merely an invisibility problem.
# ---------------------------------------------------------------------------


async def test_failed_distill_does_not_archive_and_is_visible(maker, monkeypatch):
    from server.db.models import ConversationEvent
    from server.services import chat_lifecycle, distill_service

    # Stub the LLM, NOT distill_from_signals — so the real production wiring
    # (outcome -> failure event -> complete_chat's archive decision) is exercised.
    async def failing_llm(existing, signals):
        return None
    monkeypatch.setattr(distill_service, "distill_facts", failing_llm)

    n, _ok = await chat_lifecycle.complete_chat(1)

    async with maker() as s:
        active = (await s.execute(select(ChatMessage).where(
            ChatMessage.spawn_id == 1, ChatMessage.archived == False))).scalars().all()  # noqa: E712
        archived = (await s.execute(select(ChatMessage).where(
            ChatMessage.spawn_id == 1, ChatMessage.archived == True))).scalars().all()  # noqa: E712
        kinds = (await s.execute(select(ConversationEvent.kind))).scalars().all()

    assert len(active) == 2, "a failed distill must leave the transcript ACTIVE (retryable)"
    assert len(archived) == 0
    assert n == 0, "nothing was archived, so report 0 honestly"
    assert "distill_failed" in kinds, "the failure must be visible, not only logged"


async def test_successful_distill_still_archives(maker, monkeypatch):
    """The A3 change must not regress the happy path."""
    from server.services import chat_lifecycle, distill_service

    async def ok_distill(spawn_id, signals, **kw):
        return distill_service.DistillOutcome(ok=True, spawn_id=spawn_id)
    monkeypatch.setattr(distill_service, "distill_from_signals", ok_distill)

    n, _ok = await chat_lifecycle.complete_chat(1)
    async with maker() as s:
        archived = (await s.execute(select(ChatMessage).where(
            ChatMessage.spawn_id == 1, ChatMessage.archived == True))).scalars().all()  # noqa: E712
    assert n == 2 and len(archived) == 2
