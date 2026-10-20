"""K2b (U5 ①): looking for facts and compacting run after the turn, outside its lock.

Before this, both ran inside `handle_user_message`, so the conversation's turn lock was held
through two more model calls after the answer, and a message sent right after the answer waited
("queued"). The post-turn job reads the conversation's switches again when it runs and never
lets a closed window break it."""
import asyncio

import pytest
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


async def test_one_conversations_jobs_run_in_turn(maker, monkeypatch):  # noqa: F811
    """The second turn's job starts once the first turn's job is done, so it sees what that one
    saved (the facts already known, the latest summary)."""
    order, release = [], asyncio.Event()

    async def _facts(conv, msg):
        order.append(f"{msg}:start")
        if msg == "first":
            await release.wait()
        order.append(f"{msg}:end")
        return []

    adapter = _NativeAdapter([_LLMResp(content="one"), _LLMResp(content="two")])
    monkeypatch.setattr(turn_facts, "extract", _facts)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    try:
        await arslan.handle_user_message("c1", "first", _events([]))
        await arslan.handle_user_message("c1", "second", _events([]))
        for _ in range(20):
            await asyncio.sleep(0)
        assert order == ["first:start"]
    finally:
        release.set()
    await settle_after_turn()
    assert order == ["first:start", "first:end", "second:start", "second:end"]


async def test_a_late_fact_names_the_reply_it_belongs_to_on_the_wire(maker, monkeypatch):  # noqa: F811
    """③Hands' K2b review: the window places a fact that arrives after the next message by the reply
    it belongs to. The frame says which, through the same mapping the socket uses (ws/arslan.py
    _to_frame). The phone never receives these frames (①iOS), and stream_end is unchanged."""
    from server.ws import arslan as ws_arslan

    async def _facts(conv, msg):
        return [{"content": "likes short answers", "sensitive": False}]

    monkeypatch.setattr(turn_facts, "extract", _facts)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _NativeAdapter([_LLMResp(content="noted")]))
    events = []
    await arslan.handle_user_message("c1", "I prefer short answers", _events(events))
    await settle_after_turn()
    [end] = [e for e in events if e["type"] == "stream_end"]
    [fact] = [e for e in events if e["type"] in {"fact_saved", "memory_proposed"}]
    wire = ws_arslan._to_frame(fact)
    assert end["message_id"] and wire["reply_message_id"] == end["message_id"]
    assert "reply_message_id" not in ws_arslan._to_frame(end)


@pytest.mark.parametrize("switch", ["no_memory", "no_learning"])
async def test_a_switch_turned_off_while_facts_are_looked_for_saves_nothing(maker, monkeypatch, switch):  # noqa: F811
    """③Hands' K2b review: the fact model's call takes seconds; a switch turned off meanwhile is read
    again right before anything is saved. (Saving itself refuses no_learning too; no_memory only
    this check catches.)"""
    looking, release = asyncio.Event(), asyncio.Event()

    async def _facts(conv, msg):
        looking.set()
        await release.wait()
        return [{"content": "likes short answers", "sensitive": False}]

    monkeypatch.setattr(turn_facts, "extract", _facts)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _NativeAdapter([_LLMResp(content="ok")]))
    events = []
    await arslan.handle_user_message("c1", "I prefer short answers", _events(events))
    await asyncio.wait_for(looking.wait(), 5)
    async with db_session.AsyncSessionLocal() as db:
        await db.merge(ConversationContext(id="c1", **{switch: True}))
        await db.commit()
    release.set()
    await settle_after_turn()
    assert not any(e["type"] in {"fact_saved", "memory_proposed"} for e in events)
    async with db_session.AsyncSessionLocal() as db:
        assert (await db.execute(select(UserFact))).scalars().all() == []


async def test_a_row_landing_after_the_reply_does_not_take_its_place(maker, monkeypatch):  # noqa: F811
    """③Hands' re-review: another row can land in the conversation between the reply and the end of
    the turn (a background job's result). The fact still names the turn's own reply: the id its
    stream_end carried, not the newest row."""
    async def _facts(conv, msg):
        return [{"content": "likes short answers", "sensitive": False}]

    real_budget = memory.turn_budget

    async def _budget_after_a_job_result(conversation_id, **kwargs):
        await memory.add_message(conversation_id, "arslan", "a background job's result")
        return await real_budget(conversation_id, **kwargs)

    monkeypatch.setattr(turn_facts, "extract", _facts)
    monkeypatch.setattr(memory, "turn_budget", _budget_after_a_job_result)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _NativeAdapter([_LLMResp(content="noted")]))
    events = []
    await arslan.handle_user_message("c1", "I prefer short answers", _events(events))
    await settle_after_turn()
    [end] = [e for e in events if e["type"] == "stream_end"]
    [fact] = [e for e in events if e["type"] in {"fact_saved", "memory_proposed"}]
    assert fact["reply_message_id"] == end["message_id"]
