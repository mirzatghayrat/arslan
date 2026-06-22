"""Integration test for Bug 1: language display-string flows end-to-end through build_adapter.

Scenario: two configs, openai (en=10) vs deepseek (zh=9, en=8).
- With balanced strategy + language="English (US)" → openai wins (language score tips it)
- With balanced strategy + language="Chinese (Simplified)" → deepseek wins

We verify the DISPLAY STRING stored by the dropdown reaches routing correctly.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base
from server.services import llm_factory, provider_config_service as pcs, settings_service


@pytest.fixture
async def db_language():
    """Two-config DB: openai (strong en) vs deepseek (strong zh), balanced strategy."""
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    db_session.AsyncSessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with db_session.AsyncSessionLocal() as s:
        # openai: en=10, zh=7 → strong English
        oa = await pcs.add_config(s, label="OpenAI", provider="openai",
                                  model="gpt-4o", base_url="", api_key="sk-openai")
        # deepseek: en=8, zh=9 → strong Chinese
        await pcs.add_config(s, label="DeepSeek", provider="deepseek",
                             model="deepseek-chat", base_url="", api_key="sk-ds")
        # set openai as primary (doesn't matter for balanced routing, but keeps fixture clean)
        await pcs.set_primary(s, oa["id"])
        await settings_service.update_settings(s, {"llm_strategy": "balanced"})
    yield
    await eng.dispose()


@pytest.mark.asyncio
async def test_english_display_string_selects_openai(db_language):
    """Balanced + 'English (US)' display string → openai wins (en=10 beats deepseek's en=8)."""
    async with db_session.AsyncSessionLocal() as s:
        await settings_service.update_settings(s, {"language": "English (US)"})
    adapter = await llm_factory.build_adapter(role="execute")
    assert adapter.model == "gpt-4o", (
        f"Expected gpt-4o (openai has en=10), got {adapter.model!r}"
    )


@pytest.mark.asyncio
async def test_chinese_display_string_selects_deepseek(db_language):
    """Balanced + 'Chinese (Simplified)' display string → deepseek wins (zh=9 > openai zh=7)."""
    async with db_session.AsyncSessionLocal() as s:
        await settings_service.update_settings(s, {"language": "Chinese (Simplified)"})
    adapter = await llm_factory.build_adapter(role="execute")
    assert adapter.model == "deepseek-chat", (
        f"Expected deepseek-chat (deepseek has zh=9), got {adapter.model!r}"
    )


@pytest.mark.asyncio
async def test_iso_code_en_selects_openai(db_language):
    """ISO code 'en' still works (backward compat)."""
    async with db_session.AsyncSessionLocal() as s:
        await settings_service.update_settings(s, {"language": "en"})
    adapter = await llm_factory.build_adapter(role="execute")
    assert adapter.model == "gpt-4o"


@pytest.mark.asyncio
async def test_iso_code_zh_selects_deepseek(db_language):
    """ISO code 'zh' still works (backward compat)."""
    async with db_session.AsyncSessionLocal() as s:
        await settings_service.update_settings(s, {"language": "zh"})
    adapter = await llm_factory.build_adapter(role="execute")
    assert adapter.model == "deepseek-chat"
