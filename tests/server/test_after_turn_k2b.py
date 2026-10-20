"""K2b (U5 ①): looking for facts and compacting run after the turn, outside its lock.

Before this, both ran inside `handle_user_message`, so the conversation's turn lock was held
through two more model calls after the answer, and a message sent right after the answer waited
("queued"). The post-turn job reads the conversation's switches again when it runs and never
lets a closed window break it."""
import asyncio

from sqlalchemy import select

import server.db.session as db_session
from server.db.companion_models import ConversationContext
from server.db.models import UserFact
from server.orchestrator import arslan, memory, tool_loop
from server.services import turn_facts
from tests.server.test_arslan_loop import _events, _LLMResp, _NativeAdapter, maker, settle_after_turn  # noqa: F401


def _chunks(events):
    return "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")


async def test_the_turn_ends_before_its_facts_are_looked_for(maker, monkeypatch):  # noqa: F811
    looking, release = asyncio.Event(), asyncio.Event()

    async def _facts(conv, msg):
        if msg == "I prefer short answers":
            looking.set()
            await release.wait()
            return [{"content": "likes short answers", "sensitive": False}]
        return []

    adapter = _NativeAdapter([_LLMResp(content="noted"), _LLMResp(content="second answer")])
    monkeypatch.setattr(turn_facts, "extract", _facts)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    first, second = [], []
    try:
        await asyncio.wait_for(arslan.handle_user_message("c1", "I prefer short answers", _events(first)), 5)
        await asyncio.wait_for(looking.wait(), 5)          # the fact step is running, the turn is over
        assert not any(e["type"] == "fact_saved" for e in first)
        await asyncio.wait_for(arslan.handle_user_message("c1", "and the weather?", _events(second)), 5)
        assert _chunks(second) == "second answer"          # answered while the first turn's facts wait
    finally:
        release.set()
    await settle_after_turn()
    assert any(e["type"] == "fact_saved" and "short answers" in e["content"] for e in first)


async def test_the_job_reads_the_conversation_switches_again(maker, monkeypatch):  # noqa: F811
    """Learning switched off while the answer ran: the turn's own context still had it on, the
    job looks again and saves nothing."""
    called = []

    async def _facts(conv, msg):
        called.append(msg)
        return [{"content": "likes short answers", "sensitive": False}]

    class _SwitchOff(_NativeAdapter):
        async def chat(self, *a, **k):
            async with db_session.AsyncSessionLocal() as db:
                await db.merge(ConversationContext(id="c1", no_learning=True))
                await db.commit()
            return await super().chat(*a, **k)

    monkeypatch.setattr(turn_facts, "extract", _facts)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _SwitchOff([_LLMResp(content="ok")]))
    events = []
    await arslan.handle_user_message("c1", "I prefer short answers", _events(events))
    await settle_after_turn()
    assert called == []
    assert not any(e["type"] == "fact_saved" for e in events)
    async with db_session.AsyncSessionLocal() as db:
        assert (await db.execute(select(UserFact))).scalars().all() == []


async def test_a_closed_window_never_stops_the_job(maker, monkeypatch):  # noqa: F811
    """The job's frames arrive after stream_end; a sink that fails then is ignored and the job
    goes on to compaction."""
    compacted = []

    async def _facts(conv, msg):
        return [{"content": "likes short answers", "sensitive": False}]

    async def _compact(conversation_id, *, budget=None):
        compacted.append(conversation_id)

    def _closed_after_the_answer(seen):
        def emit(ev):
            if ev["type"] in {"fact_saved", "memory_proposed"}:
                raise RuntimeError("socket closed")
            seen.append(ev)
        return emit

    monkeypatch.setattr(turn_facts, "extract", _facts)
    monkeypatch.setattr(memory, "maybe_compact", _compact)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _NativeAdapter([_LLMResp(content="ok")]))
    events = []
    await arslan.handle_user_message("c1", "I prefer short answers", _closed_after_the_answer(events))
    outcomes = await settle_after_turn()
    assert not [o for o in outcomes if isinstance(o, BaseException)]
    assert compacted == ["c1"]
    assert any(e["type"] == "stream_end" for e in events)
