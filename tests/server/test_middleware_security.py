"""S1 OSS-safety middleware: Host validation, CORS, and WS Origin checks.

A localhost-bound service with no Host validation is reachable by any web page
the user visits via DNS rebinding, and browsers can open cross-site WebSockets
freely (WS is exempt from the same-origin fetch rules). These tests pin the
fail-closed policy while proving the daily dev flow (vite :5173 origin, the
no-Origin non-browser client, the TestClient `testserver` host) still works.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

_ENV_KEYS = (
    "ARSLAN_ENV",
    "ARSLAN_ALLOWED_HOSTS",
    "ARSLAN_ALLOWED_ORIGINS",
    "ARSLAN_API_TOKEN",
    "ARSLAN_SECRET_KEY",
)


def _reload(monkeypatch, **env):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    import server.config as config

    importlib.reload(config)
    import server.security as security

    importlib.reload(security)
    return config, security


def _dev_app(monkeypatch, **env):
    _reload(monkeypatch, **env)
    from server.main import create_app

    return create_app()


# --- TrustedHost: foreign Host rejected, localhost/testserver allowed ---------


def test_foreign_host_rejected(monkeypatch):
    client = TestClient(_dev_app(monkeypatch))
    resp = client.get("http://evil.com/api/v1/health")
    assert resp.status_code == 400


def test_localhost_host_allowed(monkeypatch):
    client = TestClient(_dev_app(monkeypatch))
    resp = client.get("http://localhost/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_127_host_allowed(monkeypatch):
    client = TestClient(_dev_app(monkeypatch))
    resp = client.get("http://127.0.0.1:8741/api/v1/health")
    assert resp.status_code == 200


def test_testserver_host_allowed(monkeypatch):
    # The Starlette TestClient default Host; same-origin request must still 200.
    client = TestClient(_dev_app(monkeypatch))
    resp = client.get("/api/v1/health")  # Host: testserver
    assert resp.status_code == 200


def test_prod_allowed_hosts_from_env(monkeypatch):
    client = TestClient(
        _dev_app(
            monkeypatch,
            ARSLAN_ENV="prod",
            ARSLAN_SECRET_KEY="x" * 32,
            ARSLAN_API_TOKEN="tok",
            ARSLAN_ALLOWED_HOSTS="app.example.com,localhost",
        )
    )
    assert client.get("http://app.example.com/api/v1/health").status_code == 200
    assert client.get("http://localhost/api/v1/health").status_code == 200
    # testserver is NOT in the prod allowlist → rejected.
    assert client.get("http://testserver/api/v1/health").status_code == 400


# --- ws_origin_allowed helper -------------------------------------------------


def test_ws_origin_allows_vite_dev_origins(monkeypatch):
    _config, security = _reload(monkeypatch)
    assert security.ws_origin_allowed("http://localhost:5173") is True
    assert security.ws_origin_allowed("http://127.0.0.1:5173") is True


def test_ws_origin_rejects_foreign(monkeypatch):
    _config, security = _reload(monkeypatch)
    assert security.ws_origin_allowed("http://evil.com") is False
    assert security.ws_origin_allowed("https://attacker.example") is False


def test_ws_origin_same_origin_true(monkeypatch):
    _config, security = _reload(monkeypatch)
    # Origin host:port equals the request's own Host header → same-origin.
    assert security.ws_origin_allowed("http://myhost:9000", host="myhost:9000") is True


def test_ws_origin_no_header_allowed_in_dev(monkeypatch):
    # Non-browser clients (the smoke's websockets lib, curl) send no Origin.
    _config, security = _reload(monkeypatch)
    assert security.ws_origin_allowed(None) is True
    assert security.ws_origin_allowed("") is True


def test_ws_origin_prod_fail_closed(monkeypatch):
    _config, security = _reload(
        monkeypatch,
        ARSLAN_ENV="prod",
        ARSLAN_SECRET_KEY="x" * 32,
        ARSLAN_API_TOKEN="tok",
        ARSLAN_ALLOWED_ORIGINS="https://app.example.com",
    )
    # prod requires an Origin (no implicit no-Origin pass, no implicit localhost).
    assert security.ws_origin_allowed(None) is False
    assert security.ws_origin_allowed("http://localhost:5173") is False
    # only the configured allowlist + genuine same-origin get through.
    assert security.ws_origin_allowed("https://app.example.com") is True
    assert (
        security.ws_origin_allowed("https://packaged.local", host="packaged.local")
        is True
    )


# --- WS handshake integration: a foreign Origin is refused before accept ------


@pytest.mark.parametrize("path", ["/ws/arslan/main", "/ws/chat/1", "/ws/sandbox/1"])
def test_ws_foreign_origin_handshake_rejected(monkeypatch, path):
    # The Origin guard runs BEFORE ws.accept()/any DB work, so a cross-site open
    # closes the handshake with 4403 without touching the database.
    client = TestClient(_dev_app(monkeypatch))
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(path, headers={"origin": "http://evil.com"}) as ws:
            ws.receive_json()
    assert exc.value.code == 4403


# --- same-origin HTTP still serves through the full stack ---------------------


def test_same_origin_health_ok(monkeypatch):
    client = TestClient(_dev_app(monkeypatch))
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
