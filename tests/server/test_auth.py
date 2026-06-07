"""Token authentication tests for REST and WebSocket."""
import importlib

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def _make_client(monkeypatch, token: str):
    """Build a client whose app sees ARSLAN_API_TOKEN=token."""
    monkeypatch.setenv("ARSLAN_API_TOKEN", token)
    import server.config as config

    importlib.reload(config)
    import server.auth as auth

    importlib.reload(auth)
    import server.main as main

    importlib.reload(main)
    app = main.create_app()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_protected_route_rejects_missing_token(monkeypatch):
    async with _make_client(monkeypatch, "secret123") as client:
        resp = await client.get("/api/v1/_authcheck")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_accepts_valid_token(monkeypatch):
    async with _make_client(monkeypatch, "secret123") as client:
        resp = await client.get(
            "/api/v1/_authcheck",
            headers={"Authorization": "Bearer secret123"},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_disabled_when_token_unset(monkeypatch):
    async with _make_client(monkeypatch, "") as client:
        resp = await client.get("/api/v1/_authcheck")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_validate_ws_token_logic(monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "tok")
    import server.config as config

    importlib.reload(config)
    import server.auth as auth

    importlib.reload(auth)
    assert auth.is_ws_token_valid("tok") is True
    assert auth.is_ws_token_valid("nope") is False
    assert auth.is_ws_token_valid(None) is False
