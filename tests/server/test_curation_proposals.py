"""The memory proposal inbox (`/brain/proposals`) stays paginated.

The web labels these items `curation` (web/src/lib/pendingMemory.ts), but they are
memory_proposals rows: memory territory, DELETE-BY v0.1.65 with the memory v1 tables.
The curation loop (整理层) that also wrote here was deleted in C8-3 (v0.1.63); its
toggle test went with it (see test_curation_loop_removed.py).
"""
from __future__ import annotations

from server.db.models import MemoryProposal

AUTH: dict[str, str] = {}


async def test_list_proposals_is_paginated(client):
    async with client.db_maker() as s:
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


async def test_v1_spawns_card_lists_without_excerpt_and_accept_is_refused(client):
    """C7c-5a: "spawns" left brain._TABLE_MODELS. An old v1 card on that table still lists
    (no excerpt is read from the expert row) and accept refuses it with a clean 409.

    The legacy read-only trigger keeps spawns.memory_facts empty, so the old excerpt was
    None too: the listing alone cannot tell the two designs apart, hence the map check."""
    from server.api import brain

    assert "spawns" not in brain._TABLE_MODELS
    async with client.db_maker() as s:
        p = MemoryProposal(kind="preference_overwrite_suspect", table_name="spawns",
                           old_id=2, reason="r", status="pending", conversation_id="c-x",
                           provenance={"target_spawn_id": 2, "new_array": ["x"]})
        s.add(p)
        await s.commit()
        pid = p.id

    r = await client.get("/api/v1/brain/proposals", headers=AUTH)
    assert r.status_code == 200
    (card,) = [c for c in r.json() if c["id"] == pid]
    assert card["old_excerpt"] is None

    acc = await client.post(f"/api/v1/brain/proposals/{pid}/accept", headers=AUTH)
    assert acc.status_code == 409
    assert acc.json()["detail"]["code"] == "versioned_memory_review_required"
