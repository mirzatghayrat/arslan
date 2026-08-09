"""The slots reach the three call sites, and an unset slot changes nothing there.

Step 1 built the resolver. This is the half that matters to a user: adding a field
nobody reads is free, and wiring it is the whole job — server/mcp/catalog.py grew a
`containment` field, shipped it on the API, and nothing ever rendered it.

🔴 EVERY CASE IS TWO-SIDED, and the negative side is the one that protects people. A
slot that took over when unset would move that task — and its cost — onto a different
model, and the only symptom would be the bill. So each site is checked BOTH with the
slot set (it is used) and without (the original build_adapter call is the one that
happens, untouched).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ProviderConfig
from server.services import settings_service

SITES = (
    # (module path, the _get_adapter to call, the slot that overrides it)
    ("server.orchestrator.memory", "compaction_config_id"),
    ("server.orchestrator.router", "router_config_id"),
)


@pytest_asyncio.fixture
async def db(monkeypatch):
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    async with maker() as s:
        s.add(ProviderConfig(label="primary", provider="deepseek", model="deepseek-chat",
                             api_key="", is_primary=True))
        s.add(ProviderConfig(label="slot", provider="openai", model="gpt-4o-mini",
                             api_key="", is_primary=False))
        await s.commit()
        yield s
    await eng.dispose()


async def _slot_config_id(db) -> str:
    from sqlalchemy import select

    row = (await db.execute(
        select(ProviderConfig).where(ProviderConfig.label == "slot"))).scalars().first()
    return str(row.id)


@pytest.mark.parametrize("module_path,slot", SITES)
class TestTheThreeOneLineHooks:
    async def test_the_slot_is_used_when_set(self, db, monkeypatch, module_path, slot):
        import importlib

        mod = importlib.import_module(module_path)
        await settings_service.update_settings(db, {slot: await _slot_config_id(db)})

        adapter = await mod._get_adapter()

        assert adapter.model == "gpt-4o-mini", f"{module_path} ignored {slot}"

    async def test_an_unset_slot_leaves_the_call_site_alone(self, db, monkeypatch,
                                                            module_path, slot):
        # The protective half. Without this, "the slot is used" passes on an
        # implementation that ALWAYS reroutes, which is the expensive failure.
        import importlib

        mod = importlib.import_module(module_path)

        adapter = await mod._get_adapter()

        assert adapter.model == "deepseek-chat", (
            f"{module_path} took a detour with {slot} unset"
        )


class TestTitler:
    """titler.py builds its adapter inline rather than via a _get_adapter hook."""

    async def test_the_slot_is_used_when_set(self, db, monkeypatch):
        from server.services import titler

        await settings_service.update_settings(db, {"title_config_id": await _slot_config_id(db)})
        seen = {}

        class _Fake:
            model = "gpt-4o-mini"

            async def chat(self, *a, **kw):
                seen["model"] = self.model
                raise RuntimeError("stop here — the adapter choice is what is under test")

        adapter = await titler._adapter()
        assert adapter.model == "gpt-4o-mini"

    async def test_unset_keeps_the_summarize_role(self, db):
        from server.services import titler

        adapter = await titler._adapter()

        assert adapter.model == "deepseek-chat"


class TestVisionAppliesOnlyToTurnsWithImages:
    """The ruling's extra condition, and the reason it exists.

    🔴 Without "only when the turn carries an image", an explicitly-set vision slot
    would silently move EVERY turn onto that model — which is the silent model swap
    this spec exists to remove, arriving through the feature meant to prevent it.
    """

    async def test_a_turn_with_images_uses_the_vision_slot(self, db):
        from server.orchestrator import tool_loop

        await settings_service.update_settings(db, {"vision_config_id": await _slot_config_id(db)})

        adapter = await tool_loop._adapter_for_turn(has_images=True)

        assert adapter.model == "gpt-4o-mini"

    async def test_a_turn_without_images_does_not(self, db):
        from server.orchestrator import tool_loop

        await settings_service.update_settings(db, {"vision_config_id": await _slot_config_id(db)})

        adapter = await tool_loop._adapter_for_turn(has_images=False)

        assert adapter.model == "deepseek-chat", (
            "the vision slot took a turn that carried no image"
        )

    async def test_no_vision_slot_means_images_change_nothing(self, db):
        from server.orchestrator import tool_loop

        adapter = await tool_loop._adapter_for_turn(has_images=True)

        assert adapter.model == "deepseek-chat"
