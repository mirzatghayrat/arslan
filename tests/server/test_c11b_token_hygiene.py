"""C11b (v0.1.63, #338 review F3–F7): the access token stays out of the log, and four small gaps close.

Every test uses the fake token below and asserts that nothing captured from the loggers carries it.
Each one fails with the matching change in server/ reverted (listed next to the test). The log tests
format records with uvicorn's own formatters and config, the way the desktop app's sidecar writes them.
"""
from __future__ import annotations

import importlib
import io
import logging
import logging.config
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

from tests.server.conftest import build_ws_client
from tests.server.test_token_bootstrap import _app_after_bootstrap, _reset_bootstrap_token  # noqa: F401

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
    """Collects what a logger's handlers would write, after the logger's own filters ran. A formatter
    that cannot render the record raises here (a real handler would print a logging error and drop
    the line), so a test sees the drop instead of passing on a plain Formatter (C11b review 1)."""

    def __init__(self, lines: list[str], formatter: logging.Formatter) -> None:
        super().__init__()
        self.lines = lines
        self.setFormatter(formatter)

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


UVICORN_LOGGERS = ("uvicorn.error", "uvicorn.access", "uvicorn.asgi")


def _uvicorn_formatter(name: str) -> logging.Formatter:
    """The formatter uvicorn's default LOGGING_CONFIG gives that logger's handler (no colours: a pipe)."""
    from uvicorn.config import LOGGING_CONFIG
    from uvicorn.logging import AccessFormatter, DefaultFormatter
    if name == "uvicorn.access":
        return AccessFormatter(fmt=LOGGING_CONFIG["formatters"]["access"]["fmt"], use_colors=False)
    return DefaultFormatter(fmt=LOGGING_CONFIG["formatters"]["default"]["fmt"], use_colors=False)


@pytest.fixture
def _uvicorn_loggers_restored():
    """Snapshot and restore the uvicorn loggers' handlers, level, propagation and enabled flag."""
    import server.main  # noqa: F401  (installs the filters at import)
    loggers = [logging.getLogger(name) for name in ("uvicorn", *UVICORN_LOGGERS)]
    previous = [(list(lg.handlers), lg.level, lg.propagate, lg.disabled) for lg in loggers]
    yield loggers
    for lg, (handlers, level, propagate, disabled) in zip(loggers, previous):
        lg.handlers = handlers
        lg.setLevel(level)
        lg.propagate = propagate
        lg.disabled = disabled


@pytest.fixture
def uvicorn_lines(_uvicorn_loggers_restored):
    """What uvicorn's own formatters write for each logger it puts request lines on; `uvicorn.asgi`
    at trace level, the others at INFO, the level the desktop app runs."""
    from uvicorn.logging import TRACE_LOG_LEVEL
    lines: list[str] = []
    for name in UVICORN_LOGGERS:
        lg = logging.getLogger(name)
        lg.setLevel(TRACE_LOG_LEVEL if name == "uvicorn.asgi" else logging.INFO)
        lg.disabled = False
        lg.addHandler(_Lines(lines, _uvicorn_formatter(name)))
    return lines


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
    assert len(uvicorn_lines) == 3
    for line in uvicorn_lines:
        assert FAKE_TOKEN not in line
        assert '"WebSocket /ws/arslan/main?token=[redacted]"' in line     # the route stays readable
    assert uvicorn_lines[0].endswith("[accepted]")
    assert uvicorn_lines[1].endswith(" 403") and uvicorn_lines[2].endswith(" 404")


def test_the_http_access_line_is_logged_without_the_token(uvicorn_lines):
    # The access line (`uvicorn.access`), with the token between two other query parameters, rendered by
    # uvicorn's AccessFormatter, which unpacks the five arguments itself (C11b review 1).
    path = _uvicorn_path("/api/v1/health", f"a=1&token={FAKE_TOKEN}&b=2")
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50004", "GET", path, "1.1", 200)
    (line,) = uvicorn_lines
    assert FAKE_TOKEN not in line
    assert line.endswith('127.0.0.1:50004 - "GET /api/v1/health?a=1&token=[redacted]&b=2 HTTP/1.1" 200 OK')


@pytest.mark.parametrize("fmt,args", [
    ("%s=%s", ("token", FAKE_TOKEN)),                 # name and value in separate arguments
    ("handshake token=%s from %s", (FAKE_TOKEN, "127.0.0.1")),   # the value fills a `token=%s` placeholder
], ids=["split across arguments", "placeholder after token="])
def test_a_token_however_the_call_spells_it_is_logged_redacted(uvicorn_lines, fmt, args):
    """Follow-up to the C11b re-check: each piece redacted alone left two call shapes. A `token=%s` format string
    lost its placeholder to the redaction, so the line failed to format and logging would print the arguments,
    token and all; a name and value passed apart were never seen together. The finished line is checked too."""
    logging.getLogger("uvicorn.error").info(fmt, *args)
    (line,) = uvicorn_lines
    assert FAKE_TOKEN not in line and "token=[redacted]" in line


def test_a_call_that_never_formats_keeps_its_words_and_withholds_its_arguments(uvicorn_lines):
    """A logging error would print the arguments as they were (`Arguments: (...)`), a token among them; the line is
    kept with its words and without them."""
    logging.getLogger("uvicorn.error").info("handshake with %s", FAKE_TOKEN, "one argument too many")
    (line,) = uvicorn_lines
    assert FAKE_TOKEN not in line and line.endswith("handshake with %s (unformattable arguments withheld)")


def test_a_line_with_no_token_is_logged_as_it_was(uvicorn_lines):
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50005", "GET", "/api/v1/health",
                                             "1.1", 200)
    assert uvicorn_lines == ['INFO:     127.0.0.1:50005 - "GET /api/v1/health HTTP/1.1" 200 OK']


def test_the_sidecars_logging_config_writes_the_access_line_redacted(_uvicorn_loggers_restored, monkeypatch):
    """The whole chain as the desktop app's sidecar has it: uvicorn's LOGGING_CONFIG through dictConfig
    (after the app module installed the filters, the order the sidecar has), then an access line and a
    handshake line. The line is written, redacted, and no logging error is printed (C11b review 1)."""
    from uvicorn.config import LOGGING_CONFIG
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)          # LOGGING_CONFIG's handlers resolve ext://sys.stdout / stderr
    monkeypatch.setattr(sys, "stderr", err)          # at dictConfig time
    logging.config.dictConfig(LOGGING_CONFIG)
    path = _uvicorn_path("/api/v1/health", f"token={FAKE_TOKEN}")
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50006", "GET", path, "1.1", 200)
    logging.getLogger("uvicorn.error").info('%s - "WebSocket %s" [accepted]', "127.0.0.1:50007",
                                            _uvicorn_path("/ws/arslan/main", f"token={FAKE_TOKEN}"))
    written = out.getvalue() + err.getvalue()
    assert FAKE_TOKEN not in written
    assert "Logging error" not in written and "Traceback" not in written
    assert '127.0.0.1:50006 - "GET /api/v1/health?token=[redacted] HTTP/1.1" 200 OK' in out.getvalue()
    assert '"WebSocket /ws/arslan/main?token=[redacted]" [accepted]' in err.getvalue()


def test_the_asgi_trace_log_carries_no_token(uvicorn_lines):
    # `--log-level trace`: uvicorn's message logger writes the ASGI scope, query string included, on
    # `uvicorn.asgi` (C11b review 5). The scope is a dict argument, not a string.
    from uvicorn.logging import TRACE_LOG_LEVEL
    scope = {"type": "websocket", "path": "/ws/arslan/main", "query_string": f"token={FAKE_TOKEN}".encode()}
    logging.getLogger("uvicorn.asgi").log(TRACE_LOG_LEVEL, "%s - ASGI [%d] Started scope=%s", "127.0.0.1:50008", 1, scope)
    (line,) = uvicorn_lines
    assert FAKE_TOKEN not in line
    assert "'query_string': b'token=[redacted]'" in line


# 1b ── the first-boot banner names where the token is, never its value ──────────────────────────

def test_minting_a_token_logs_where_it_is_stored_and_not_its_value(tmp_path, caplog):
    # C11b review 2: this warning reaches stderr in the desktop app, and the release check keeps it in app.log.
    import server.token_bootstrap as tb
    with caplog.at_level(logging.DEBUG):
        token = tb._generate_and_persist(tmp_path, log=logging.getLogger("t"))
    assert token and (tmp_path / "api_token").read_text().strip() == token
    assert token not in caplog.text
    assert str(tmp_path / "api_token") in caplog.text


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


@pytest.mark.asyncio
async def test_a_non_ascii_bearer_on_the_token_routes_is_refused_not_a_crash(monkeypatch, tmp_path):
    """The four routes that check the bearer themselves (C11b review 3): the packaged app, a direct
    loopback caller, a non-ASCII bearer. Each answers as it does to a wrong ASCII bearer, never a 500."""
    from server.services import settings_service
    app, auth = _app_after_bootstrap(monkeypatch, tmp_path, ARSLAN_PACKAGED="1")
    monkeypatch.setattr(settings_service, "mcp_server_enabled", AsyncMock(return_value=False))
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    assert auth.active_token()
    bearer = {"Authorization": f"Bearer {NON_ASCII_TOKEN}".encode("utf-8")}
    transport = ASGITransport(app=app, client=("127.0.0.1", 5001))
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        shown = await c.get("/api/v1/settings/access-token", headers=bearer)
        reset = await c.post("/api/v1/settings/access-token/reset", headers=bearer)
        generate = await c.post("/api/v1/settings/mcp-token/generate", headers=bearer)
        disable = await c.post("/api/v1/settings/mcp-token/disable", headers=bearer)
    assert shown.status_code == 200 and shown.json() == {"token_required": True, "token": None}
    assert (reset.status_code, generate.status_code, disable.status_code) == (401, 401, 401)


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
    ("ARSLAN_ALLOWED_ORIGINS", "https://*.example"),
    ("ARSLAN_ALLOWED_HOSTS", "*"),
    ("ARSLAN_ALLOWED_HOSTS", "a.example,*"),
    # C11b review 4: server.security strips `:port`, so these would become `*`; `*.` matches every
    # name ending in a dot; a `*.` prefix is refused with them (a dev bind names each host in full).
    ("ARSLAN_ALLOWED_HOSTS", "*:8000"),
    ("ARSLAN_ALLOWED_HOSTS", "*:*"),
    ("ARSLAN_ALLOWED_HOSTS", "*."),
    ("ARSLAN_ALLOWED_HOSTS", "*.example.com"),
])
def test_a_wildcard_allowlist_refuses_to_start(monkeypatch, variable, value):
    with pytest.raises(ValueError, match=f"{variable}.*'\\*' is not accepted"):
        _config(monkeypatch, **{variable: value})


@pytest.mark.parametrize("value", ["null", "https://a.example, null", "NULL", " Null "])
def test_a_null_origin_refuses_to_start(monkeypatch, value):
    """Follow-up to the C11b re-check: `null` is the Origin a sandboxed iframe, a `data:` page or a file sends,
    so any site can produce it; allowing it would open CORS and the WebSocket to them all."""
    with pytest.raises(ValueError, match="ARSLAN_ALLOWED_ORIGINS.*'null' is not accepted"):
        _config(monkeypatch, ARSLAN_ALLOWED_ORIGINS=value)


def test_an_explicit_allowlist_still_loads(monkeypatch):
    settings = _config(monkeypatch, ARSLAN_ALLOWED_ORIGINS="https://a.example",
                       ARSLAN_ALLOWED_HOSTS="a.example,localhost:8000").settings
    assert settings.allowed_origins == ("https://a.example",)
    assert settings.allowed_hosts == ("a.example", "localhost:8000")


# 4 ── F6: the desktop app's server serves no API explorer ────────────────────────────────────────

API_EXPLORER = ("/docs", "/redoc", "/openapi.json")


def test_a_packaged_server_serves_no_api_explorer(monkeypatch):
    # No explorer route is registered. Here, with no static folder, that is a 404; in the bundle the
    # SPA catch-all answers these paths with the app's own page, and no schema is served either way.
    from tests.route_introspection import iter_route_paths
    _config(monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_SECRET_KEY="x" * 32, ARSLAN_API_TOKEN=FAKE_TOKEN)
    import server.security as security
    importlib.reload(security)
    import server.main as main
    app = main.create_app()
    assert not set(API_EXPLORER) & iter_route_paths(app)
    packaged = TestClient(app, base_url="http://localhost")
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
