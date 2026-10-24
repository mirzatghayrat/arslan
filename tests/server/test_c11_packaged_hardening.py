"""C11 (v0.1.63, cloud audit [3]): the desktop app's server holds its line without ARSLAN_ENV=prod.

One test per hardening point, each in packaged mode (ARSLAN_PACKAGED=1, what the frozen server entry sets),
next to the dev behaviour it changes nothing about; and prod mode itself is gone."""
from __future__ import annotations

import importlib
import logging
import sys

import pytest
from httpx import ASGITransport, AsyncClient

from tests.server.test_token_bootstrap import _app_after_bootstrap, _reset_bootstrap_token  # noqa: F401

_ENV = ("ARSLAN_ENV", "ARSLAN_SECRET_KEY", "ARSLAN_API_TOKEN", "ARSLAN_PACKAGED", "ARSLAN_ALLOWED_ORIGINS", "ARSLAN_ALLOWED_HOSTS",
        "ARSLAN_ALLOW_INSECURE_SECRETS", "ARSLAN_TEST_ROUTES")


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


# 1 ── no secret: refuse to start, whatever ARSLAN_ALLOW_INSECURE_SECRETS says ─────────────────────────

@pytest.mark.parametrize("insecure", ["", "1"])
def test_a_packaged_server_with_no_secret_refuses_to_start(monkeypatch, insecure):
    env = {"ARSLAN_PACKAGED": "1", "ARSLAN_SECRET_KEY": "  "}
    if insecure:
        env["ARSLAN_ALLOW_INSECURE_SECRETS"] = insecure
    config = _config(monkeypatch, **env)
    import server.main as main
    with pytest.raises(RuntimeError, match="refusing to start"):
        main._validate_settings(config.settings, active_token="tok", log=logging.getLogger("t"))


def test_the_insecure_store_switch_is_ignored_when_packaged(monkeypatch):
    from server import crypto
    _config(monkeypatch, ARSLAN_ALLOW_INSECURE_SECRETS="1")
    assert crypto.insecure_writes_allowed() is True                      # a bare dev run may opt in
    _config(monkeypatch, ARSLAN_ALLOW_INSECURE_SECRETS="1", ARSLAN_PACKAGED="1")
    assert crypto.insecure_writes_allowed() is False


def test_a_dev_server_with_no_secret_still_starts(monkeypatch):
    config = _config(monkeypatch, ARSLAN_SECRET_KEY="")
    import server.main as main
    main._validate_settings(config.settings, active_token="", log=logging.getLogger("t"))   # no raise


# 2 ── an inherited ARSLAN_PACKAGED=0 cannot turn auth off ────────────────────────────────────────────

def test_the_frozen_entry_assigns_packaged_whatever_was_inherited(monkeypatch):
    sys.path.insert(0, "packaging")
    try:
        import server_entry
    finally:
        sys.path.remove("packaging")
    import os
    for var in ("ARSLAN_DATA_DIR", "ARSLAN_DB_PATH", "ARSLAN_API_TOKEN", "ARSLAN_ENV",   # _sanitize_env pops these
                "ARSLAN_ALLOWED_ORIGINS", "ARSLAN_ALLOWED_HOSTS"):
        if var in os.environ:
            monkeypatch.setenv(var, os.environ[var])                       # so undo() puts them back
        else:
            monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("ARSLAN_PACKAGED", "0")
    monkeypatch.setenv("ARSLAN_ENV", "prod")                   # inherited from a shell: dropped, not fatal
    monkeypatch.setenv("ARSLAN_ALLOWED_ORIGINS", "https://a.example")
    monkeypatch.setenv("ARSLAN_ALLOWED_HOSTS", "a.example")
    monkeypatch.setattr(server_entry, "_point_static_dir_into_the_bundle", lambda: None)
    server_entry._sanitize_env()
    # one key at a time: an assertion on os.environ itself prints the whole environment, keys included
    assert os.environ.get("ARSLAN_PACKAGED") == "1"
    assert os.environ.get("ARSLAN_ENV") is None
    assert os.environ.get("ARSLAN_ALLOWED_ORIGINS") is None
    assert os.environ.get("ARSLAN_ALLOWED_HOSTS") is None


# 3 ── no cross-origin by default ─────────────────────────────────────────────────────────────────────

def test_a_packaged_server_allows_no_other_origin_by_default(monkeypatch):
    assert _config(monkeypatch, ARSLAN_PACKAGED="1").settings.allowed_origins == ()
    assert _config(monkeypatch).settings.allowed_origins                # dev: the vite dev server
    explicit = _config(monkeypatch, ARSLAN_ALLOWED_ORIGINS="https://a.example")
    assert explicit.settings.allowed_origins == ("https://a.example",)  # a dev bind may name its own


def test_a_packaged_server_ignores_the_override_variables(monkeypatch):
    # Cloud audit on C11: they were read before `packaged`, so a value inherited from a shell replaced the packaged defaults.
    inherited = _config(monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_ALLOWED_ORIGINS="https://a.example",
                        ARSLAN_ALLOWED_HOSTS="a.example").settings
    assert inherited.allowed_origins == ()
    assert inherited.allowed_hosts == ("localhost", "127.0.0.1")


def test_a_packaged_app_with_both_overrides_set_still_answers_no_cross_origin_caller(monkeypatch):
    """The whole app, not the settings: CORS, the Host check and the WebSocket Origin check."""
    from fastapi.testclient import TestClient
    _config(monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_SECRET_KEY="x" * 32, ARSLAN_API_TOKEN="tok",
            ARSLAN_ALLOWED_ORIGINS="https://a.example", ARSLAN_ALLOWED_HOSTS="a.example")
    import server.security as security
    importlib.reload(security)
    import server.main as main
    client = TestClient(main.create_app(), base_url="http://localhost")
    preflight = client.options("/api/v1/health", headers={"Origin": "https://a.example",
                                                         "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in preflight.headers
    simple = client.get("/api/v1/health", headers={"Origin": "https://a.example"})
    assert simple.status_code == 200 and "access-control-allow-origin" not in simple.headers
    assert client.get("http://a.example/api/v1/health").status_code == 400          # its Host is not trusted
    assert security.ws_origin_allowed("https://a.example", "127.0.0.1:8000") is False
    _config(monkeypatch, ARSLAN_ALLOWED_ORIGINS="https://a.example")                 # the same origin in dev is allowed:
    importlib.reload(security)                                                       # the test can tell the two apart
    dev = TestClient(main.create_app(), base_url="http://localhost")
    assert dev.get("/api/v1/health", headers={"Origin": "https://a.example"}).headers.get(
        "access-control-allow-origin") == "https://a.example"


def test_a_packaged_server_trusts_only_localhost_hosts(monkeypatch):
    # C11 review F1: no test-harness host (t, test, testserver) in the desktop app's TrustedHost list.
    assert _config(monkeypatch, ARSLAN_PACKAGED="1").settings.allowed_hosts == ("localhost", "127.0.0.1")
    assert "testserver" in _config(monkeypatch).settings.allowed_hosts            # dev keeps the harness hosts


# 4 ── a WebSocket with no Origin is refused ──────────────────────────────────────────────────────────

def test_a_packaged_server_refuses_a_websocket_with_no_origin(monkeypatch):
    import server.security as security
    _config(monkeypatch, ARSLAN_PACKAGED="1")
    importlib.reload(security)
    assert security.ws_origin_allowed(None, "127.0.0.1:8000") is False
    assert security.ws_origin_allowed("http://127.0.0.1:8000", "127.0.0.1:8000") is True    # same origin
    assert security.ws_origin_allowed("http://localhost:5173", "127.0.0.1:8000") is False
    _config(monkeypatch)
    importlib.reload(security)
    assert security.ws_origin_allowed(None, "127.0.0.1:8000") is True                       # dev


# 5 ── no test routes ─────────────────────────────────────────────────────────────────────────────────

def test_a_packaged_server_registers_no_test_route(monkeypatch):
    from tests.route_introspection import iter_route_paths
    _config(monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_TEST_ROUTES="1", ARSLAN_SECRET_KEY="x" * 32)
    import server.main as main
    assert "/api/v1/_test/seed_spawn" not in iter_route_paths(main.create_app())


# 6 ── a new MCP token needs the current access token ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generating_or_disabling_an_mcp_token_needs_the_current_access_token(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    from server.services import settings_service
    app, auth = _app_after_bootstrap(monkeypatch, tmp_path, ARSLAN_PACKAGED="1")
    monkeypatch.setattr(settings_service, "mcp_server_enabled", AsyncMock(return_value=False))
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    current = auth.active_token()
    assert current
    transport = ASGITransport(app=app, client=("127.0.0.1", 5001))
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        bare = await c.post("/api/v1/settings/mcp-token/generate")
        wrong = await c.post("/api/v1/settings/mcp-token/generate", headers={"Authorization": "Bearer nope"})
        right = await c.post("/api/v1/settings/mcp-token/generate", headers={"Authorization": f"Bearer {current}"})
    assert (bare.status_code, wrong.status_code) == (401, 401)
    assert right.status_code == 200 and right.json()["token"]
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        off_bare = await c.post("/api/v1/settings/mcp-token/disable")
        off_right = await c.post("/api/v1/settings/mcp-token/disable", headers={"Authorization": f"Bearer {current}"})
    assert off_bare.status_code == 401 and off_right.status_code == 200   # C11 review F2


# ── prod mode is gone ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["prod", "PROD", "staging"])
def test_arslan_env_other_than_dev_refuses_to_start(monkeypatch, value):
    config = _config(monkeypatch, ARSLAN_ENV=value, ARSLAN_SECRET_KEY="x" * 32)
    import server.main as main
    with pytest.raises(RuntimeError, match="no longer supported"):
        main._validate_settings(config.settings, active_token="tok", log=logging.getLogger("t"))
    assert not hasattr(config.settings, "is_prod")
