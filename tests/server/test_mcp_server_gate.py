import dataclasses

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server import config
from server.db import session as db_session
from server.db.models import Base
from server.mcp_server import token_store
from server.mcp_server.gate import McpServerGate
from server.services import settings_service


class _Inner:
    """Records whether the gate delegated to the wrapped app."""
    def __init__(self):
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _http_scope(auth: str | None = None):
    headers = [(b"host", b"127.0.0.1")]
    if auth is not None:
        headers.append((b"authorization", auth.encode()))
    return {"type": "http", "method": "POST", "path": "/", "headers": headers}


async def _drive(gate, scope):
    sent = []
    async def receive():  # noqa: ANN202
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(msg):  # noqa: ANN202
        sent.append(msg)
    await gate(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'g.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    # The gate calls token_store.mcp_token_matches(bearer) with no explicit data_dir,
    # so it reads server.config.settings.data_dir. Point that at tmp_path so tests
    # that generate a token with data_dir=tmp_path and the gate's ambient lookup
    # agree on the same location.
    #
    # NOTE: server.config.Settings is a frozen dataclass, so
    # monkeypatch.setattr("server.config.settings.data_dir", ...) (the task brief's
    # suggested "option b") raises dataclasses.FrozenInstanceError — mutating a field
    # in place is not possible. Rebinding the module-level `settings` name itself to
    # a replacement instance works: token_store._resolve_data_dir() does a call-time
    # `from server.config import settings`, which (per its own comment) "honors a
    # reloaded config in tests" — i.e. it re-reads whatever object is currently bound
    # to server.config.settings, which is exactly what this replaces. Same effect as
    # option b (no env var, no importlib.reload), monkeypatch auto-reverts at
    # teardown.
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, data_dir=tmp_path))

    async def set_enabled(v):
        async with maker() as s:
            await settings_service.update_settings(s, {"mcp_server_enabled": v})

    yield tmp_path, set_enabled
    await engine.dispose()


async def test_disabled_rejects_even_with_a_valid_token(env):
    tmp_path, set_enabled = env
    tok = token_store.generate_mcp_token(data_dir=tmp_path)
    await set_enabled(False)
    inner = _Inner()
    status = await _drive(McpServerGate(inner), _http_scope(f"Bearer {tok}"))
    assert status == 403 and inner.called is False


async def test_enabled_no_token_and_wrong_token_reject(env):
    tmp_path, set_enabled = env
    token_store.generate_mcp_token(data_dir=tmp_path)
    await set_enabled(True)
    inner = _Inner()
    assert await _drive(McpServerGate(inner), _http_scope(None)) == 401
    assert await _drive(McpServerGate(inner), _http_scope("Bearer wrong")) == 401
    assert inner.called is False


async def test_enabled_correct_token_delegates(env):
    tmp_path, set_enabled = env
    tok = token_store.generate_mcp_token(data_dir=tmp_path)
    await set_enabled(True)
    inner = _Inner()
    assert await _drive(McpServerGate(inner), _http_scope(f"Bearer {tok}")) == 200
    assert inner.called is True


async def test_closed_even_when_require_auth_is_a_noop(env, monkeypatch):
    # require_auth is a no-op when no api_token is set — the MCP gate must still close.
    from server import auth
    monkeypatch.setattr(auth, "active_token", lambda: "")   # confirm no app token
    tmp_path, set_enabled = env
    await set_enabled(False)
    inner = _Inner()
    assert await _drive(McpServerGate(inner), _http_scope(None)) == 403
    assert inner.called is False


async def test_reject_emits_audit_line_without_the_bearer(env, caplog):
    import logging
    tmp_path, set_enabled = env
    await set_enabled(False)
    with caplog.at_level(logging.INFO, logger="arslan.mcp_server.audit"):
        await _drive(McpServerGate(_Inner()), _http_scope("Bearer some-secret-xyz"))
    lines = [r.getMessage() for r in caplog.records if r.name == "arslan.mcp_server.audit"]
    assert len(lines) == 1 and "reject" in lines[0]
    assert "some-secret-xyz" not in " ".join(lines)   # the bearer is never logged


async def test_websocket_is_closed_1008_and_audited(env, caplog):
    # An untrusted cross-site WS probe must leave a trace: reject:ws audit line,
    # clean 1008 close, and the MCP app is never reached — even when enabled.
    import logging
    tmp_path, set_enabled = env
    await set_enabled(True)
    inner = _Inner()
    scope = {"type": "websocket", "path": "/", "headers": []}
    sent = []
    async def receive():  # noqa: ANN202
        return {"type": "websocket.connect"}
    async def send(msg):  # noqa: ANN202
        sent.append(msg)
    with caplog.at_level(logging.INFO, logger="arslan.mcp_server.audit"):
        await McpServerGate(inner)(scope, receive, send)
    assert sent == [{"type": "websocket.close", "code": 1008}]
    assert inner.called is False
    lines = [r.getMessage() for r in caplog.records if r.name == "arslan.mcp_server.audit"]
    assert len(lines) == 1 and "reject:ws" in lines[0]


async def test_non_ascii_bearer_is_401_not_500(env):
    tmp_path, set_enabled = env
    token_store.generate_mcp_token(data_dir=tmp_path)
    await set_enabled(True)
    scope = {"type": "http", "method": "POST", "path": "/",
             "headers": [(b"host", b"127.0.0.1"), (b"authorization", b"Bearer \xff\xfe")]}
    assert await _drive(McpServerGate(_Inner()), scope) == 401
