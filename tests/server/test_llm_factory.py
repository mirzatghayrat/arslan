"""build_adapter assembles an LLMAdapter from stored settings."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import provider_config_service, settings_service


@pytest_asyncio.fixture
async def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "unit-test")
    import importlib

    import server.config as config

    importlib.reload(config)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'f.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as s:
        await settings_service.update_settings(
            s,
            {"llm_provider": "openai", "llm_model": "gpt-4o", "llm_api_key": "sk-x"},
        )

    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    return maker


@pytest.mark.asyncio
async def test_build_adapter_reads_settings(temp_db):
    from server.services.llm_factory import build_adapter

    adapter = await build_adapter()
    assert adapter.provider_name == "openai"
    assert adapter.model == "gpt-4o"


@pytest.mark.asyncio
async def test_build_adapter_refuses_unconfigured_destination(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'g.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.services.llm_factory import build_adapter

    from unittest.mock import Mock
    import server.services.llm_factory as factory
    constructor = Mock(side_effect=AssertionError("must not construct a provider"))
    monkeypatch.setattr(factory, "LLMAdapter", constructor)
    with pytest.raises(ValueError, match="No model connection"):
        await build_adapter()
    constructor.assert_not_called()
    await engine.dispose()


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


@pytest.mark.asyncio
async def test_adapter_reports_config_provider_not_protocol(tmp_path, monkeypatch):
    """S3-M3: usage attribution must carry the CONFIG-level provider key (deepseek/
    ollama/…), not the expanded protocol name ("openai") — every Tier-0 preset was
    previously reported as provider="openai" in buckets/summary rows."""
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "unit-test")  # hermetic: crypto fails closed without it
    import importlib

    import server.config as config

    importlib.reload(config)
    from arslan.llm import usage_sink

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'rp.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    async with maker() as s:
        await provider_config_service.add_config(
            s, label="O", provider="ollama", model="qwen2.5:0.5b", base_url="", api_key="")

    from server.services.llm_factory import build_adapter

    adapter = await build_adapter()
    assert adapter.provider_name == "openai"          # protocol unchanged (routing untouched)
    assert adapter._report_provider == "ollama"       # attribution identity

    with usage_sink.collecting():
        usage_sink.report_detail(tokens_in=10, tokens_out=5,
                                 model=adapter.model, provider=adapter._report_provider)
        d = usage_sink.detail()
    assert d["provider"] == "ollama"


# ---------------------------------------------------------------------------
# Provider-P1: blank model must raise, never silently become "gpt-4o"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_adapter_blank_model_native_provider_raises(tmp_path, monkeypatch):
    """A native provider config (anthropic) with a blank model must raise a clear
    ValueError — previously the `model or "gpt-4o"` poison fallback silently sent
    requests for a model the provider does not serve."""
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "unit-test")
    import importlib

    import server.config as config

    importlib.reload(config)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'bm.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    async with maker() as s:
        # First config is auto-primary. anthropic is NATIVE (not a Tier-0 preset),
        # so expand_preset leaves the blank model blank.
        await provider_config_service.add_config(
            s, label="A", provider="anthropic", model="", base_url="", api_key="sk-ant")

    from server.services.llm_factory import build_adapter

    with pytest.raises(ValueError, match="没有配置模型"):
        await build_adapter()


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "zh", "ja", "es", "de", "fr"])
@pytest.mark.parametrize("provider", [None, "", "   "])
async def test_legacy_key_without_provider_never_selects_cloud(tmp_path, monkeypatch, language, provider):
    """A restored key alone must not select a cloud destination or preset model."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'fi.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from unittest.mock import AsyncMock, Mock
    import server.services.llm_factory as factory
    from server.db.models import Setting
    from server.services.provider_error_messages import render
    async with maker() as session:
        session.add(Setting(key="language", value=language))
        # Simulates a restored profile's leftover encrypted key without exposing it.
        session.add(Setting(key="llm_api_key", value="synthetic-unreadable-ciphertext"))
        if provider is not None:
            session.add(Setting(key="llm_provider", value=provider))
        await session.commit()
    constructor = Mock(side_effect=AssertionError("must not construct a provider"))
    decrypted = AsyncMock(side_effect=AssertionError("must not load a provider key"))
    monkeypatch.setattr(factory, "LLMAdapter", constructor)
    monkeypatch.setattr(settings_service, "get_decrypted_api_key", decrypted)
    with pytest.raises(ValueError) as error:
        await factory.build_adapter()
    assert str(error.value) == render("not_configured", language)
    constructor.assert_not_called()
    decrypted.assert_not_called()
    await engine.dispose()


@pytest.mark.asyncio
async def test_tier0_preset_config_blank_model_does_not_raise(tmp_path, monkeypatch):
    """Regression guard: a Tier-0 preset config (deepseek) with a blank model gets
    the preset default from expand_preset — no error."""
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "unit-test")
    import importlib

    import server.config as config

    importlib.reload(config)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'t0.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    async with maker() as s:
        await provider_config_service.add_config(
            s, label="DS", provider="deepseek", model="", base_url="", api_key="sk-ds")

    from server.services.llm_factory import build_adapter

    adapter = await build_adapter()
    assert adapter.model == "deepseek-v4-flash"
