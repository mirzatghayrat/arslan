"""Tests that LLM errors during orchestration are surfaced as in-chat error frames
instead of being silently swallowed or propagated as unhandled exceptions that
close the WebSocket.

Root-cause regression suite for the Gemini-primary-LLM no-response bug:
- router.route() raising → must emit {"type": "error"} not raise
- _classify_followup raising → must emit {"type": "error"} not raise
- _handle_answer streaming raising → must emit {"type": "error"} not raise
- All three cases must NOT propagate an exception out of handle_user_message
  (which would close the WebSocket instead of showing an error in-chat).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    """Isolated in-memory SQLite database for each test."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'err.db'}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    return maker


def _collect():
    """Return (events list, emit callback)."""
    events: list[dict] = []
    return events, lambda ev: events.append(ev)


# ---------------------------------------------------------------------------
# 1. router.route() raises → error frame emitted, no exception propagated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_router_raise_emits_error_frame_not_exception(db, monkeypatch):
    """If router.route() raises (e.g. LLM timeout), handle_user_message must
    emit an error frame and return normally — NOT propagate the exception."""
    from server.orchestrator import arslan, router

    async def _boom(conv, msg):
        raise TimeoutError("Gemini did not respond within 300 s")

    monkeypatch.setattr(router, "route", _boom)
    # stub phase_service so there's no pending proposal to classify
    import server.services.phase_service as ps
    monkeypatch.setattr(ps, "get_pending", lambda cid: _async_none())

    events, emit = _collect()
    # Must NOT raise
    await arslan.handle_user_message("test-conv", "hello", emit)

    error_frames = [e for e in events if e.get("type") == "error"]
    assert error_frames, f"Expected an error frame but got: {events}"
    assert error_frames[0]["code"] == "LLM_ERROR"
    assert "Gemini" in error_frames[0]["message"] or "300" in error_frames[0]["message"]
    assert error_frames[0].get("recoverable") is True


# ---------------------------------------------------------------------------
# 2. _classify_followup raises → error frame emitted, no exception propagated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_followup_raise_emits_error_frame(db, monkeypatch):
    """If _classify_followup raises while a proposal is pending, the error must
    be emitted as an error frame — the WebSocket must stay open."""
    from server.orchestrator import arslan
    import server.services.phase_service as ps

    # Simulate a pending proposal
    async def _fake_pending(cid):
        return {"phase": "proposing", "spawn_id": 7, "direction": "do some marketing"}

    monkeypatch.setattr(ps, "get_pending", _fake_pending)

    async def _boom(user_msg, direction):
        raise ConnectionError("LLM API unreachable")

    monkeypatch.setattr(arslan, "_classify_followup", _boom)

    events, emit = _collect()
    await arslan.handle_user_message("test-conv", "sounds good", emit)

    error_frames = [e for e in events if e.get("type") == "error"]
    assert error_frames, f"Expected an error frame but got: {events}"
    assert error_frames[0]["code"] == "LLM_ERROR"
    assert error_frames[0].get("recoverable") is True


# ---------------------------------------------------------------------------
# 3. tool_loop adapter raises in _handle_answer → error frame emitted,
#    no exception propagated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_answer_llm_error_emits_error_frame(db, monkeypatch):
    """If the LLM raises during streaming in _handle_answer, an error frame
    must be emitted and the function must return normally."""
    from server.orchestrator import arslan, router
    import server.services.phase_service as ps

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(router, "route", _fake_route)
    monkeypatch.setattr(ps, "get_pending", lambda cid: _async_none())

    from server.orchestrator import tool_loop
    from tests.server.conftest import MockAdapter

    monkeypatch.setattr(tool_loop, "_get_adapter",
                        lambda: MockAdapter(raise_on_call=TimeoutError("read timeout")))

    events, emit = _collect()
    await arslan.handle_user_message("test-conv", "hi", emit)

    error_frames = [e for e in events if e.get("type") == "error"]
    assert error_frames, f"Expected an error frame but got: {events}"
    assert error_frames[0]["code"] == "LLM_ERROR"
    assert error_frames[0].get("recoverable") is True


# ---------------------------------------------------------------------------
# 4. Happy-path regression: normal answer still emits stream_start / stream_end
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_normal_answer_still_works_after_error_guard(db, monkeypatch):
    """Ensure the error guard doesn't break the normal answer path."""
    from server.orchestrator import arslan, router
    import server.services.phase_service as ps

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(router, "route", _fake_route)
    monkeypatch.setattr(ps, "get_pending", lambda cid: _async_none())

    from server.orchestrator import tool_loop
    from tests.server.conftest import MockAdapter

    monkeypatch.setattr(tool_loop, "_get_adapter",
                        lambda: MockAdapter(chat_content="Hello world", stream_chunks=["Hello ", "world"]))

    events, emit = _collect()
    await arslan.handle_user_message("test-conv", "hi", emit)

    types = [e["type"] for e in events]
    assert "stream_start" in types
    assert "stream_end" in types
    # run_native answers via adapter.chat() (not chat_stream()) then reveals the
    # final content incrementally via on_chunk, so assert on the joined stream
    # rather than any single chunk.
    streamed = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
    assert "Hello" in streamed
    assert not any(e["type"] == "error" for e in events)


# ---------------------------------------------------------------------------
# 5. GeminiProvider.chat_stream uses per-chunk read timeout (not total timeout)
# ---------------------------------------------------------------------------

def test_gemini_stream_uses_httpx_timeout_object():
    """chat_stream must use an httpx.Timeout object (not a bare float) so that
    the read timeout can be set independently from the connect timeout.  A bare
    float sets all timeouts to the same value, which is too short for thinking
    models during the read phase."""
    import inspect
    from arslan.llm.providers.gemini_provider import GeminiProvider

    src = inspect.getsource(GeminiProvider.chat_stream)
    # Must not have a bare `timeout=60.0` — that's the old behaviour that failed.
    assert "timeout=60.0" not in src, (
        "chat_stream still uses a bare 60 s timeout — thinking models need more"
    )
    # Must use httpx.Timeout
    assert "httpx.Timeout" in src, "chat_stream must use httpx.Timeout for fine-grained control"

    src_chat = inspect.getsource(GeminiProvider.chat)
    assert "timeout=60.0" not in src_chat
    assert "httpx.Timeout" in src_chat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _async_none():
    return None
