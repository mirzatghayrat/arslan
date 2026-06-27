"""Loop: gate enforcement, bounds, events, escalate surfacing, final streaming."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, SpawnCapability


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'lp.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        from server.registry.seeder import seed_registry

        await seed_registry()
        async with m() as s:
            s.add(Spawn(id=7, name="小美", domain_category="c", system_prompt="sp"))
            s.add(SpawnCapability(spawn_id=7, kind="toolset", ref_key="web_search_scraping"))
            await s.commit()

    anyio.run(_seed)
    return m


class _Resp:
    def __init__(self, content):
        self.content = content


def _scripted_adapter(replies):
    """Adapter stub yielding canned chat_stream replies in order."""
    it = iter(replies)

    class _A:
        async def chat_stream(self, system, user, history=None, **kw):
            yield next(it)

    return _A()


@pytest.mark.asyncio
async def test_tool_call_then_final(maker, monkeypatch):
    from server.orchestrator import spawn_loop, tool_loop
    from server.orchestrator.untrusted import DELIM_CLOSE, DELIM_OPEN

    calls = {}
    captured_convo = []

    class _Exec:
        key = "web_search"

        async def execute(self, args):
            calls["args"] = args
            return {"ok": True, "results": [{"title": "T", "url": "u", "snippet": "s"}]}

    monkeypatch.setattr(tool_loop, "EXECUTORS", {"web_search": _Exec()})

    class _CapturingAdapter:
        _replies = iter([
            '{"tool": "web_search", "args": {"query": "防晒 趋势"}}',
            "最终答案：成分党内容上升。",
        ])

        async def chat_stream(self, system, user, history=None, **kw):
            captured_convo.append({"system": system, "user": user, "history": list(history or [])})
            yield next(self._replies)

    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _CapturingAdapter())

    events, chunks = [], []
    out = await spawn_loop.run(
        spawn_id=7, system="sp", user_content="查一下防晒趋势", history=[],
        current_turn=1, emit=events.append, on_chunk=chunks.append,
    )
    assert out["final"] == "最终答案：成分党内容上升。"
    assert out["escalation"] is None
    assert calls["args"]["query"] == "防晒 趋势"
    types = [e["type"] for e in events]
    assert types == ["tool_call", "tool_result"]
    assert events[0]["tool"] == "web_search"
    assert events[1]["ok"] is True
    assert "".join(chunks) == out["final"]

    # --- structural isolation assertions ---
    # The system prompt must carry the guard note.
    assert "untrusted external data" in captured_convo[0]["system"]

    # The second call receives the TOOL RESULT as the `user` argument (convo[-1]).
    tr_user = captured_convo[1]["user"]
    assert "TOOL RESULT" in tr_user, "second chat call must include TOOL RESULT"
    assert DELIM_OPEN in tr_user, "TOOL RESULT must contain open delimiter"
    assert DELIM_CLOSE in tr_user, "TOOL RESULT must contain close delimiter"


@pytest.mark.asyncio
async def test_unequipped_tool_refused_in_loop(maker, monkeypatch):
    """Spec test #4 runtime half: naming execute_code verbatim gets a refusal,
    never an execution."""
    from server.orchestrator import spawn_loop, tool_loop

    executed = []

    class _Exec:
        key = "execute_code"

        async def execute(self, args):
            executed.append(args)
            return {"ok": True}

    # even if an executor EXISTS, the gate must refuse: it's not in the spawn's wired set
    monkeypatch.setattr(tool_loop, "EXECUTORS", {"execute_code": _Exec()})
    adapter = _scripted_adapter([
        '{"tool": "execute_code", "args": {"code": "rm -rf /"}}',
        "ok, answering without it.",
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    events = []
    out = await spawn_loop.run(
        spawn_id=7, system="sp", user_content="x", history=[],
        current_turn=1, emit=events.append, on_chunk=lambda c: None,
    )
    assert executed == []
    assert events[0]["type"] == "tool_call"
    assert events[1]["type"] == "tool_result" and events[1]["ok"] is False
    assert "not available" in events[1]["summary"]
    assert out["final"] == "ok, answering without it."


@pytest.mark.asyncio
async def test_budget_forces_final(maker, monkeypatch):
    from server.orchestrator import spawn_loop, tool_loop

    class _Exec:
        key = "web_search"

        async def execute(self, args):
            return {"ok": True, "results": []}

    monkeypatch.setattr(tool_loop, "EXECUTORS", {"web_search": _Exec()})
    replies = ['{"tool": "web_search", "args": {"query": "q"}}'] * 5 + ["forced answer"]
    adapter = _scripted_adapter(replies)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    out = await spawn_loop.run(
        spawn_id=7, system="sp", user_content="x", history=[],
        current_turn=1, emit=lambda e: None, on_chunk=lambda c: None,
    )
    assert out["final"] == "forced answer"


@pytest.mark.asyncio
async def test_escalate_ends_turn(maker, monkeypatch):
    from server.orchestrator import spawn_loop, tool_loop

    adapter = _scripted_adapter([
        '{"escalate": {"kind": "data", "need": "latest trend data", "context": "for the post"}}',
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    out = await spawn_loop.run(
        spawn_id=7, system="sp", user_content="x", history=[],
        current_turn=1, emit=lambda e: None, on_chunk=lambda c: None,
    )
    assert out["final"] is None
    assert out["escalation"]["need"] == "latest trend data"


@pytest.mark.asyncio
async def test_escalate_disabled_feeds_back_and_continues(maker, monkeypatch):
    """When allow_escalation=False, escalate reply becomes feedback line and loop continues."""
    from server.orchestrator import spawn_loop, tool_loop

    adapter = _scripted_adapter([
        '{"escalate": {"kind": "data", "need": "more info", "context": ""}}',
        "final answer without escalation",
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    out = await spawn_loop.run(
        spawn_id=7, system="sp", user_content="x", history=[],
        current_turn=1, emit=lambda e: None, on_chunk=lambda c: None,
        allow_escalation=False,
    )
    assert out["escalation"] is None
    assert out["final"] == "final answer without escalation"


def test_spawn_loop_forces_tools(maker, monkeypatch):
    """spawn_loop must pass force_tools=True to tool_loop.run (spawns structurally use tools)."""
    from server.orchestrator import spawn_loop, tool_loop

    seen = {}

    async def fake_run(**kw):
        seen["force_tools"] = kw.get("force_tools")
        return {"final": "ok", "escalation": None, "tool_trace": []}

    monkeypatch.setattr(tool_loop, "run", fake_run)
    anyio.run(lambda: spawn_loop.run(
        spawn_id=7, system="s", user_content="u", history=[],
        current_turn=1, emit=lambda e: None, on_chunk=lambda c: None,
    ))
    assert seen["force_tools"] is True
