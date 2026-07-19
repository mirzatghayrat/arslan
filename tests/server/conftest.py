"""Shared fixtures for server tests."""
from __future__ import annotations

import importlib
import os

# Belt to the root-conftest guard: disable secret auto-generation BEFORE the server.*
# imports below build the frozen settings singleton (see tests/conftest.py for why).
os.environ["ARSLAN_SECRET_KEY_FILE"] = ""
from typing import TYPE_CHECKING, Awaitable, Callable

import pytest
import pytest_asyncio
from anyio.from_thread import start_blocking_portal
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base
from server.db.session import get_session
from server.registry.seeder import seed_registry_with
from server.services import evolution_estimate, evolution_watcher

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _restore_config_after_test():
    """Guard against cross-test ``server.config`` pollution.

    Several tests reload ``server.config`` with a mutated environment (e.g. an *unset*
    ``ARSLAN_SECRET_KEY`` for the middleware-security suite) and never reload it back.
    That was harmless until ``crypto.encrypt()`` began failing closed under an empty
    secret (S1 OSS-safety): a later test that calls ``crypto.encrypt()`` directly would
    then hit the insecure-default refusal purely because of test ordering.

    As an autouse teardown, this runs *after* ``monkeypatch`` has restored the ambient
    environment; if the live config's secret has drifted from that environment, it
    reloads config back to the ambient baseline. It is a cheap no-op when there is no
    drift (the overwhelming majority of tests).
    """
    yield
    import server.config as _cfg

    if (_cfg.settings.secret_key or "") != (os.environ.get("ARSLAN_SECRET_KEY", "") or ""):
        importlib.reload(_cfg)


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


# ---------------------------------------------------------------------------
# Single-loop WS/TestClient harness — the root fix for the cross-loop aiosqlite
# flake (`database is locked` / `Event loop is closed` / portal-teardown hang).
# See docs/tech-debt/single-loop-sqlite-flake.md. Every TestClient-backed test
# seeds its DB and serves every websocket_connect on ONE portal loop, over a
# NullPool engine, so no pooled connection is ever reused across event loops.
# ---------------------------------------------------------------------------
@pytest.fixture
def portal():
    """One blocking portal per test: its single event loop drives BOTH the DB
    seed and every TestClient/websocket_connect built via ``build_ws_client``,
    so no pooled aiosqlite connection is reused across loops (the flake root).

    Teardown order is load-bearing: dispose every engine ON the portal loop
    BEFORE stopping the portal, else the portal thread's ``join()`` blocks
    terminating a live connection. ``portal.stop(cancel_remaining=True)`` also
    cancels fire-and-forget stragglers (distill/ledger ``create_task``) that
    anyio's own ``__exit__`` (cancel_remaining=False) would otherwise wait on —
    the source of the >120s teardown hangs seen on slow CI.
    """
    with start_blocking_portal() as p:
        p._test_engines = []  # populated by build_ws_client, disposed below
        try:
            yield p
        finally:
            try:
                for _engine in p._test_engines:
                    p.call(_engine.dispose)
            finally:
                p.call(p.stop, True)


def build_ws_client(
    portal,
    tmp_path,
    monkeypatch,
    seed: Callable[[async_sessionmaker], Awaitable[None]] | None = None,
    *,
    db_name: str = "app.db",
    env: dict[str, str] | None = None,
) -> "TestClient":
    """Build a TestClient whose app, DB seed, and every websocket_connect run on
    ONE loop (``portal``). NullPool engine + seed-on-portal-loop is the root fix.

    ``seed(maker)`` is an async callback receiving the sessionmaker; each WS test
    file supplies its own (different Spawn configs). It runs via ``portal.call``
    so it executes on the same loop the TestClient will serve on. Schema creation
    (``Base.metadata.create_all``) is done here, before ``seed`` is invoked.

    Env order mirrors the hand-rolled fixtures: set env -> reload config ->
    monkeypatch AsyncSessionLocal -> create_app, so config-dependent app wiring
    reads the intended settings.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import NullPool

    from server.db import session as db_session

    for _k, _v in (env or {}).items():
        monkeypatch.setenv(_k, _v)
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import server.config as _config

    importlib.reload(_config)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path/db_name}", poolclass=NullPool
    )
    portal._test_engines.append(engine)  # disposed at portal-fixture teardown
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        if seed is not None:
            await seed(maker)

    portal.call(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    client = TestClient(create_app())
    client.portal = portal  # websocket_connect + HTTP calls reuse this loop
    client.db_maker = maker  # type: ignore[attr-defined]  # mid-test DB reads via portal.call
    return client


def _assert_testclient_portal_seam() -> None:
    """Fail loudly if a starlette upgrade drops the settable ``.portal`` seam that
    ``build_ws_client`` relies on — otherwise the single-loop fix silently
    regresses to a fresh per-connection loop with no visible test failure."""
    import inspect

    from fastapi.testclient import TestClient as _TC

    factory = getattr(_TC, "_portal_factory", None)
    if factory is None:
        raise AssertionError(
            "starlette TestClient no longer exposes _portal_factory — the single-loop "
            "flake fix relies on a settable .portal seam. See conftest.build_ws_client."
        )
    try:
        src = inspect.getsource(factory)
    except (OSError, TypeError):
        return  # source unavailable (compiled) — cannot introspect; skip.
    assert "self.portal" in src, (
        "starlette TestClient no longer honors a settable .portal — the single-loop "
        "flake fix silently regresses to per-connection loops. See conftest.build_ws_client."
    )


_assert_testclient_portal_seam()


# ── evolution watcher ────────────────────────────────────────────────────────────
# Shared by test_evolution_watcher.py and test_evolution_attempt_source.py. Lives here
# rather than being imported between them so the tests that take it as a parameter are
# not flagged as redefinitions.
@pytest.fixture
async def wdb(tmp_path, monkeypatch):
    """A file-backed SQLite DB wired into db_session.AsyncSessionLocal (so the watcher's own
    sessions hit it), with a cheap stubbed estimate. Resets watcher module state around each
    test so nothing bleeds."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'w.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)

    async def fake_estimate(db, spawn_id):
        return {"pairs": 4, "dispatches": 56, "judge_calls": 56, "optimizer_calls": 3,
                "synth_calls": 0, "est_tokens": 1000, "lower_bound": True}

    monkeypatch.setattr(evolution_estimate, "estimate", fake_estimate)

    evolution_watcher._running_spawns.clear()
    yield Session
    for t in list(evolution_watcher._tasks):
        t.cancel()
    evolution_watcher._tasks.clear()
    evolution_watcher._running_spawns.clear()
    await engine.dispose()
