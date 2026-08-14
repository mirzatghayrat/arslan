"""Step 3's seams: encrypted token storage, and the session actually using it.

STORAGE RULING (spec ③ §2.1): tokens ride the EXISTING crypto path — the same
crypto.encrypt the MCPServer.env secrets use — into the EXISTING Setting table.
No new table, no new cipher route: spec ⓪ spent a round collapsing this family
to one path, and a sixth consumer with its own route is how it un-collapses.

WHAT THE SESSION TEST PINS: `auth=` reaching streamablehttp_client. The recon
line that started spec ③ was "the SDK does PKCE; we fail to pass one argument" —
so the one assertion that matters is that the argument is now passed, and only
when tokens exist (a tokenless server must behave byte-for-byte as today).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Setting
from server.mcp.oauth_flow import EncryptedTokenStorage, has_tokens


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    # House pattern (test_settings.py:59): crypto reads config.settings at CALL
    # time, so reloading config after setenv is sufficient — and reloading crypto
    # itself would reset the process salt, which now raises by design.
    import importlib

    import server.config as config

    monkeypatch.setenv("ARSLAN_SECRET_KEY", "test-oauth-secret")
    importlib.reload(config)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'o.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


TOKENS = OAuthToken(access_token="at-123", token_type="Bearer", refresh_token="rt-456")
CLIENT = OAuthClientInformationFull(
    client_id="cid", redirect_uris=["http://127.0.0.1:1234/callback"],
)


class TestEncryptedTokenStorage:
    async def test_round_trips_tokens_and_client_info(self, maker):
        s = EncryptedTokenStorage(server_id=7)
        assert await s.get_tokens() is None
        await s.set_tokens(TOKENS)
        await s.set_client_info(CLIENT)
        back = await s.get_tokens()
        assert back is not None and back.access_token == "at-123"
        info = await s.get_client_info()
        assert info is not None and info.client_id == "cid"
        assert await has_tokens(7) is True
        assert await has_tokens(8) is False

    async def test_what_hits_the_database_is_ciphertext(self, maker):
        """The property, not the plumbing: the raw row must not contain the
        token. A storage that "uses the crypto module" but writes plaintext
        would pass every round-trip test ever written."""
        s = EncryptedTokenStorage(server_id=7)
        await s.set_tokens(TOKENS)
        async with maker() as db:
            rows = (await db.execute(select(Setting))).scalars().all()
        blob = " ".join((r.value or "") + (r.key or "") for r in rows)
        assert "at-123" not in blob
        assert "rt-456" not in blob

    async def test_two_servers_do_not_share_tokens(self, maker):
        a, b = EncryptedTokenStorage(server_id=1), EncryptedTokenStorage(server_id=2)
        await a.set_tokens(TOKENS)
        assert await b.get_tokens() is None

    async def test_an_undecryptable_blob_reads_as_absent_not_as_a_crash(self, maker, monkeypatch):
        """Same stance as MCPServer.env: a token written under a different secret
        must degrade to 'no tokens' (the flow re-runs) rather than take the whole
        session path down."""
        s = EncryptedTokenStorage(server_id=7)
        await s.set_tokens(TOKENS)
        async with maker() as db:
            row = (await db.execute(select(Setting))).scalars().first()
            row.value = "not-ciphertext"
            await db.commit()
        assert await s.get_tokens() is None


class TestSessionAttachesAuth:
    @pytest_asyncio.fixture
    async def capture(self, monkeypatch, maker):
        """Capture what _open_session passes to streamablehttp_client."""
        from server.mcp import session as sess

        seen: dict = {}

        class _FakeCtx:
            async def __aenter__(self):
                raise RuntimeError("stop-after-capture")
            async def __aexit__(self, *a):
                return False

        def fake_client(url, headers=None, auth=None, **kw):
            seen.update(url=url, headers=headers, auth=auth)
            return _FakeCtx()

        monkeypatch.setattr(sess, "streamablehttp_client", fake_client)
        return seen

    async def test_no_tokens_means_no_auth_argument(self, capture):
        from server.mcp.session import manager

        with pytest.raises(Exception):
            await manager._open_session(
                {"id": 5, "transport": "http", "url": "http://mcp.x/mcp", "env": {}}
            )
        assert capture["auth"] is None, (
            "a server without stored tokens must open exactly as it does today"
        )

    async def test_stored_tokens_attach_an_oauth_provider(self, capture):
        s = EncryptedTokenStorage(server_id=5)
        await s.set_tokens(TOKENS)
        await s.set_client_info(CLIENT)
        from server.mcp.session import manager

        with pytest.raises(Exception):
            await manager._open_session(
                {"id": 5, "transport": "http", "url": "http://mcp.x/mcp", "env": {}}
            )
        assert capture["auth"] is not None, (
            "tokens exist and the client still went out bare — the one missing "
            "argument the whole spec was about"
        )


class TestAuthorizeEndpoint:
    """POST /mcp/servers/{id}/oauth/authorize — the browser URL out, the outcome
    pollable. Endpoint-level, because a flow module nobody routed is a feature
    nobody has."""

    @pytest_asyncio.fixture
    async def client(self, maker, monkeypatch):
        from httpx import ASGITransport, AsyncClient

        from server.db.models import MCPServer
        from server.main import create_app

        async with maker() as db:
            db.add(MCPServer(id=3, label="remote", transport="http",
                             url="http://mcp.x/mcp", command="", args=[], env=None,
                             status="registered"))
            await db.commit()
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://t") as c:
            yield c

    async def test_returns_the_auth_url_and_reports_done(self, client, monkeypatch):
        from server.mcp import oauth_flow

        async def fake_authorize(server, *, on_auth_url, timeout=180.0):
            await on_auth_url("https://auth.example/authorize?client_id=x")

        monkeypatch.setattr(oauth_flow, "authorize", fake_authorize)
        r = await client.post("/api/v1/mcp/servers/3/oauth/authorize")
        assert r.status_code == 200, r.text
        assert r.json()["auth_url"].startswith("https://auth.example/")

        import asyncio as _a
        for _ in range(50):
            st = (await client.get("/api/v1/mcp/servers/3/oauth/status")).json()
            if st["state"] == "done":
                break
            await _a.sleep(0.02)
        assert st["state"] == "done"

    async def test_a_failed_flow_reports_error_not_a_hang(self, client, monkeypatch):
        from server.mcp import oauth_flow

        async def fake_authorize(server, *, on_auth_url, timeout=180.0):
            await on_auth_url("https://auth.example/a")
            raise RuntimeError("authorization refused: access_denied")

        monkeypatch.setattr(oauth_flow, "authorize", fake_authorize)
        await client.post("/api/v1/mcp/servers/3/oauth/authorize")
        import asyncio as _a
        for _ in range(50):
            st = (await client.get("/api/v1/mcp/servers/3/oauth/status")).json()
            if st["state"] == "error":
                break
            await _a.sleep(0.02)
        assert st["state"] == "error"
        assert "access_denied" in st["error"]

    async def test_unknown_server_is_404(self, client):
        r = await client.post("/api/v1/mcp/servers/999/oauth/authorize")
        assert r.status_code == 404
