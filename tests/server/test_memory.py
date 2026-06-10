"""Working-memory assembly, compaction trigger, and long-term facts."""
import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import ArslanMessage, ArslanSummary, Base


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'mem.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_create)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def test_estimate_tokens():
    from server.orchestrator.memory import estimate_tokens

    assert estimate_tokens("a" * 400) == 100  # 4 chars/token


@pytest.mark.asyncio
async def test_add_and_assemble_working_context(maker):
    from server.orchestrator import memory

    await memory.add_message("main", "user", "hello")
    await memory.add_message("main", "arslan", "hi there")
    ctx = await memory.assemble_working_context("main")
    # Returns recent turns (context copy) as a list of {role, content} for the LLM.
    assert ctx["history"][-1]["content"] == "hi there"
    assert ctx["summary"] == ""  # no compaction yet


@pytest.mark.asyncio
async def test_facts_roundtrip_and_injection(maker):
    from server.orchestrator import memory

    await memory.save_facts([{"content": "prefers metric units", "sensitive": False}])
    facts = await memory.list_facts()
    assert facts[0].content == "prefers metric units"
    text = await memory.facts_text()
    assert "metric units" in text


@pytest.mark.asyncio
async def test_compaction_folds_old_messages(maker, monkeypatch):
    from server.orchestrator import memory

    # Tiny budget so two messages trigger compaction.
    monkeypatch.setenv("ARSLAN_WORKING_TOKEN_BUDGET", "5")

    # Stub the LLM compaction call to a deterministic summary.
    async def _fake_summarize(_adapter, _text):
        return "SUMMARY"

    monkeypatch.setattr(memory, "_summarize", _fake_summarize)

    class _FakeAdapter:  # not used because _summarize is stubbed
        pass

    monkeypatch.setattr(memory, "_get_adapter", lambda: _FakeAdapter())

    await memory.add_message("main", "user", "a long-ish first message here")
    await memory.add_message("main", "user", "second message also fairly long")
    await memory.maybe_compact("main")

    async with db_session.AsyncSessionLocal() as s:
        summaries = (await s.execute(select(ArslanSummary))).scalars().all()
    assert len(summaries) == 1
    assert summaries[0].summary == "SUMMARY"
    # After compaction, assembled context carries the summary.
    ctx = await memory.assemble_working_context("main")
    assert ctx["summary"] == "SUMMARY"


@pytest.mark.asyncio
async def test_user_turn_count(maker):
    from server.orchestrator import memory

    # Seed 3 user + 2 arslan rows in "clock-conv"
    async with maker() as s:
        for content in ("hello", "second", "third"):
            s.add(ArslanMessage(conversation_id="clock-conv", role="user", content=content))
        for content in ("reply one", "reply two"):
            s.add(ArslanMessage(conversation_id="clock-conv", role="arslan", content=content))
        await s.commit()

    assert await memory.user_turn_count("clock-conv") == 3
    # Unknown conversation returns 0
    assert await memory.user_turn_count("no-such-conv") == 0


def test_estimate_tokens_cjk():
    from server.orchestrator.memory import estimate_tokens

    # 100 Chinese chars ~ 100 tokens (not 25 as a naive /4 would give)
    assert estimate_tokens("中" * 100) == 100
    # mixed: 10 CJK + 40 ascii -> 10 + 10
    assert estimate_tokens("中" * 10 + "a" * 40) == 20


@pytest.mark.asyncio
async def test_compaction_caps_summary(maker, monkeypatch):
    from server.orchestrator import memory

    monkeypatch.setenv("ARSLAN_WORKING_TOKEN_BUDGET", "5")

    calls = []

    async def _fake_summarize(_adapter, _text):
        calls.append(_text)
        # first pass returns an over-cap summary; the compress pass returns a short one
        return "X" * 200 if len(calls) == 1 else "short"

    monkeypatch.setattr(memory, "_summarize", _fake_summarize)
    monkeypatch.setattr(memory, "_get_adapter", lambda: object())

    await memory.add_message("main", "user", "aaaa aaaa aaaa aaaa")
    await memory.add_message("main", "user", "bbbb bbbb bbbb bbbb")
    await memory.maybe_compact("main")

    # the first summary exceeded the cap, so it was compressed a second time
    assert len(calls) == 2
    ctx = await memory.assemble_working_context("main")
    assert ctx["summary"] == "short"
