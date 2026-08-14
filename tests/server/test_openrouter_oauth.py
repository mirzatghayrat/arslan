"""OpenRouter sign-in: spec ③'s plumbing under a simpler, non-standard flow.

NOT the SDK's OAuthClientProvider — OpenRouter has no client_id, no token
endpoint, no DCR; just an auth page, a code, and one JSON exchange. What carries
over from ③ is the infrastructure and its rules: the loopback catcher, the
pinned HTTP path for every outbound call, and "the auth URL travels backend →
response → shell doorway and nowhere else".
"""
from __future__ import annotations

import importlib

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ProviderConfig
from server.services import openrouter_oauth as oro


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    import server.config as config

    monkeypatch.setenv("ARSLAN_SECRET_KEY", "test-oro-secret")
    importlib.reload(config)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'r.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


class TestAuthUrl:
    def test_carries_pkce_and_the_loopback_callback(self):
        url = oro._auth_url("http://127.0.0.1:49152/callback", "challenge-abc")
        assert url.startswith("https://openrouter.ai/auth?")
        assert "code_challenge=challenge-abc" in url
        assert "code_challenge_method=S256" in url
        assert "callback_url=http%3A%2F%2F127.0.0.1%3A49152%2Fcallback" in url

    def test_challenge_is_s256_of_the_verifier(self):
        # RFC 7636: BASE64URL(SHA256(verifier)), no padding. Pinned with a known
        # vector so a plain-text "challenge" cannot sneak in as an implementation.
        import base64
        import hashlib

        verifier, challenge = oro._pkce_pair()
        expect = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        assert challenge == expect
        assert len(verifier) >= 43  # RFC 7636 minimum


class TestFreeModelChoice:
    MODELS = {"data": [
        {"id": "anthropic/claude-sonnet-5", "pricing": {"prompt": "0.000003"}},
        {"id": "meta-llama/llama-3.3-70b:free", "pricing": {"prompt": "0"}},
        {"id": "deepseek/deepseek-chat-v3:free", "pricing": {"prompt": "0"}},
    ]}

    def test_prefers_a_free_deepseek(self):
        assert oro._pick_free_model(self.MODELS) == "deepseek/deepseek-chat-v3:free"

    def test_any_free_model_beats_a_paid_one(self):
        models = {"data": [
            {"id": "anthropic/claude-sonnet-5", "pricing": {"prompt": "0.000003"}},
            {"id": "meta-llama/llama-3.3-70b:free", "pricing": {"prompt": "0"}},
        ]}
        assert oro._pick_free_model(models) == "meta-llama/llama-3.3-70b:free"

    def test_no_free_model_returns_none_not_a_guess(self):
        models = {"data": [{"id": "x/paid", "pricing": {"prompt": "1"}}]}
        assert oro._pick_free_model(models) is None

    def test_garbage_returns_none(self):
        assert oro._pick_free_model({}) is None
        assert oro._pick_free_model({"data": "nope"}) is None


class TestTheExchange:
    async def test_flow_lands_an_encrypted_config(self, maker, monkeypatch):
        """End to end minus the human: code arrives → key exchanged → config
        row exists, provider=openrouter, key ENCRYPTED (the raw row must not
        contain it), model is the free pick."""

        async def fake_request(method, url, **kw):
            req = httpx.Request(method, url)
            if url.endswith("/auth/keys"):
                assert kw.get("json", {}).get("code") == "code-1"
                assert kw.get("json", {}).get("code_verifier")
                return httpx.Response(200, json={"key": "sk-or-v1-SECRET"}, request=req)
            if url.endswith("/models"):
                return httpx.Response(200, json=TestFreeModelChoice.MODELS, request=req)
            raise AssertionError(f"unexpected url {url}")

        monkeypatch.setattr(oro.net_pin, "pinned_request", fake_request)

        class _Catcher:
            port = 49152
            redirect_uri = "http://127.0.0.1:49152/callback"

            def __init__(self):
                import asyncio

                self.result = asyncio.get_event_loop().create_future()
                self.result.set_result(("code-1", ""))

            def cancel(self):
                self.cancelled = True

        async def fake_catch(**kw):
            return _Catcher()

        monkeypatch.setattr(oro, "catch_authorization_code", fake_catch)

        seen_url: list[str] = []

        async def on_auth_url(u):
            seen_url.append(u)

        result = await oro.run_flow(on_auth_url=on_auth_url)
        assert seen_url and "code_challenge=" in seen_url[0]
        assert result["model"] == "deepseek/deepseek-chat-v3:free"
        assert result["free_model"] is True

        async with maker() as db:
            rows = (await db.execute(select(ProviderConfig))).scalars().all()
        assert len(rows) == 1
        assert rows[0].provider == "openrouter"
        assert rows[0].is_primary is True
        assert "sk-or-v1-SECRET" not in (rows[0].api_key or ""), (
            "the key reached the database in plaintext"
        )

    async def test_no_free_model_falls_back_and_says_so(self, maker, monkeypatch):
        async def fake_request(method, url, **kw):
            req = httpx.Request(method, url)
            if url.endswith("/auth/keys"):
                return httpx.Response(200, json={"key": "sk-or-v1-K"}, request=req)
            return httpx.Response(500, text="listing down", request=req)

        monkeypatch.setattr(oro.net_pin, "pinned_request", fake_request)

        class _Catcher:
            port = 1
            redirect_uri = "http://127.0.0.1:1/callback"

            def __init__(self):
                import asyncio

                self.result = asyncio.get_event_loop().create_future()
                self.result.set_result(("c", ""))

            def cancel(self): ...

        async def fake_catch(**kw):
            return _Catcher()

        monkeypatch.setattr(oro, "catch_authorization_code", fake_catch)

        result = await oro.run_flow(on_auth_url=lambda u: _noop())
        assert result["free_model"] is False, (
            "the fallback must be STATED — a silent paid default 402s on the "
            "exact user this feature exists for"
        )

    async def test_listing_ok_but_no_free_model_also_says_so(self, maker, monkeypatch):
        """The OTHER fallback path: /models answers fine but every model is
        paid. The first mutation run exposed that only the listing-failed path
        was covered — the mutated free=True sailed through here."""
        async def fake_request(method, url, **kw):
            req = httpx.Request(method, url)
            if url.endswith("/auth/keys"):
                return httpx.Response(200, json={"key": "sk-or-v1-K"}, request=req)
            return httpx.Response(
                200, json={"data": [{"id": "x/paid", "pricing": {"prompt": "1"}}]},
                request=req,
            )

        monkeypatch.setattr(oro.net_pin, "pinned_request", fake_request)

        class _Catcher:
            port = 1
            redirect_uri = "http://127.0.0.1:1/callback"

            def __init__(self):
                import asyncio

                self.result = asyncio.get_event_loop().create_future()
                self.result.set_result(("c", ""))

            def cancel(self): ...

        async def fake_catch(**kw):
            return _Catcher()

        monkeypatch.setattr(oro, "catch_authorization_code", fake_catch)
        result = await oro.run_flow(on_auth_url=lambda u: _noop())
        assert result["free_model"] is False
        assert result["model"] == oro._FALLBACK_MODEL

    async def test_a_refused_exchange_raises_not_half_a_config(self, maker, monkeypatch):
        async def fake_request(method, url, **kw):
            return httpx.Response(403, text="bad code", request=httpx.Request(method, url))

        monkeypatch.setattr(oro.net_pin, "pinned_request", fake_request)

        class _Catcher:
            port = 1
            redirect_uri = "http://127.0.0.1:1/callback"

            def __init__(self):
                import asyncio

                self.result = asyncio.get_event_loop().create_future()
                self.result.set_result(("c", ""))

            def cancel(self): ...

        async def fake_catch(**kw):
            return _Catcher()

        monkeypatch.setattr(oro, "catch_authorization_code", fake_catch)
        with pytest.raises(Exception):
            await oro.run_flow(on_auth_url=lambda u: _noop())
        async with maker() as db:
            rows = (await db.execute(select(ProviderConfig))).scalars().all()
        assert rows == [], "a failed exchange must not leave a keyless config behind"


async def _noop():
    return None


def test_no_bare_http_client_in_the_flow():
    """Absence, which has no behaviour to observe (the acknowledged exception):
    every outbound call rides net_pin. A bare client here would be the first
    unpinned outbound request since the SearXNG round closed that class."""
    import inspect

    src = inspect.getsource(oro)
    assert "httpx.AsyncClient(" not in src
    assert "requests." not in src


class TestEndpoints:
    @pytest_asyncio.fixture
    async def client(self, maker):
        from httpx import ASGITransport, AsyncClient

        from server.main import create_app

        async with AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://t"
        ) as c:
            yield c

    async def test_start_returns_the_auth_url_and_status_lands_done(self, client, monkeypatch):
        async def fake_flow(*, on_auth_url, timeout=180.0):
            await on_auth_url("https://openrouter.ai/auth?code_challenge=x")
            return {"config_id": 1, "model": "deepseek/x:free", "free_model": True}

        monkeypatch.setattr(oro, "run_flow", fake_flow)
        r = await client.post("/api/v1/settings/openrouter/oauth/start")
        assert r.status_code == 200, r.text
        assert r.json()["auth_url"].startswith("https://openrouter.ai/auth?")

        import asyncio as _a

        for _ in range(50):
            st = (await client.get("/api/v1/settings/openrouter/oauth/status")).json()
            if st["state"] == "done":
                break
            await _a.sleep(0.02)
        assert st["state"] == "done"
        assert st["free_model"] is True

    async def test_a_refusal_reports_error(self, client, monkeypatch):
        async def fake_flow(*, on_auth_url, timeout=180.0):
            await on_auth_url("https://openrouter.ai/auth?x")
            raise RuntimeError("authorization refused: access_denied")

        monkeypatch.setattr(oro, "run_flow", fake_flow)
        await client.post("/api/v1/settings/openrouter/oauth/start")
        import asyncio as _a

        for _ in range(50):
            st = (await client.get("/api/v1/settings/openrouter/oauth/status")).json()
            if st["state"] == "error":
                break
            await _a.sleep(0.02)
        assert "access_denied" in st["error"]
