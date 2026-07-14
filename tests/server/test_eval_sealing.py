# tests/server/test_eval_sealing.py
import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base
from server.services import replay_safety
from server.services.replay_run import REPLAY_CONVERSATION_ID
from server.orchestrator import tool_loop


@pytest_asyncio.fixture(autouse=True)
async def _isolated_db(tmp_path, monkeypatch):
    """Autouse, file-scoped DB isolation.

    The new test_dispatch_* tests (below) call dispatcher.dispatch() for a real
    conversation_id with no other DB setup; on the live branch that reaches
    memory.user_turn_count(), which reads server.db.session.AsyncSessionLocal
    directly (bypassing FastAPI's dependency injection some other tests override).
    Without this, those tests would hit whichever real DB ARSLAN_DATA_DIR happens
    to resolve to in the ambient environment and fail with "no such table" on a
    fresh checkout — unrelated to the behavior under test. Every other dispatcher
    test file in this suite (e.g. test_dispatcher.py's `maker` fixture) sets up an
    isolated schema-created engine the same way; this mirrors that convention as
    an autouse fixture so the given test bodies stay untouched.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'eval_seal.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    yield
    await engine.dispose()


def test_is_hermetic_context_matches_both_eval_sentinels():
    # Both eval sentinels are hermetic; a real conversation id and None are not.
    assert replay_safety.is_hermetic_context("evolution-eval") is True
    assert replay_safety.is_hermetic_context("evolution-replay") is True
    assert replay_safety.is_hermetic_context(REPLAY_CONVERSATION_ID) is True  # == "evolution-replay"
    assert replay_safety.is_hermetic_context("conv_abc123") is False
    assert replay_safety.is_hermetic_context(None) is False


def test_hermetic_set_covers_the_evaluator_sentinel_literal():
    # evaluator.py + evolution_loop._val_outputs dispatch under "evolution-eval";
    # pin that literal is a member so a rename can't silently un-seal them.
    assert "evolution-eval" in replay_safety._HERMETIC_CONVERSATION_IDS


async def test_throat_refuses_nonsafe_tool_in_hermetic_context_even_if_resolver_leaks():
    """The backstop is independent of resolve_tools: even if resolve_tools LEAKS an MCP
    key into the live set (simulating a forgotten upstream filter), a hermetic
    conversation_id must make _dispatch_tool refuse it without executing."""
    executed = []

    async def leaky_resolve():
        # Deliberately leak a side-effecting MCP tool into the live set.
        return [{"key": "mcp_1__send_message"}, {"key": "web_search"}]

    # Monkeypatch resolve_executor so we can detect if execution is (wrongly) reached.
    import server.orchestrator.tool_loop as tl

    async def fake_resolve_executor(key):
        executed.append(key)
        class _E:
            async def execute(self, args):
                executed.append(("EXECUTED", key))
                return {"ok": True}
        return _E()

    orig = tl.resolve_executor
    tl.resolve_executor = fake_resolve_executor
    try:
        emitted = []
        out = await tool_loop._dispatch_tool(
            "mcp_1__send_message", {"to": "x"},
            json.dumps({"tool": "mcp_1__send_message", "args": {}}),
            resolve_tools=leaky_resolve, emit=lambda e: emitted.append(e),
            tool_timeout_s=5, tool_trace=[], convo=[{"role": "user", "content": "hi"}],
            conversation_id="evolution-eval")
    finally:
        tl.resolve_executor = orig

    assert out["ok"] is False
    assert "hermetic" in (out.get("error") or "").lower()
    assert ("EXECUTED", "mcp_1__send_message") not in executed  # never executed


async def test_throat_allows_safe_tool_in_hermetic_context():
    """A read-only builtin (web_search) is NOT blocked by the backstop in a hermetic
    context — it still resolves + executes normally."""
    import server.orchestrator.tool_loop as tl

    async def resolve():
        return [{"key": "web_search"}]

    async def fake_resolve_executor(key):
        class _E:
            async def execute(self, args):
                return {"ok": True, "results": []}
        return _E()

    orig = tl.resolve_executor
    tl.resolve_executor = fake_resolve_executor
    try:
        out = await tool_loop._dispatch_tool(
            "web_search", {"query": "x"},
            json.dumps({"tool": "web_search", "args": {"query": "x"}}),
            resolve_tools=resolve, emit=lambda e: None,
            tool_timeout_s=5, tool_trace=[], convo=[{"role": "user", "content": "hi"}],
            conversation_id="evolution-eval")
    finally:
        tl.resolve_executor = orig
    assert out.get("ok") is True


async def test_dispatch_defaults_to_hermetic_for_eval_sentinel(monkeypatch):
    """An eval-sentinel conversation_id with no explicit replay flag routes to the
    SEALED path (_dispatch_replay), not the live branch."""
    from server.orchestrator import dispatcher

    seen = {}

    async def fake_dispatch_replay(conversation_id, **kw):
        seen["sealed"] = True
        return {"run_id": 1, "full_output": "ok"}

    async def fake_load_spawn(sid):
        return object()  # non-None; _dispatch_replay is faked so the object is unused

    monkeypatch.setattr(dispatcher, "_dispatch_replay", fake_dispatch_replay)
    monkeypatch.setattr(dispatcher, "_load_spawn", fake_load_spawn)

    await dispatcher.dispatch("evolution-eval", spawn_id=1, task_brief="t")
    assert seen.get("sealed") is True


async def test_dispatch_replay_false_under_sentinel_still_sealed(monkeypatch):
    """No opt-out: even an EXPLICIT replay=False under an eval sentinel is sealed (routes
    to _dispatch_replay), because a safety control is no-override."""
    from server.orchestrator import dispatcher

    sealed = {"v": False}

    async def fake_dispatch_replay(conversation_id, **kw):
        sealed["v"] = True
        return {"run_id": 1, "full_output": "ok"}

    async def fake_load_spawn(sid):
        return object()

    monkeypatch.setattr(dispatcher, "_dispatch_replay", fake_dispatch_replay)
    monkeypatch.setattr(dispatcher, "_load_spawn", fake_load_spawn)

    await dispatcher.dispatch("evolution-eval", spawn_id=1, task_brief="t", replay=False)
    assert sealed["v"] is True  # replay=False did NOT open a live dispatch under the sentinel


async def test_dispatch_real_conversation_stays_live(monkeypatch):
    """A real conversation id with no replay flag does NOT route to the sealed path."""
    from server.orchestrator import dispatcher

    sealed = {"v": False}

    async def fake_dispatch_replay(conversation_id, **kw):
        sealed["v"] = True
        return {"run_id": 1, "full_output": "ok"}

    async def fake_load_spawn(sid):
        return object()

    async def fake_build(*a, **k):
        raise RuntimeError("LIVE_BRANCH_TAKEN")

    monkeypatch.setattr(dispatcher, "_dispatch_replay", fake_dispatch_replay)
    monkeypatch.setattr(dispatcher, "_load_spawn", fake_load_spawn)
    monkeypatch.setattr(dispatcher, "build_spawn_system", fake_build)

    with pytest.raises(RuntimeError, match="LIVE_BRANCH_TAKEN"):
        await dispatcher.dispatch("conv_realuser", spawn_id=1, task_brief="t")
    assert sealed["v"] is False  # real conversation stayed on the live branch
