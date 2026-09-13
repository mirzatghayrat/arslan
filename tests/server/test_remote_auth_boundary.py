"""Actual peer addressing closes the bare uvicorn --host configuration gap."""
import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server import auth
from server.security import LocalOnlyWhenUnauthenticatedMiddleware


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "")
    app = FastAPI()
    app.add_middleware(LocalOnlyWhenUnauthenticatedMiddleware)

    @app.get("/probe")
    async def probe():
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        await ws.accept()
        await ws.send_text("ok")

    return app


@pytest.mark.parametrize("peer", ["192.0.2.8", "0.0.0.0", "2001:db8::1", "unknown"])
def test_remote_http_denied_without_token_even_with_local_host(app, peer):
    with TestClient(app, client=(peer, 51234)) as client:
        response = client.get("/probe", headers={"host": "localhost", "x-forwarded-for": "127.0.0.1"})
    assert response.status_code == 403


def test_remote_websocket_denied_without_token(app):
    with TestClient(app, client=("192.0.2.8", 51234)) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws"):
                pass
    assert exc.value.code == 1008


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1"])
def test_loopback_dev_stays_available(app, peer):
    with TestClient(app, client=(peer, 51234)) as client:
        assert client.get("/probe").status_code == 200
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_text() == "ok"


def test_configured_auth_hands_off_to_endpoint_guards(app, monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "explicit")
    with TestClient(app, client=("192.0.2.8", 51234)) as client:
        assert client.get("/probe").status_code == 200


def test_real_app_installs_boundary(monkeypatch):
    from server.main import create_app
    monkeypatch.setattr(auth, "active_token", lambda: "")
    app = create_app()
    # No lifespan needed: rejection happens before any database access.
    client = TestClient(app, client=("192.0.2.8", 51234))
    assert client.get("/api/v1/health", headers={"host": "localhost"}).status_code == 403
