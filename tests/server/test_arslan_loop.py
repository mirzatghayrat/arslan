"""Orchestration loop: answer / route / suggest_create + fact saving."""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import ArslanMessage, Base, Spawn, UserFact


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'loop.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with m() as s:
        s.add(
            Spawn(
                id=7,
                name="beauty-guru",
                domain_category="content-creator",
                capabilities=["content-generation"],
                system_prompt="You are a beauty expert.",
            )
        )
        await s.commit()

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def _events(collector):
    return lambda ev: collector.append(ev)


async def _fake_noop(): pass
async def _fake_list(): return []


async def _force_named(_msg, _sid):
    # Boundary component 2 sends UNNAMED (inferred) routes to doer-first (answer). These route
    # tests exercise the routing/dispatch MECHANICS, so force the explicit-naming path; naming
    # detection itself is covered in test_boundary_doer_first.
    return True


async def _fake_curate(need):
    """Hermetic stub for equipment_service.curate (no outbound LLM call)."""
    return {"toolsets": [], "skills": [], "mcps": [], "gaps": []}


async def _ready_slots(history_text):
    """Hermetic stub for staffing_gather.extract_slots returning a READY slot set —
    drives the spine's ready path (match-and-propose / suggest_create card)."""
    return {"domain": "x.y", "capability": "do-x", "first_task": "run x", "recurrence": True}


class _LLMResp:
    """Native LLMResponse stub: separate content (prose) + tool_calls (structured)."""
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def _tc(name, args):
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": args}}


class _NativeAdapter:
    """chat()-based stub (Arslan's answer path uses run_native → a.chat, not chat_stream).
    Returns queued LLMResponses in order; optionally records the system/user it saw."""
    def __init__(self, replies, capture=None):
        self._it = iter(replies)
        self.capture = capture

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        if self.capture is not None:
            self.capture["system"] = system
            self.capture["user"] = user
        return next(self._it)


@pytest.mark.asyncio
async def test_answer_path_streams_and_persists(maker, monkeypatch):
    from server.orchestrator import arslan
    from server.services import turn_facts

    async def _facts(conv, msg):
        return [{"content": "likes brevity", "sensitive": False}]

    monkeypatch.setattr(turn_facts, "extract", _facts)

    captured = {}

    from server.orchestrator import tool_loop

    monkeypatch.setattr(tool_loop, "_get_adapter",
                        lambda: _NativeAdapter([_LLMResp(content="Hi there")], capture=captured))

    events = []
    await arslan.handle_user_message("main", "hello", _events(events))

    types = [e["type"] for e in events]
    assert "stream_start" in types and "stream_end" in types
    assert any(e["type"] == "fact_saved" and "brevity" in e["content"] for e in events)
    # plain answer must NOT carry the clarify addendum (distinguishes it from clarify)
    assert "clarifying questions" not in captured["system"]

    async with db_session.AsyncSessionLocal() as s:
        ams = (await s.execute(select(ArslanMessage).order_by(ArslanMessage.id))).scalars().all()
        facts = (await s.execute(select(UserFact))).scalars().all()
    assert [a.role for a in ams] == ["user", "arslan"]
    assert ams[1].content == "Hi there"
    assert len(facts) == 1


@pytest.mark.asyncio
async def test_arslan_answer_calls_web_tool(maker, monkeypatch):
    # Arslan's answer path runs tool_loop; the model calls web_search, then streams a final answer.
    from server.orchestrator import arslan, tool_loop
    from server.registry import executors



    adapter = _NativeAdapter([
        _LLMResp(content="", tool_calls=[_tc("web_search", {"query": "today"})]),
        _LLMResp(content="Fresh info: X happened."),
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    class _Stub:
        async def execute(self, args):
            return {"ok": True, "results": [{"title": "t", "url": "u"}]}

    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Stub())

    events = []
    await arslan.handle_user_message("main", "what happened today?", _events(events))
    types = [e["type"] for e in events]
    assert "tool_call" in types and "tool_result" in types
    streamed = "".join(e["content"] for e in events if e["type"] == "stream_chunk")
    assert "Fresh info: X happened." in streamed
    assert "stream_end" in types


@pytest.mark.asyncio
async def test_arslan_answer_plain_no_tool(maker, monkeypatch):
    from server.orchestrator import arslan, tool_loop



    monkeypatch.setattr(tool_loop, "_get_adapter",
                        lambda: _NativeAdapter([_LLMResp(content="just a friendly reply")]))

    events = []
    await arslan.handle_user_message("main", "哈喽", _events(events))
    types = [e["type"] for e in events]
    assert "tool_call" not in types
    streamed = "".join(e["content"] for e in events if e["type"] == "stream_chunk")
    assert "just a friendly reply" in streamed








@pytest.mark.asyncio
async def test_dispatch_to_missing_spawn_emits_error_not_crash(maker, monkeypatch):
    """Defense-in-depth at the dispatch chokepoint: if a spawn_id reaches
    _dispatch_spawn but no longer exists (e.g. deleted mid-conversation, or a stale
    id from any non-route entry point), dispatch must emit a recoverable error frame
    and return — NEVER call RunRecorder.start() with a dangling FK (IntegrityError)."""
    from server.orchestrator import arslan
    from server.services import run_recorder
    from server.db.models import Run

    # Guard against a regression where the recorder is reached anyway.
    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda rid: None)

    events = []
    # spawn 999 does not exist (only id=7 is seeded)
    await arslan._dispatch_spawn("main", 999, "do x", _events(events), user_message="do x")

    types = [e["type"] for e in events]
    assert "error" in types, f"expected an error frame, got {types}"
    err = next(e for e in events if e["type"] == "error")
    assert err.get("recoverable") is True
    # crucially: no routing/stream frames and no Run row was written
    assert "routing" not in types
    async with db_session.AsyncSessionLocal() as s:
        runs = (await s.execute(select(Run))).scalars().all()
    assert runs == []












@pytest.mark.asyncio
async def test_arslan_answer_prompt_has_web_tool_guidance(maker, monkeypatch):
    # Regression: Arslan's answer-path system prompt must bind "unsure about something
    # current" → "search" (not → ask/fabricate), or the model narrates instead of calling
    # the tool. Asserts the guidance + the reconciliation with anti-fabrication are present.
    from server.orchestrator import arslan, tool_loop



    captured = {}

    monkeypatch.setattr(tool_loop, "_get_adapter",
                        lambda: _NativeAdapter([_LLMResp(content="ok")], capture=captured))

    await arslan.handle_user_message("main", "今天的新闻", _events([]))
    sys = captured["system"]
    assert "web_search" in sys
    assert "MUST" in sys                       # "you MUST actually CALL web_search"
    assert "INSTEAD of fabricating" in sys     # reconciled with anti-fabrication
    assert "ACT, don't narrate" in sys         # forbid ending a turn with "I'll search"
    # Prompt-cache reorder (spec 2026-07-13): the timestamp is now DATE-level (the minute is
    # a per-request cache poison) — the date is still injected → no search needed for 'now'.
    assert "Current date" in sys
