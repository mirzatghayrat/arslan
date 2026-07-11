"""build_adapter assembles an LLMAdapter from stored settings."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import settings_service


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "unit-test")
    import importlib

    import server.config as config

    importlib.reload(config)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'f.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            await settings_service.update_settings(
                s,
                {"llm_provider": "openai", "llm_model": "gpt-4o", "llm_api_key": "sk-x"},
            )

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    return maker


@pytest.mark.asyncio
async def test_build_adapter_reads_settings(temp_db):
    from server.services.llm_factory import build_adapter

    adapter = await build_adapter()
    assert adapter.provider_name == "openai"
    assert adapter.model == "gpt-4o"


@pytest.mark.asyncio
async def test_build_adapter_defaults_when_unset(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'g.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.services.llm_factory import build_adapter

    adapter = await build_adapter()
    assert adapter.provider_name == "openai"  # default
    assert adapter.model == "gpt-5.6-terra"   # preset default (expand_preset fills it)


@pytest.mark.asyncio
async def test_build_adapter_expands_tier0_preset(tmp_path, monkeypatch):
    """Storing a preset name (e.g. deepseek) yields the OpenAI-compatible config."""
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "unit-test")
    import importlib

    import server.config as config

    importlib.reload(config)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'h.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as s:
        # user picks the preset and supplies only a key — no base_url/model
        await settings_service.update_settings(
            s, {"llm_provider": "deepseek", "llm_api_key": "sk-x"}
        )
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.services.llm_factory import build_adapter

    adapter = await build_adapter()
    assert adapter.provider_name == "openai"  # routed through OpenAI-compatible client
    assert adapter.model == "deepseek-v4-flash"  # filled from the preset default
