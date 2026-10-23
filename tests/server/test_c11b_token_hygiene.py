"""C11b (v0.1.63, #338 review F3–F7): the access token stays out of the log, and four small gaps close.

Every test uses the fake token below and asserts that nothing captured from the loggers carries it.
Each one fails with the matching change in server/ reverted (listed next to the test).
"""
from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

from tests.server.conftest import build_ws_client

# Not a real token: made up for these tests. Long and distinctive so a leak cannot hide in another word.
FAKE_TOKEN = "fake-access-token-for-c11b-tests-0123456789"
NON_ASCII_TOKEN = "tök€n-not-ascii"

_ENV = ("ARSLAN_ENV", "ARSLAN_SECRET_KEY", "ARSLAN_API_TOKEN", "ARSLAN_PACKAGED", "ARSLAN_ALLOWED_ORIGINS",
        "ARSLAN_ALLOWED_HOSTS", "ARSLAN_TEST_ROUTES")


def _config(monkeypatch, **env):
    for key in _ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import server.config as config
    return importlib.reload(config)


@pytest.fixture(autouse=True)
def _restore_config(monkeypatch):
    yield
    monkeypatch.undo()
    import server.config as config
    importlib.reload(config)


@pytest.fixture(autouse=True)
def _no_token_in_the_log(caplog):
    """Whatever a test logs at any level, the fake token is not in it."""
    caplog.set_level(logging.DEBUG)
    yield
    assert FAKE_TOKEN not in caplog.text


class _Lines(logging.Handler):
    """Collects what a logger's handlers would write, after the logger's own filters ran."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture
def uvicorn_lines():
    """A handler on each uvicorn logger uvicorn writes request lines to, at the level the desktop app runs."""
    import server.main  # noqa: F401  (installs the filters at import)
    handler = _Lines()
    loggers = [logging.getLogger(name) for name in ("uvicorn.error", "uvicorn.access")]
    previous = [(lg.level, lg.disabled) for lg in loggers]
    for lg in loggers:
        lg.setLevel(logging.INFO)
        lg.disabled = False
        lg.addHandler(handler)
    yield handler
    for lg, (level, disabled) in zip(loggers, previous):
        lg.removeHandler(handler)
        lg.setLevel(level)
        lg.disabled = disabled


# 1 ── F3: the WebSocket handshake line no longer carries the token ────────────────────────────────

def _uvicorn_path(path: str, query: str) -> str:
    """The path argument as uvicorn builds it for its request lines (path plus raw query string)."""
    from uvicorn.protocols.utils import get_path_with_query_string
    return get_path_with_query_string({"path": path, "query_string": query.encode("ascii")})


def test_the_websocket_handshake_lines_are_logged_without_the_token(uvicorn_lines):
    # The three lines uvicorn's websockets protocol writes on `uvicorn.error` (accept, 403, other status).
    log = logging.getLogger("uvicorn.error")
    path = _uvicorn_path("/ws/arslan/main", f"token={FAKE_TOKEN}")
    log.info('%s - "WebSocket %s" [accepted]', "127.0.0.1:50001", path)
    log.info('%s - "WebSocket %s" 403', "127.0.0.1:50002", path)
    log.info('%s - "WebSocket %s" %d', "127.0.0.1:50003", path, 404)
    assert len(uvicorn_lines.lines) == 3
    for line in uvicorn_lines.lines:
        assert FAKE_TOKEN not in line
        assert '"WebSocket /ws/arslan/main?token=[redacted]"' in line     # the route stays readable
    assert uvicorn_lines.lines[0].endswith("[accepted]")
    assert uvicorn_lines.lines[1].endswith(" 403") and uvicorn_lines.lines[2].endswith(" 404")


def test_the_http_access_line_is_logged_without_the_token(uvicorn_lines):
    # The access line (`uvicorn.access`), with the token between two other query parameters.
    path = _uvicorn_path("/api/v1/health", f"a=1&token={FAKE_TOKEN}&b=2")
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50004", "GET", path, "1.1", 200)
    (line,) = uvicorn_lines.lines
    assert FAKE_TOKEN not in line
    assert line.endswith('"GET /api/v1/health?a=1&token=[redacted]&b=2 HTTP/1.1" 200')


def test_a_line_with_no_token_is_logged_as_it_was(uvicorn_lines):
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50005", "GET", "/api/v1/health",
                                             "1.1", 200)
    assert uvicorn_lines.lines == ['127.0.0.1:50005 - "GET /api/v1/health HTTP/1.1" 200']


# 2 ── F4: a non-ASCII token is a refusal (401 / 4001), not a crash ───────────────────────────────

@pytest.mark.asyncio
async def test_a_non_ascii_bearer_is_unauthorized_not_a_crash(monkeypatch):
    _config(monkeypatch, ARSLAN_API_TOKEN=FAKE_TOKEN)
    import server.auth as auth
    import server.main as main
    assert auth.is_ws_token_valid(NON_ASCII_TOKEN) is False
    with pytest.raises(HTTPException) as refused:
        await auth.require_auth(HTTPAuthorizationCredentials(scheme="Bearer", credentials=NON_ASCII_TOKEN))
    assert refused.value.status_code == 401
    # End to end: the header goes over the wire as UTF-8 bytes, which the server reads as non-ASCII text.
    transport = ASGITransport(app=main.create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bad = await client.get("/api/v1/_authcheck",
                               headers={"Authorization": f"Bearer {NON_ASCII_TOKEN}".encode("utf-8")})
        good = await client.get("/api/v1/_authcheck", headers={"Authorization": f"Bearer {FAKE_TOKEN}"})
    assert bad.status_code == 401
    assert good.status_code == 200


def test_a_non_ascii_websocket_token_closes_the_handshake_with_4001(tmp_path, monkeypatch, portal):
    client: TestClient = build_ws_client(portal, tmp_path, monkeypatch, None, db_name="c11b.db",
                                         env={"ARSLAN_API_TOKEN": FAKE_TOKEN})
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws/arslan/main?token=t%C3%B6k%E2%82%ACn-not-ascii") as ws:
            ws.receive_json()
    assert closed.value.code == 4001


# 3 ── F5: `*` in an allowlist refuses to start ───────────────────────────────────────────────────

@pytest.mark.parametrize("variable,value", [
    ("ARSLAN_ALLOWED_ORIGINS", "*"),
    ("ARSLAN_ALLOWED_ORIGINS", "https://a.example, *"),
    ("ARSLAN_ALLOWED_HOSTS", "*"),
    ("ARSLAN_ALLOWED_HOSTS", "a.example,*"),
])
def test_a_wildcard_allowlist_refuses_to_start(monkeypatch, variable, value):
    with pytest.raises(ValueError, match=f"{variable}.*'\\*' is not accepted"):
        _config(monkeypatch, **{variable: value})


def test_an_explicit_allowlist_still_loads(monkeypatch):
    settings = _config(monkeypatch, ARSLAN_ALLOWED_ORIGINS="https://a.example", ARSLAN_ALLOWED_HOSTS="a.example").settings
    assert settings.allowed_origins == ("https://a.example",)
    assert settings.allowed_hosts == ("a.example",)


# 4 ── F6: the desktop app's server serves no API explorer ────────────────────────────────────────

API_EXPLORER = ("/docs", "/redoc", "/openapi.json")


def test_a_packaged_server_serves_no_api_explorer(monkeypatch):
    _config(monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_SECRET_KEY="x" * 32, ARSLAN_API_TOKEN=FAKE_TOKEN)
    import server.security as security
    importlib.reload(security)
    import server.main as main
    packaged = TestClient(main.create_app(), base_url="http://localhost")
    assert [packaged.get(path).status_code for path in API_EXPLORER] == [404, 404, 404]
    _config(monkeypatch)
    importlib.reload(security)
    dev = TestClient(main.create_app(), base_url="http://localhost")
    assert [dev.get(path).status_code for path in API_EXPLORER] == [200, 200, 200]


# 5 ── F7: the seed route needs the access token ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_seed_route_needs_the_access_token(monkeypatch):
    from server.db.session import get_session
    from server.services import spawn_service
    monkeypatch.setattr(spawn_service, "create_spawn", AsyncMock(return_value=SimpleNamespace(id=7)))

    async def _no_session():
        yield None

    _config(monkeypatch, ARSLAN_TEST_ROUTES="1", ARSLAN_API_TOKEN=FAKE_TOKEN)
    import server.main as main
    app = main.create_app()
    app.dependency_overrides[get_session] = _no_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bare = await client.post("/api/v1/_test/seed_spawn", json={"name": "x"})
        wrong = await client.post("/api/v1/_test/seed_spawn", json={"name": "x"},
                                  headers={"Authorization": "Bearer nope"})
        right = await client.post("/api/v1/_test/seed_spawn", json={"name": "x"},
                                  headers={"Authorization": f"Bearer {FAKE_TOKEN}"})
    assert (bare.status_code, wrong.status_code) == (401, 401)
    assert right.status_code == 200 and right.json() == {"id": 7}
    assert spawn_service.create_spawn.await_count == 1

    _config(monkeypatch, ARSLAN_TEST_ROUTES="1")                           # the dev harness: no token, still open
    app = main.create_app()
    app.dependency_overrides[get_session] = _no_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/v1/_test/seed_spawn", json={"name": "x"})).status_code == 200
