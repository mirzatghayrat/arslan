"""S2 E3 — hermetic replay: a spawn runs on a task WITHOUT polluting real state.

Each test monkeypatches the adapter to a deterministic stub. The invariants:
  - replay writes NO brain_usage (vs a live dispatch which DOES)
  - replay writes NO ConversationEvent (the honesty guard still RUNS — correction applied)
  - the model sees NO MCP tool in replay (builtins kept)
  - replay creates a kind='replay', status='replayed' Run with output + steps, no scoring
  - two arms sharing an ambient + prompts differing by one line → prompts differ by that line
  - is_replayable is False iff the original trace used a non-replay-safe (MCP) tool
"""
from __future__ import annotations

import difflib

import pytest
from sqlalchemy import func, select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import (
    Base,
    BrainUsage,
    ConversationEvent,
    KnowledgeChunk,
    MCPServer,
    Run,
    RunStep,
    Spawn,
    SpawnCapability,
    Tool,
    Toolset,
)
from server.orchestrator import dispatcher, tool_loop
from server.services import replay_run, run_recorder
from server.services.replay_safety import REPLAY_SAFE_BUILTINS, filter_replay_tools


# ---------------------------------------------------------------------------
# Deterministic adapters
# ---------------------------------------------------------------------------
class _StreamAdapter:
    """Zero-tool path stub: chat_stream yields fixed chunks."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
        for c in self._chunks:
            yield c

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        from arslan.models import LLMResponse
        return LLMResponse(content="".join(self._chunks), tool_calls=[], usage={})


class _LLMResp:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _NativeAdapter:
    """Equipped path stub: records every chat() call (incl. the tools schema it saw)."""

    def __init__(self, replies):
        self._it = iter(replies)
        self.calls: list[dict] = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.calls.append({"system": system, "tools": tools})
        return next(self._it)


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
async def maker(tmp_path, monkeypatch):
    """File-backed SQLite (shares across the many sessions dispatch opens), no registry."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'hr.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    yield m
    await engine.dispose()


async def _spawn(maker, name="SpawnA", prompt="You are a helpful agent.") -> int:
    async with maker() as s:
        row = Spawn(name=name, domain_category="x", system_prompt=prompt)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row.id


async def _seed_kb(maker, spawn_id: int, source: str, text: str) -> None:
    """Insert a knowledge chunk + its FTS row so retrieval hits it and records usage."""
    async with maker() as s:
        chunk = KnowledgeChunk(spawn_id=spawn_id, source=source, chunk_index=0, text=text)
        s.add(chunk)
        await s.commit()
        await s.refresh(chunk)
        await s.execute(sa_text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)"))
        await s.execute(sa_text(
            "INSERT INTO knowledge_chunks_fts (rowid, text) VALUES (:rid, :t)"),
            {"rid": chunk.id, "t": text})
        await s.commit()


async def _count(maker, model) -> int:
    async with maker() as s:
        return int((await s.execute(select(func.count()).select_from(model))).scalar() or 0)


# ---------------------------------------------------------------------------
# 1. no brain_usage
# ---------------------------------------------------------------------------
async def test_replay_no_brain_usage(maker, monkeypatch):
    sid = await _spawn(maker)
    await _seed_kb(maker, sid, "policy.txt", "Refund policy is 30 days for all orders.")
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _StreamAdapter(["ok"]))

    # LIVE dispatch: retrieval records material usage.
    await dispatcher.dispatch("c-live", spawn_id=sid, task_brief="refund policy", persist=False)
    live = await _count(maker, BrainUsage)
    assert live >= 1, "live dispatch must record brain_usage for a retrieved material"

    # REPLAY dispatch: retrieval identical, but NO brain_usage write.
    out = await dispatcher.dispatch("c-replay", spawn_id=sid, task_brief="refund policy",
                                    replay=True)
    assert out["run_id"] is not None
    assert await _count(maker, BrainUsage) == live, "replay must not touch brain_usage"


# ---------------------------------------------------------------------------
# 2. no ConversationEvent (guard still runs)
# ---------------------------------------------------------------------------
async def test_replay_no_conversation_events(maker, monkeypatch):
    sid = await _spawn(maker, name="Promiser")
    # Zero-tool spawn streams a forward-promise fabrication ("正在生成中,稍等") → the honesty
    # guard fires. The correction re-synthesis (tool_loop._get_adapter) returns clean prose.
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _StreamAdapter(["正在生成中,稍等"]))
    correction = "更正:我没有相应工具,无法自己产出该文件。"
    monkeypatch.setattr(tool_loop, "_get_adapter",
                        lambda: _StreamAdapter([correction]))

    # REPLAY: guard runs (correction applied to output) but NO ConversationEvent written.
    out = await dispatcher.dispatch("c-replay", spawn_id=sid, task_brief="make a deck",
                                    replay=True)
    assert correction in out["full_output"], "the honesty guard must still run in replay"
    assert await _count(maker, ConversationEvent) == 0, "replay must not write ConversationEvent"

    # LIVE (control): the SAME guard writes exactly one promise_intercept event.
    await dispatcher.dispatch("c-live", spawn_id=sid, task_brief="make a deck", persist=False)
    assert await _count(maker, ConversationEvent) == 1


# ---------------------------------------------------------------------------
# 3. no MCP tools visible to the model
# ---------------------------------------------------------------------------
@pytest.fixture
async def seeded(tmp_path, monkeypatch):
    """File-backed SQLite WITH the registry seeded (universal builtins wired)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'hrs.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    from server.registry.seeder import seed_registry
    await seed_registry()
    yield m
    await engine.dispose()


async def test_replay_no_mcp_tools(seeded, monkeypatch):
    async with seeded() as s:
        s.add(MCPServer(id=1, label="fs", command="x", args=[], env=None, status="connected"))
        s.add(Toolset(key="mcp_1", name="fs", description="d", tier="safe", status="wired"))
        s.add(Tool(key="mcp_1__list", toolset_key="mcp_1", description="list files",
                   tier="safe", status="wired", input_schema={}, external_name="list"))
        spawn = Spawn(name="MCPUser", domain_category="x", system_prompt="BASE")
        s.add(spawn)
        await s.flush()
        sid = spawn.id
        s.add(SpawnCapability(spawn_id=sid, kind="toolset", ref_key="mcp_1"))
        await s.commit()

    native = _NativeAdapter([_LLMResp(content="done", tool_calls=[])])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: native)

    out = await dispatcher.dispatch("c-replay", spawn_id=sid, task_brief="hello", replay=True)
    assert out["run_id"] is not None

    tool_calls = [c for c in native.calls if c["tools"]]
    assert tool_calls, "the model was called with a tool schema"
    names = {t["function"]["name"] for t in tool_calls[0]["tools"]}
    assert "web_search" in names, "builtin replay-safe tool must remain visible"
    assert "mcp_1__list" not in names, "MCP tool must be dropped in replay"


def test_filter_replay_tools_unit():
    wired = [
        {"key": "web_search"}, {"key": "render_chart"},
        {"key": "mcp_9__do"}, {"key": "create_skill"}, {"key": "ask_user_choice"},
    ]
    kept = {t["key"] for t in filter_replay_tools(wired)}
    assert kept == {"web_search", "render_chart"}
    assert "mcp_9__do" not in REPLAY_SAFE_BUILTINS


# ---------------------------------------------------------------------------
# 4. replay creates a replay Run, no scoring
# ---------------------------------------------------------------------------
async def test_replay_creates_replay_run(maker, monkeypatch):
    sid = await _spawn(maker)
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _StreamAdapter(["hello world"]))
    scored: list[int] = []
    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda rid: scored.append(rid))

    out = await dispatcher.dispatch("c-replay", spawn_id=sid, task_brief="greet", replay=True)
    run_id = out["run_id"]

    async with maker() as s:
        run = await s.get(Run, run_id)
        steps = (await s.execute(select(RunStep).where(RunStep.run_id == run_id))).scalars().all()

    assert run is not None
    assert run.kind == "replay"
    assert run.status == "replayed"
    assert run.final_output == "hello world"
    assert len(steps) >= 1, "replay must record its trace as RunSteps"
    assert scored == [], "a replay must NOT schedule judge scoring"


# ---------------------------------------------------------------------------
# 5. two-arm symmetry
# ---------------------------------------------------------------------------
async def test_two_arm_symmetry(maker, monkeypatch):
    sid = await _spawn(maker)
    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _StreamAdapter(["out"]))

    prompt_a = "You are agent X.\nRULE ONE: be concise."
    prompt_b = "You are agent X.\nRULE ONE: be verbose."

    async with maker() as s:
        ambient = await replay_run.snapshot_ambient(
            s, spawn_id=sid, conversation_id="c", task="do the thing")

    arm_a = await replay_run.run_arm(None, spawn_id=sid, task="do the thing",
                                     system_prompt=prompt_a, ambient=ambient)
    arm_b = await replay_run.run_arm(None, spawn_id=sid, task="do the thing",
                                     system_prompt=prompt_b, ambient=ambient)

    async with maker() as s:
        sys_a = (await s.get(Run, arm_a["run_id"])).system_prompt
        sys_b = (await s.get(Run, arm_b["run_id"])).system_prompt

    changed = [ln for ln in difflib.ndiff(sys_a.splitlines(), sys_b.splitlines())
               if ln.startswith(("+ ", "- "))]
    assert changed == ["- RULE ONE: be concise.", "+ RULE ONE: be verbose."], (
        "the two arms' full system prompts must differ ONLY by the one target line")


# ---------------------------------------------------------------------------
# 6. is_replayable
# ---------------------------------------------------------------------------
async def _run_with_tool(maker, tool_key: str | None) -> int:
    async with maker() as s:
        run = Run(conversation_id="c", spawn_id=None, user_message="t", status="recorded")
        s.add(run)
        await s.commit()
        await s.refresh(run)
        if tool_key is not None:
            s.add(RunStep(run_id=run.id, seq=0, kind="tool_call",
                          ref={"tool": tool_key, "ok": True}, detail={}))
            await s.commit()
        return run.id


async def test_is_replayable(maker):
    builtin_run = await _run_with_tool(maker, "web_search")
    mcp_run = await _run_with_tool(maker, "mcp_1__list")
    no_tool_run = await _run_with_tool(maker, None)

    async with maker() as s:
        assert await replay_run.is_replayable(s, builtin_run) is True
        assert await replay_run.is_replayable(s, mcp_run) is False
        assert await replay_run.is_replayable(s, no_tool_run) is True
