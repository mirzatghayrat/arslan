"""S1-3 env-split access-token bootstrap.

Goal: a fresh install must be SAFE BY DEFAULT for packaged / prod / non-loopback
binds (auto-generate + enforce a token), while dev+localhost stays ZERO-friction
(no token file, ``require_auth`` a no-op). Covers BOTH trigger paths (prod env,
packaged flag) + non-loopback bind + reset endpoint + no cross-origin token leak.

Isolation notes:
  * We reload ``server.config`` only (never ``server.auth``) so the singleton auth
    module — the one every router/WS handler imported — stays identical and reads
    the ``_bootstrapped_token`` global that ``token_bootstrap`` sets. The autouse
    fixture clears that global after each test so no bootstrap leaks into the rest
    of the suite (which relies on the dev "empty token => no-op" flow).
"""
from __future__ import annotations

import importlib
import logging
import stat

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import ASGITransport, AsyncClient

_TOKEN_ENVS = (
    "ARSLAN_ENV", "ARSLAN_SECRET_KEY", "ARSLAN_API_TOKEN", "ARSLAN_BIND_HOST",
    "ARSLAN_PACKAGED", "ARSLAN_DATA_DIR", "HOST",
)


def _reload(monkeypatch, tmp_path, **env):
    """Reload config against a clean env + isolated data_dir. Returns (config, auth, tb)."""
    for key in _TOKEN_ENVS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import server.config as config

    importlib.reload(config)
    import server.auth as auth
    import server.token_bootstrap as tb

    return config, auth, tb


@pytest.fixture(autouse=True)
def _reset_bootstrap_token():
    """Clear the process-wide bootstrapped token before AND after each test."""
    import server.auth as auth

    auth.set_bootstrapped_token(None)
    yield
    auth.set_bootstrapped_token(None)


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# --- (a) dev + localhost + no token => zero-friction ------------------------


@pytest.mark.asyncio
async def test_dev_localhost_no_token_stays_open(monkeypatch, tmp_path):
    config, auth, tb = _reload(monkeypatch, tmp_path)  # env unset => dev, bind 127.0.0.1
    assert tb._needs_token(config.settings) is False

    token = tb.bootstrap_api_token(config.settings)
    assert token == ""
    assert auth.active_token() == ""
    # No token file is written in the dev zero-friction path.
    assert not (tmp_path / "api_token").exists()
    # require_auth is a no-op (a token-less request succeeds), WS stays open.
    assert await auth.require_auth(None) is None
    assert auth.is_ws_token_valid(None) is True


# --- (b) prod build => auto-generate & enforce ------------------------------


@pytest.mark.asyncio
async def test_prod_no_token_generates_and_enforces(monkeypatch, tmp_path, caplog):
    config, auth, tb = _reload(monkeypatch, tmp_path, ARSLAN_ENV="prod", ARSLAN_SECRET_KEY="x" * 32)
    assert tb._needs_token(config.settings) is True

    with caplog.at_level(logging.WARNING):
        token = tb.bootstrap_api_token(config.settings)

    assert token  # a real token was generated
    tf = tmp_path / "api_token"
    assert tf.exists() and tf.read_text().strip() == token
    assert stat.S_IMODE(tf.stat().st_mode) == 0o600  # not world/group readable
    # Printed once at boot so a packaged user can copy it.
    assert any("access token" in r.message.lower() and token in r.message for r in caplog.records)

    # Enforcement is now live: token-less request rejected, bootstrapped token accepted.
    assert auth.active_token() == token
    with pytest.raises(HTTPException) as exc:
        await auth.require_auth(None)
    assert exc.value.status_code == 401
    assert await auth.require_auth(_creds(token)) is None
    assert auth.is_ws_token_valid(token) is True
    assert auth.is_ws_token_valid("wrong") is False


@pytest.mark.asyncio
async def test_prod_second_boot_reuses_same_token(monkeypatch, tmp_path):
    config, _auth, tb = _reload(monkeypatch, tmp_path, ARSLAN_ENV="prod", ARSLAN_SECRET_KEY="x" * 32)
    first = tb.bootstrap_api_token(config.settings)
    assert first

    # A second boot (same data_dir) must READ the persisted token, never regenerate.
    config, auth, tb = _reload(monkeypatch, tmp_path, ARSLAN_ENV="prod", ARSLAN_SECRET_KEY="x" * 32)
    second = tb.bootstrap_api_token(config.settings)
    assert second == first
    assert auth.active_token() == first


# --- packaged flag path (Tauri build sets ARSLAN_PACKAGED=1) ----------------


@pytest.mark.asyncio
async def test_packaged_flag_generates_and_enforces(monkeypatch, tmp_path):
    config, auth, tb = _reload(monkeypatch, tmp_path, ARSLAN_PACKAGED="1")
    assert tb._needs_token(config.settings) is True

    token = tb.bootstrap_api_token(config.settings)
    assert token and (tmp_path / "api_token").exists()
    assert auth.active_token() == token
    with pytest.raises(HTTPException):
        await auth.require_auth(None)
    assert await auth.require_auth(_creds(token)) is None


# --- non-loopback bind path -------------------------------------------------


@pytest.mark.asyncio
async def test_non_loopback_bind_generates(monkeypatch, tmp_path):
    config, auth, tb = _reload(monkeypatch, tmp_path, ARSLAN_BIND_HOST="0.0.0.0")
    assert tb._needs_token(config.settings) is True
    token = tb.bootstrap_api_token(config.settings)
    assert token
    assert auth.active_token() == token


def test_loopback_host_classification():
    import server.token_bootstrap as tb

    for local in ("127.0.0.1", "::1", "localhost", "127.0.0.5", "[::1]"):
        assert tb.is_loopback_host(local) is True, local
    for remote in ("0.0.0.0", "192.168.1.10", "10.0.0.4", "example.com", ""):
        assert tb.is_loopback_host(remote) is False, remote


# --- explicit env token always wins (no bootstrap file) ---------------------


@pytest.mark.asyncio
async def test_explicit_env_token_wins_no_file(monkeypatch, tmp_path):
    config, auth, tb = _reload(
        monkeypatch, tmp_path,
        ARSLAN_ENV="prod", ARSLAN_SECRET_KEY="x" * 32, ARSLAN_API_TOKEN="explicit-tok",
    )
    token = tb.bootstrap_api_token(config.settings)
    assert token == "explicit-tok"
    assert not (tmp_path / "api_token").exists()  # explicit value => never persist a file
    assert auth.active_token() == "explicit-tok"


# --- Settings view/reset (condition 3): reachable + localhost-gated ---------


def _app_after_bootstrap(monkeypatch, tmp_path, **env):
    config, auth, tb = _reload(monkeypatch, tmp_path, **env)
    tb.bootstrap_api_token(config.settings)
    from server.main import create_app

    return create_app(), auth


@pytest.mark.asyncio
async def test_get_access_token_localhost_returns_value(monkeypatch, tmp_path):
    app, auth = _app_after_bootstrap(monkeypatch, tmp_path, ARSLAN_PACKAGED="1")
    transport = ASGITransport(app=app, client=("127.0.0.1", 5001))
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.get("/api/v1/settings/access-token")
    assert r.status_code == 200
    body = r.json()
    assert body["token_required"] is True
    assert body["token"] == auth.active_token()


@pytest.mark.asyncio
async def test_get_access_token_remote_does_not_leak(monkeypatch, tmp_path):
    app, auth = _app_after_bootstrap(monkeypatch, tmp_path, ARSLAN_PACKAGED="1")
    transport = ASGITransport(app=app, client=("203.0.113.9", 5555))
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.get("/api/v1/settings/access-token")
    assert r.status_code == 200
    body = r.json()
    # A remote/cross-origin caller learns that auth is required but NEVER the value.
    assert body["token_required"] is True
    assert body["token"] is None


@pytest.mark.asyncio
async def test_reset_access_token_localhost_rotates(monkeypatch, tmp_path):
    app, auth = _app_after_bootstrap(monkeypatch, tmp_path, ARSLAN_PACKAGED="1")
    old = auth.active_token()
    assert old
    transport = ASGITransport(app=app, client=("127.0.0.1", 5001))
    # FIX 3: reset now requires the caller to present the CURRENT token (the genuine
    # local operator who already read it via GET). A direct-loopback request carries no
    # forwarding header.
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.post("/api/v1/settings/access-token/reset",
                         headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 200
    new = r.json()["token"]
    assert new and new != old
    assert auth.active_token() == new
    # The old token stops working immediately; the new one is accepted.
    assert auth.is_ws_token_valid(old) is False
    assert auth.is_ws_token_valid(new) is True
    # Persisted to disk too (survives reboot).
    assert (tmp_path / "api_token").read_text().strip() == new


@pytest.mark.asyncio
async def test_reset_access_token_remote_forbidden(monkeypatch, tmp_path):
    app, auth = _app_after_bootstrap(monkeypatch, tmp_path, ARSLAN_PACKAGED="1")
    old = auth.active_token()
    transport = ASGITransport(app=app, client=("203.0.113.9", 5555))
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.post("/api/v1/settings/access-token/reset",
                         headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 403
    assert auth.active_token() == old  # a remote caller cannot rotate / lock out


# --- FIX 2: reset refuses when ARSLAN_API_TOKEN is env-managed (no dead mint) ----


@pytest.mark.asyncio
async def test_reset_refuses_when_env_token_set(monkeypatch, tmp_path):
    """An explicit ARSLAN_API_TOKEN always wins in auth.active_token(); minting a new
    bootstrapped token would rotate NOTHING (the env token still gates) and lock the
    user out. So reset must REFUSE with an actionable 409 and never mint."""
    app, auth = _app_after_bootstrap(
        monkeypatch, tmp_path, ARSLAN_API_TOKEN="explicit-tok", ARSLAN_ENV="prod",
        ARSLAN_SECRET_KEY="x" * 32)
    assert auth.active_token() == "explicit-tok"
    transport = ASGITransport(app=app, client=("127.0.0.1", 5001))
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.post("/api/v1/settings/access-token/reset",
                         headers={"Authorization": "Bearer explicit-tok"})
    assert r.status_code == 409
    assert "ARSLAN_API_TOKEN" in r.json()["detail"]
    # No mint happened: the env token is unchanged and still works; no file was written.
    assert auth.active_token() == "explicit-tok"
    assert auth.is_ws_token_valid("explicit-tok") is True
    assert not (tmp_path / "api_token").exists()


@pytest.mark.asyncio
async def test_get_reports_env_token_honestly(monkeypatch, tmp_path):
    """GET reports token_required:true, and hands the authoritative ENV token to a
    localhost caller (the honest, useful value — env is what actually gates)."""
    app, auth = _app_after_bootstrap(
        monkeypatch, tmp_path, ARSLAN_API_TOKEN="explicit-tok", ARSLAN_ENV="prod",
        ARSLAN_SECRET_KEY="x" * 32)
    transport = ASGITransport(app=app, client=("127.0.0.1", 5001))
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.get("/api/v1/settings/access-token")
    body = r.json()
    assert body["token_required"] is True
    assert body["token"] == "explicit-tok"


def test_reset_api_token_raises_under_env_token(monkeypatch, tmp_path):
    """Defense-in-depth: reset_api_token itself refuses to mint a dead token when the
    env manages the token, so no caller can silently lock the user out."""
    config, _auth, tb = _reload(
        monkeypatch, tmp_path, ARSLAN_API_TOKEN="explicit-tok")
    with pytest.raises(ValueError) as exc:
        tb.reset_api_token(config.settings)
    assert "ARSLAN_API_TOKEN" in str(exc.value)
    assert not (tmp_path / "api_token").exists()


# --- FIX 3: the localhost gate must reject X-Forwarded-For loopback spoofing ------


@pytest.mark.asyncio
async def test_get_rejects_forwarded_header_spoof(monkeypatch, tmp_path):
    """With uvicorn --proxy-headers, request.client.host reflects X-Forwarded-For, so a
    remote client behind a trusted proxy could spoof 127.0.0.1. A DIRECT loopback
    connection never carries a forwarding header, so its PRESENCE disqualifies the
    request — the token is not leaked."""
    app, auth = _app_after_bootstrap(monkeypatch, tmp_path, ARSLAN_PACKAGED="1")
    transport = ASGITransport(app=app, client=("127.0.0.1", 5001))
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.get("/api/v1/settings/access-token",
                        headers={"X-Forwarded-For": "127.0.0.1"})
    body = r.json()
    assert body["token_required"] is True
    assert body["token"] is None  # spoofed loopback learns required, never the value


@pytest.mark.asyncio
async def test_reset_rejects_forwarded_header_spoof(monkeypatch, tmp_path):
    app, auth = _app_after_bootstrap(monkeypatch, tmp_path, ARSLAN_PACKAGED="1")
    old = auth.active_token()
    transport = ASGITransport(app=app, client=("127.0.0.1", 5001))
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.post("/api/v1/settings/access-token/reset",
                         headers={"Authorization": f"Bearer {old}",
                                  "X-Forwarded-For": "127.0.0.1"})
    assert r.status_code == 403
    assert auth.active_token() == old  # spoofed loopback cannot rotate


@pytest.mark.asyncio
async def test_reset_requires_bearer_token(monkeypatch, tmp_path):
    """Even a genuine direct-loopback reset must present the CURRENT token, so a
    spoofed-loopback remote that also strips forwarding headers still can't rotate
    without knowing the token."""
    app, auth = _app_after_bootstrap(monkeypatch, tmp_path, ARSLAN_PACKAGED="1")
    old = auth.active_token()
    transport = ASGITransport(app=app, client=("127.0.0.1", 5001))
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        # No Authorization header -> rejected.
        r = await c.post("/api/v1/settings/access-token/reset")
    assert r.status_code == 401
    assert auth.active_token() == old
    # Wrong bearer -> rejected.
    async with AsyncClient(transport=transport, base_url="http://localhost") as c:
        r = await c.post("/api/v1/settings/access-token/reset",
                         headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401
    assert auth.active_token() == old
