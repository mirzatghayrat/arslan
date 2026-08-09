"""Per-task model slots: set one and that task uses it; leave it and nothing changes.

Four slots — compaction, title, router, vision — built on the shape
``build_synthesis_adapter`` already established: a settings key holding a
provider_config id, resolved to an adapter, and **None when unset** so the caller
keeps exactly the behaviour it had. Copying that shape rather than inventing a second
one is deliberate; two ways to say "use a different model here" would drift.

🔴 THE ASSERTION THAT MATTERS MOST is the negative one. "Unset changes nothing" is what
makes this feature safe to ship, and it is the one a careless implementation breaks
silently — a slot that quietly takes over when empty would move every compaction call
onto some other model and the only symptom would be the bill.

🔴 AND VISION IS TWO-SIDED, per the ruling. `vision_config_id` applies only to turns
that actually carry an image. Without that condition "explicit" becomes "quietly moved
every turn elsewhere", which is the silent model swap this spec exists to remove.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ProviderConfig
from server.services import llm_factory, settings_service

SLOTS = ("compaction_config_id", "title_config_id", "router_config_id", "vision_config_id")


@pytest_asyncio.fixture
async def db(monkeypatch):
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    async with maker() as s:
        for label, provider, model in (("primary", "deepseek", "deepseek-chat"),
                                       ("slot", "openai", "gpt-4o-mini")):
            s.add(ProviderConfig(label=label, provider=provider, model=model,
                                 api_key="", is_primary=(label == "primary")))
        await s.commit()
        yield s
    await eng.dispose()


async def _slot_id(db) -> int:
    from sqlalchemy import select

    rows = (await db.execute(select(ProviderConfig).where(ProviderConfig.label == "slot"))).scalars()
    return next(iter(rows)).id


class TestUnsetChangesNothing:
    @pytest.mark.parametrize("slot", SLOTS)
    async def test_an_unset_slot_returns_none(self, db, slot):
        # None is the contract: the caller keeps its own adapter untouched. Anything
        # else here silently reroutes work — and money — to another model.
        assert await llm_factory.build_slot_adapter(slot) is None

    @pytest.mark.parametrize("slot", SLOTS)
    async def test_a_blank_slot_is_treated_as_unset(self, db, slot):
        await settings_service.update_settings(db, {slot: "   "})

        assert await llm_factory.build_slot_adapter(slot) is None

    @pytest.mark.parametrize("slot", SLOTS)
    async def test_a_slot_pointing_at_a_deleted_config_returns_none(self, db, slot):
        # Fail back to the default rather than raising: a stale id is a settings
        # problem, and taking the whole compaction path down over it would be worse
        # than quietly using the model that was working yesterday.
        await settings_service.update_settings(db, {slot: "99999"})

        assert await llm_factory.build_slot_adapter(slot) is None


class TestSetSlotIsUsed:
    @pytest.mark.parametrize("slot", SLOTS)
    async def test_a_set_slot_builds_that_config(self, db, slot):
        sid = await _slot_id(db)
        await settings_service.update_settings(db, {slot: str(sid)})

        adapter = await llm_factory.build_slot_adapter(slot)

        assert adapter is not None, f"{slot} was set and produced no adapter"
        assert adapter.model == "gpt-4o-mini"

    async def test_slots_are_independent(self, db):
        # Setting one must not turn the others on — the failure mode of a single
        # shared key pretending to be four.
        sid = await _slot_id(db)
        await settings_service.update_settings(db, {"title_config_id": str(sid)})

        assert await llm_factory.build_slot_adapter("title_config_id") is not None
        for other in ("compaction_config_id", "router_config_id", "vision_config_id"):
            assert await llm_factory.build_slot_adapter(other) is None, other

    async def test_only_registered_slots_are_accepted(self, db):
        # A typo'd slot name must raise rather than silently resolve to nothing, which
        # would look exactly like "the user has not configured it".
        with pytest.raises(ValueError):
            await llm_factory.build_slot_adapter("nonsense_config_id")


class TestTheSlotsAreRegisteredEverywhereTheyMustBe:
    def test_every_slot_is_a_settings_key(self):
        # Derived, not hand-listed. A slot missing from _PLAIN_KEYS would be accepted
        # by the API and never stored — the github_token defect, which happened three
        # times before anyone wrote a test shaped like this one.
        for slot in SLOTS:
            assert slot in settings_service._PLAIN_KEYS, slot

    def test_every_slot_is_on_both_pydantic_schemas(self):
        # BOTH. github_token was on neither, so the PUT dropped it going in and the GET
        # dropped it coming out, while the frontend sent it correctly and its own tests
        # passed. One side is not enough to check.
        from server.schemas import SettingsIn, SettingsOut

        for slot in SLOTS:
            assert slot in SettingsIn.model_fields, f"{slot} missing from SettingsIn"
            assert slot in SettingsOut.model_fields, f"{slot} missing from SettingsOut"

    def test_the_slot_registry_matches_the_settings_keys(self):
        assert set(llm_factory.SLOT_KEYS) == set(SLOTS)
