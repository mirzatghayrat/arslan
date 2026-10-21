"""Curation's proposal inbox: what is left under memory v2 (0.1.63 C2a-2).

The curation sweep no longer files v1 proposals (memory v2 distillation proposes memory entries instead), and
accepting a v1 card on a non-notes table is refused for versioned review; tests/server/test_memory_proposals_api.py
covers accept and its sibling rules. What stays here: the inbox listing is paginated (an unbounded list does two
extra queries per row), and the curation toggle is reachable through the settings API. C8 removes curation.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import ArslanMessage, Base, MemoryProposal, Spawn
from server.services import curation_loop


AUTH: dict[str, str] = {}


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    curation_loop._attempts.clear()
    yield Session
    curation_loop._attempts.clear()
    await engine.dispose()


async def _seed(Session, *, conversation_id="c1", spawn_id=1):
    async with Session() as s:
        if await s.get(Spawn, spawn_id) is None:
            s.add(Spawn(id=spawn_id, name=f"S{spawn_id}", domain_category="g",
                        system_prompt="sp", memory_facts=["旧偏好"]))
        s.add(ArslanMessage(conversation_id=conversation_id, role="user", content="做事"))
        s.add(ArslanMessage(conversation_id=conversation_id, role="spawn_summary",
                            content="产出", display_content="产出", spawn_id=spawn_id))
        await s.commit()


async def _proposals(Session):
    async with Session() as s:
        return (await s.execute(select(MemoryProposal))).scalars().all()


# --------------------------------------------------------------------------- propose_only


# --------------------------------------------------------------------------- dedup


# --------------------------------------------------------------------------- accept










# --------------------------------------------------------------------------- listing


async def test_list_proposals_is_paginated(client):
    async with client.db_maker() as s:
        s.add(Spawn(id=1, name="S", domain_category="g", system_prompt="sp"))
        for i in range(7):
            s.add(MemoryProposal(kind="preference_overwrite_suspect", table_name="spawns",
                                 old_id=1, reason=f"r{i}", status="pending",
                                 conversation_id=f"c{i}",
                                 provenance={"target_spawn_id": 1, "new_array": ["x"]}))
        await s.commit()

    r = await client.get("/api/v1/brain/proposals?limit=3", headers=AUTH)
    assert r.status_code == 200
    assert len(r.json()) == 3, "an unbounded inbox does 2 extra queries PER ROW"
    r2 = await client.get("/api/v1/brain/proposals?limit=3&offset=6", headers=AUTH)
    assert len(r2.json()) == 1
    # the response stays a JSON ARRAY — turning it into an object would break every
    # existing consumer and test
    assert isinstance(r.json(), list)


async def _aw(v):
    return v


async def test_the_curation_toggle_is_reachable_through_the_settings_api(client):
    """The kill switch was implemented in the service layer and wired to NOTHING: it
    was missing from SettingsIn/SettingsOut, so PUT /settings silently dropped it and
    returned 200 while the sweep kept running. Drive the real HTTP round-trip."""
    from server.services import settings_service

    r = await client.get("/api/v1/settings", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["curation_enabled"] is False, "opt-in by default"

    r = await client.put("/api/v1/settings", json={"curation_enabled": True}, headers=AUTH)
    assert r.status_code == 200, r.text
    async with client.db_maker() as s:
        assert await settings_service.curation_enabled(s) is True

    r = await client.put("/api/v1/settings", json={"curation_enabled": False}, headers=AUTH)
    assert r.status_code == 200, r.text
    async with client.db_maker() as s:
        assert await settings_service.curation_enabled(s) is False


