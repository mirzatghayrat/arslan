"""The memory proposal inbox (`/brain/proposals`) stays paginated.

The web labels these items `curation` (web/src/lib/pendingMemory.ts), but they are
memory_proposals rows: memory territory, DELETE-BY v0.1.64 with the memory v1 tables.
The curation loop (整理层) that also wrote here was deleted in C8-3 (v0.1.63); its
toggle test went with it (see test_curation_loop_removed.py).
"""
from __future__ import annotations

from server.db.models import MemoryProposal, Spawn

AUTH: dict[str, str] = {}


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
