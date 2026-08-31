"""A stored verdict must not outlive the configuration it was about.

The whole point of the new status is that green means "a real message went
through". A row that was tested, then repointed at a different provider/model/
endpoint/key, has a verdict describing something nobody ran — which is the same
lie in a new place. Editing clears it back to "never tested".
"""
from __future__ import annotations

import pytest
from server.db.models import ProviderConfig
from server.services import provider_config_service as svc


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from server.db import session as db_session
    from server.db.models import Base
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    db_session.AsyncSessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with db_session.AsyncSessionLocal() as s:
        yield s


async def _tested_row(db) -> ProviderConfig:
    row = ProviderConfig(label="A", provider="deepseek", model="deepseek-chat",
                         base_url="", api_key="", is_primary=True)
    svc.record_test_verdict(row, ok=True, detail=None)
    db.add(row)
    await db.commit()
    assert row.last_health == "ok"      # precondition, not the assertion
    return row


@pytest.mark.parametrize("patch", [
    {"provider": "anthropic"},
    {"model": "claude-sonnet-5"},
    {"base_url": "https://example.test/v1"},
    {"api_key": "sk-brand-new-key-9999"},
])
async def test_editing_what_the_test_exercised_clears_the_verdict(db, patch):
    row = await _tested_row(db)
    await svc.update_config(db, row.id, **patch)
    await db.refresh(row)
    assert row.last_health is None, f"{patch} kept a verdict about a different config"
    assert row.last_health_at is None
    assert row.last_health_detail is None


async def test_a_failed_verdicts_reason_is_cleared_too(db):
    row = ProviderConfig(label="A", provider="deepseek", model="m", api_key="", is_primary=True)
    svc.record_test_verdict(row, ok=False, detail="额度上限已触顶")
    db.add(row)
    await db.commit()

    await svc.update_config(db, row.id, api_key="sk-a-different-key-1234")
    await db.refresh(row)
    # A stale reason is worse than none: it explains a failure of a key that is
    # no longer installed.
    assert row.last_health_detail is None


async def test_renaming_keeps_the_verdict(db):
    """The discriminating case. If invalidation were keyed on "any update" this
    would clear too, and every rename would throw away a valid test result."""
    row = await _tested_row(db)
    await svc.update_config(db, row.id, label="My favourite model")
    await db.refresh(row)
    assert row.last_health == "ok", "a rename discarded a verdict it did not affect"


async def test_a_masked_key_echo_is_not_a_key_change(db):
    """The UI round-trips the masked key ("sk-…abcd") on unrelated saves. Treating
    that echo as a new key would clear the verdict on every incidental save —
    and _looks_masked already stops it from overwriting the stored secret, so the
    two decisions have to agree."""
    row = await _tested_row(db)
    await svc.update_config(db, row.id, api_key=svc.mask_secret("sk-original-key-abcd"))
    await db.refresh(row)
    assert row.last_health == "ok", "a masked echo was mistaken for a new key"
