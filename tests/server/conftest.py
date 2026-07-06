"""Shared fixtures for server tests."""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base
from server.db.session import get_session
from server.registry.seeder import seed_registry_with


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client with an isolated temp-file SQLite DB."""
    import os

    os.environ["ARSLAN_TEST_ROUTES"] = "1"
    os.environ["ARSLAN_SPAWNS_DIR"] = str(tmp_path / "spawns")
    import server.config as _config
    import importlib as _il

    _il.reload(_config)

    from server.main import create_app

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'app.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as s:
        await seed_registry_with(s)

    async def _override_get_session():
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.db_maker = maker  # type: ignore[attr-defined]  # direct DB access for fixtures
        yield ac
    await engine.dispose()


# ---------------------------------------------------------------------------
# Shared mock LLM adapter — replaces the per-file `_A` stubs that drifted out
# of sync when the native tool-calling migration moved the answer path from
# chat_stream() to chat(). Implements BOTH methods with the real adapter's full
# signature (history/tools/temperature) so run_native's `a.chat(..., tools=)`
# never AttributeErrors and never falls through to a real (401) LLM call.
# ---------------------------------------------------------------------------
class MockAdapter:
    """Stub LLMAdapter. Configure per test:
      - chat_content: str returned by chat() as LLMResponse.content
      - stream_chunks: list[str] yielded by chat_stream()
      - tool_calls: list[dict] returned by chat() as LLMResponse.tool_calls
      - raise_on_call: Exception raised by BOTH methods (error-path tests)
    Records calls in .chat_calls / .chat_stream_calls for assertions."""

    def __init__(self, *, chat_content="all done", stream_chunks=("ok",),
                 tool_calls=None, raise_on_call=None):
        self.chat_content = chat_content
        self.stream_chunks = list(stream_chunks)
        self.tool_calls = list(tool_calls or [])
        self.raise_on_call = raise_on_call
        self.chat_calls: list[dict] = []
        self.chat_stream_calls: list[dict] = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.chat_calls.append({"system": system, "user": user, "history": history,
                                "tools": tools, "temperature": temperature})
        if self.raise_on_call is not None:
            raise self.raise_on_call
        from arslan.models import LLMResponse
        return LLMResponse(content=self.chat_content, tool_calls=self.tool_calls, usage={})

    async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
        self.chat_stream_calls.append({"system": system, "user": user, "history": history,
                                       "tools": tools, "temperature": temperature})
        if self.raise_on_call is not None:
            raise self.raise_on_call
        for chunk in self.stream_chunks:
            yield chunk


@pytest_asyncio.fixture
def mock_adapter():
    """Factory: `mock_adapter(stream_chunks=[...], raise_on_call=...)`."""
    return MockAdapter
