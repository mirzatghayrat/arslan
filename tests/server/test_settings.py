"""Settings service and API tests, including secret masking."""
import importlib

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base


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
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "unit-test-secret")
    import server.config as config

    importlib.reload(config)
    import server.crypto as crypto

    importlib.reload(crypto)
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
    import server.crypto as crypto

    importlib.reload(crypto)
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
