"""An expert's preferences under memory v2: its active memory entries in expert scope (0.1.63 C2a-2 removed
the v1 list on Spawn.memory_facts). Deleting one needs its entry id and version, and only this expert's
entries can be deleted through this route."""
import pytest

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from server.db.models import Spawn
from server.services.memory_repository import repository


@pytest.fixture
async def seeded(client, monkeypatch):
    from server.db import session as db_session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    async with client.db_maker() as s:
        s.add(Spawn(id=3, name="Synthetic expert", domain_category="content", system_prompt="sp"))
        s.add(Spawn(id=4, name="Another expert", domain_category="content", system_prompt="sp"))
        await s.commit()
    entries = {}
    async with repository() as repo:
        for key, text, owner in (("short", "Shorter answers", "3"), ("cite", "Cite sources", "3"),
                                 ("other", "Another expert's habit", "4")):
            entries[key] = await repo.create(MemoryWrite(content=text, scope=MemoryScope(kind="expert", id=owner)),
                                             MemoryActor(origin="user"))
    client.entries = entries
    return client


async def test_get_preferences_lists_only_this_experts_active_entries(seeded):
    r = await seeded.get("/api/v1/spawns/3/preferences")
    assert r.status_code == 200
    assert sorted(r.json()["preferences"]) == ["Cite sources", "Shorter answers"]


async def test_delete_needs_identity_and_version(seeded):
    r = await seeded.request("DELETE", "/api/v1/spawns/3/preferences", json={"fact": "Cite sources"})
    assert r.status_code == 428


async def test_delete_refuses_another_experts_entry(seeded):
    other = seeded.entries["other"]
    r = await seeded.request("DELETE", "/api/v1/spawns/3/preferences",
                             json={"fact": "x", "entry_id": other["id"], "expected_version": other["version"]})
    assert r.status_code == 403


async def test_delete_removes_the_entry(seeded):
    cite = seeded.entries["cite"]
    r = await seeded.request("DELETE", "/api/v1/spawns/3/preferences",
                             json={"fact": "Cite sources", "entry_id": cite["id"], "expected_version": cite["version"]})
    assert r.status_code == 200 and r.json()["preferences"] == ["Shorter answers"]
