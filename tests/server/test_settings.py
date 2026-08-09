"""Settings service and API tests, including secret masking."""
import importlib

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base


@pytest.mark.asyncio
async def test_list_providers_endpoint(client):
    resp = await client.get("/api/v1/settings/providers")
    assert resp.status_code == 200
    options = resp.json()
    keys = {o["key"] for o in options}
    # Tier-0 presets + native providers all surfaced for the dropdown
    assert {"openai", "deepseek", "qwen", "ollama"} <= keys
    assert {"anthropic", "gemini"} <= keys
    by_key = {o["key"]: o for o in options}
    assert by_key["deepseek"]["base_url"].startswith("https://api.deepseek.com")
    assert by_key["anthropic"]["native"] is True


@pytest.mark.asyncio
async def test_list_search_providers_endpoint(client):
    resp = await client.get("/api/v1/settings/search-providers")
    assert resp.status_code == 200
    providers = resp.json()
    # The keyless default leads the dropdown: it is the one that works on a machine
    # that has not signed up anywhere, so burying it under options that need a key
    # would put the only usable choice last.
    assert providers[0] == "duckduckgo"
    assert "tavily" in providers


@pytest.mark.asyncio
async def test_search_settings_roundtrip(client):
    resp = await client.put("/api/v1/settings", json={
        "search_provider": "tavily", "search_api_key": "tvly-secret-12345678",
    })
    assert resp.status_code == 200
    body = (await client.get("/api/v1/settings")).json()
    assert body["search_provider"] == "tavily"
    assert body["search_api_key"].endswith("5678") and "secret" not in body["search_api_key"]


@pytest_asyncio.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


def test_fernet_roundtrip(monkeypatch):
    # Only `config` is reloaded. crypto._active_secret() reads config.settings at CALL
    # time, so that is enough to change the active secret — and reloading crypto would
    # reset the process-wide PBKDF2 salt to None, which now raises rather than
    # silently deriving from a guess.
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "unit-test-secret")
    import server.config as config

    importlib.reload(config)
    import server.crypto as crypto

    token = crypto.encrypt("sk-abc123")
    assert token != "sk-abc123"
    assert crypto.decrypt(token) == "sk-abc123"


def test_mask_secret():
    from server.services.settings_service import mask_secret

    assert mask_secret("sk-1234567890") == "sk-...7890"
    assert mask_secret("") == ""
    assert mask_secret("short") == "***"


@pytest.mark.asyncio
async def test_set_and_get_settings_masks_key(session, monkeypatch):
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "unit-test-secret")
    import server.config as config

    importlib.reload(config)

    from server.services import settings_service

    importlib.reload(settings_service)

    await settings_service.update_settings(
        session,
        {"llm_provider": "openai", "llm_model": "gpt-4o", "llm_api_key": "sk-secret-9999"},
    )
    out = await settings_service.get_settings(session)
    assert out["llm_provider"] == "openai"
    assert out["llm_model"] == "gpt-4o"
    assert out["llm_api_key"] == "sk-...9999"  # masked
    # The raw, decrypted key is retrievable internally for LLM calls:
    raw = await settings_service.get_decrypted_api_key(session)
    assert raw == "sk-secret-9999"


@pytest.mark.asyncio
async def test_masked_echo_not_persisted(session, monkeypatch):
    """GET → PUT round-trip must never overwrite a real key with its masked echo.

    A client that GETs settings and PUTs the response body back unchanged would
    send the masked value (e.g. "sk-...9999") instead of the real key.  The
    service must detect the mask shape and skip the update so the stored
    plaintext is not silently corrupted.
    """
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "unit-test-secret")
    import server.config as config

    importlib.reload(config)

    from server.services import settings_service

    importlib.reload(settings_service)

    # --- llm_api_key (sk- prefix, long-form mask) ---
    real_llm_key = "sk-realkey-abcdefgh1234"
    await settings_service.update_settings(session, {"llm_api_key": real_llm_key})

    # Capture what a GET would return and PUT it straight back.
    out = await settings_service.get_settings(session)
    masked_llm = out["llm_api_key"]
    assert "..." in masked_llm, "expected long-form mask for llm_api_key"

    await settings_service.update_settings(session, {"llm_api_key": masked_llm})

    stored = await settings_service.get_decrypted(session, "llm_api_key")
    assert stored == real_llm_key, (
        f"llm_api_key was corrupted: expected {real_llm_key!r}, got {stored!r}"
    )

    # --- search_api_key (non-sk- prefix, long-form mask) ---
    real_search_key = "tvly-realkey-xyzw9876"
    await settings_service.update_settings(session, {"search_api_key": real_search_key})

    out = await settings_service.get_settings(session)
    masked_search = out["search_api_key"]
    assert "..." in masked_search, "expected long-form mask for search_api_key"

    await settings_service.update_settings(session, {"search_api_key": masked_search})

    stored = await settings_service.get_decrypted(session, "search_api_key")
    assert stored == real_search_key, (
        f"search_api_key was corrupted: expected {real_search_key!r}, got {stored!r}"
    )

    # --- literal "***" (short-key mask) must also be skipped ---
    await settings_service.update_settings(session, {"llm_api_key": "***"})
    stored = await settings_service.get_decrypted(session, "llm_api_key")
    assert stored == real_llm_key, (
        f'literal "***" should be skipped, but key was overwritten: {stored!r}'
    )


@pytest.mark.asyncio
async def test_get_settings_survives_key_rotation(session, monkeypatch):
    # Encrypt under one secret key...
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "old-secret")
    import server.config as config

    importlib.reload(config)

    from server.services import settings_service

    importlib.reload(settings_service)
    await settings_service.update_settings(session, {"llm_api_key": "sk-rotate-1234"})

    # ...then rotate the secret key. The old ciphertext can no longer be decrypted.
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "new-secret")
    importlib.reload(config)
    importlib.reload(settings_service)

    out = await settings_service.get_settings(session)  # must NOT raise
    assert out["llm_api_key"] == ""  # degraded to unset
    assert await settings_service.get_decrypted_api_key(session) == ""
