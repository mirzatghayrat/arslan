"""WebSocket handshake token enforcement — integration coverage for all 3 endpoints.

The three inline WS routes in ``main.py`` (``/ws/chat``, ``/ws/arslan``,
``/ws/sandbox``) delegate to the handlers in ``server/ws/*.py``, each of which
validates the ``?token=`` query param via ``is_ws_token_valid`` *before*
accepting the socket. ``test_auth.py`` already unit-tests the helper; these tests
prove the wiring end to end:

* with ``ARSLAN_API_TOKEN`` set, a wrong or missing token closes the handshake
  with code ``4001`` (the socket never upgrades — the guard runs before
  ``ws.accept()``);
* the correct token connects and receives the first ``history`` frame;
* with the token unset, the empty-token passthrough lets any client connect,
  mirroring the HTTP ``require_auth`` no-op-when-unset semantics.
"""
import importlib

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

from sqlalchemy.pool import NullPool

import server.db.session as db_session
from server.db.models import Base, Spawn

# (path, human name) for each of the three token-guarded WS endpoints. The
# arslan channel is the highest-risk one (drives spawn dispatch / roster edits).
WS_ENDPOINTS = [
    ("/ws/chat/1", "chat"),
    ("/ws/arslan/main", "arslan"),
    ("/ws/sandbox/1", "sandbox"),
]


def _build_client(tmp_path, monkeypatch, token: str) -> TestClient:
    """Build a TestClient whose app sees ``ARSLAN_API_TOKEN=token``.

    Reloads ``server.config`` so ``config.settings.api_token`` reflects the env,
    then points the WS handlers' session factory at an isolated temp DB seeded
    with one spawn (id=1) so the chat/sandbox handlers get past their spawn
    lookup once the token check passes.
    """
    monkeypatch.setenv("ARSLAN_API_TOKEN", token)
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))

    import server.config as config

    importlib.reload(config)  # is_ws_token_valid reads config.settings live

    # NullPool: TestClient drives each WS connection on its own portal event
    # loop; a pooled aiosqlite connection reused across loops hangs on teardown
    # (see the arslan endpoint's extra roster/_history DB work). Don't pool.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path/'wsauth.db'}", poolclass=NullPool
    )
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            s.add(
                Spawn(
                    name="beauty-guru",
                    domain_category="content-creator",
                    domain_subcategory="xiaohongshu",
                    capabilities=["content-generation"],
                    system_prompt="You are a beauty expert.",
                )
            )
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    return TestClient(create_app())


@pytest.mark.parametrize("path,name", WS_ENDPOINTS)
def test_ws_rejects_wrong_token(tmp_path, monkeypatch, path, name):
    client = _build_client(tmp_path, monkeypatch, "secret123")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"{path}?token=wrong") as ws:
            ws.receive_json()
    assert exc.value.code == 4001


@pytest.mark.parametrize("path,name", WS_ENDPOINTS)
def test_ws_rejects_missing_token(tmp_path, monkeypatch, path, name):
    client = _build_client(tmp_path, monkeypatch, "secret123")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(path) as ws:  # no ?token=
            ws.receive_json()
    assert exc.value.code == 4001


@pytest.mark.parametrize("path,name", WS_ENDPOINTS)
def test_ws_accepts_correct_token(tmp_path, monkeypatch, path, name):
    client = _build_client(tmp_path, monkeypatch, "secret123")
    with client.websocket_connect(f"{path}?token=secret123") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "history"


@pytest.mark.parametrize("path,name", WS_ENDPOINTS)
def test_ws_open_when_token_unset(tmp_path, monkeypatch, path, name):
    # Empty token => auth disabled => any client (even token-less) connects.
    client = _build_client(tmp_path, monkeypatch, "")
    with client.websocket_connect(path) as ws:  # no ?token=
        frame = ws.receive_json()
        assert frame["type"] == "history"
