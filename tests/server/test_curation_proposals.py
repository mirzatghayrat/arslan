"""整理层#10 段 C: curation output goes to the brain proposal inbox, never straight
into memory — plus the production hygiene a BACKGROUND producer needs.

Contract under test:
  - propose_only writes NOTHING to memory: not spawn.memory_facts, and not the
    meta-upflow either (that one routes through memory.save_facts, which can
    AUTO-SUPERSEDE a live profile fact with no human approval — the silent write this
    whole segment exists to prevent). Asserted as an empty WRITE SET, not one member;
  - the proposal carries `target_spawn_id` — the key `_accept_preference_overwrite`
    actually reads (it has no fallback, unlike the delete branch) — and accepting it
    through the REAL endpoint materializes the memory;
  - dedup is per (kind, table_name, old_id, conversation_id): re-sweeping one
    conversation updates its pending row, but a DIFFERENT conversation touching the
    same spawn gets its OWN proposal (collapsing them silently loses material);
  - accepting invalidates only SAME-KIND siblings on the same target (a different kind
    may still be something the user wants);
  - accept validates new_array: an empty/garbage array must not silently wipe a spawn's
    memory;
  - listing is paginated (an unbounded list does 2 extra queries per row).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import ArslanMessage, Base, MemoryProposal, Spawn
from server.services import curation_loop, distill_service

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


async def test_propose_only_writes_nothing_to_memory(db, monkeypatch):
    """The WRITE SET must be empty — including the meta-upflow, whose save_facts can
    auto-supersede a live profile fact with zero human approval."""
    from server.orchestrator import memory
    from server.services import memory_temporal

    writes = []
    monkeypatch.setattr(memory, "save_facts",
                        lambda *a, **k: writes.append("save_facts") or _aw([]))
    monkeypatch.setattr(memory_temporal, "execute_supersede",
                        lambda *a, **k: writes.append("supersede") or _aw(None))

    async def _facts(existing, signals):
        return ["新偏好"]
    monkeypatch.setattr(distill_service, "distill_facts", _facts)
    await _seed(db)

    await distill_service.distill_session_detailed("c1", propose_only=True)

    assert writes == [], f"propose_only must write NOTHING to memory, got {writes}"
    async with db() as s:
        spawn = await s.get(Spawn, 1)
    assert spawn.memory_facts == ["旧偏好"], "memory_facts must be untouched"
    assert len(await _proposals(db)) == 1


async def test_proposal_carries_the_key_accept_actually_reads(db, monkeypatch):
    async def _facts(existing, signals):
        return ["新偏好"]
    monkeypatch.setattr(distill_service, "distill_facts", _facts)
    await _seed(db)

    await distill_service.distill_session_detailed("c1", propose_only=True)

    (p,) = await _proposals(db)
    assert p.kind == "preference_overwrite_suspect"
    assert p.table_name == "spawns"
    assert p.conversation_id == "c1"
    # `_accept_preference_overwrite` reads target_spawn_id and has NO fallback to
    # old_id (unlike the delete branch), so emitting only spawn_id would 422 forever.
    assert p.provenance["target_spawn_id"] == 1
    assert p.provenance["new_array"] == ["新偏好"]
    assert p.provenance["source_kind"] == "curator"


async def test_interactive_path_is_unchanged(db, monkeypatch):
    """propose_only defaults False; the interactive path still writes memory directly."""
    async def _facts(existing, signals):
        return ["新偏好"]
    monkeypatch.setattr(distill_service, "distill_facts", _facts)
    await _seed(db)

    await distill_service.distill_session("c1")

    async with db() as s:
        spawn = await s.get(Spawn, 1)
    assert spawn.memory_facts == ["新偏好"]
    assert await _proposals(db) == []


# --------------------------------------------------------------------------- dedup


async def test_resweeping_one_conversation_updates_its_pending_proposal(db, monkeypatch):
    calls = {"n": 0}

    async def _facts(existing, signals):
        calls["n"] += 1
        return [f"偏好{calls['n']}"]
    monkeypatch.setattr(distill_service, "distill_facts", _facts)
    await _seed(db)

    await distill_service.distill_session_detailed("c1", propose_only=True)
    async with db() as s:                       # clear the marker to allow a re-sweep
        from server.db.models import DistilledSession
        for row in (await s.execute(select(DistilledSession))).scalars().all():
            await s.delete(row)
        await s.commit()
    await distill_service.distill_session_detailed("c1", propose_only=True)

    props = await _proposals(db)
    assert len(props) == 1, "a re-sweep must UPDATE the pending row, not stack duplicates"
    assert props[0].provenance["new_array"] == ["偏好2"]


async def test_two_conversations_touching_one_spawn_get_two_proposals(db, monkeypatch):
    """Deduping on the spawn alone would silently drop the second conversation's
    material while still marking it processed."""
    async def _facts(existing, signals):
        return ["偏好"]
    monkeypatch.setattr(distill_service, "distill_facts", _facts)
    await _seed(db, conversation_id="c1", spawn_id=1)
    await _seed(db, conversation_id="c2", spawn_id=1)

    await distill_service.distill_session_detailed("c1", propose_only=True)
    await distill_service.distill_session_detailed("c2", propose_only=True)

    props = await _proposals(db)
    assert {p.conversation_id for p in props} == {"c1", "c2"}


# --------------------------------------------------------------------------- accept


async def test_accept_never_dismisses_another_conversations_material(client):
    """Accepting c1's proposal must NOT dismiss c2's: both conversations are already
    marked processed, so a dismissed proposal is material lost with no way back (no
    marker to clear, no re-sweep, no manual retry). The earlier version of this test
    asserted the opposite and locked the data loss in."""
    async with client.db_maker() as s:
        s.add(Spawn(id=1, name="S", domain_category="g", system_prompt="sp",
                    memory_facts=["旧偏好"]))
        for cid in ("c1", "c2"):
            s.add(MemoryProposal(
                kind="preference_overwrite_suspect", table_name="spawns", old_id=1,
                conversation_id=cid, reason="r", status="pending",
                provenance={"target_spawn_id": 1, "new_array": [f"{cid}偏好"],
                            "source_kind": "curator", "conversation_id": cid}))
        await s.commit()
        props = sorted((await s.execute(select(MemoryProposal))).scalars().all(),
                       key=lambda p: p.id)
        first_id = props[0].id

    r = await client.post(f"/api/v1/brain/proposals/{first_id}/accept", headers=AUTH)
    assert r.status_code == 200, r.text

    async with client.db_maker() as s:
        rows = sorted((await s.execute(select(MemoryProposal))).scalars().all(),
                      key=lambda p: p.id)
    assert rows[0].status == "accepted"
    assert rows[1].status == "pending", (
        "the other conversation's material must still be adjudicable")


async def test_accept_dismisses_only_same_conversation_siblings(client):
    """Within ONE conversation two pending overwrites are genuinely stale after an
    accept (whole-array replace), so those are dismissed."""
    async with client.db_maker() as s:
        s.add(Spawn(id=1, name="S", domain_category="g", system_prompt="sp",
                    memory_facts=["旧偏好"]))
        for _ in range(2):
            s.add(MemoryProposal(
                kind="preference_overwrite_suspect", table_name="spawns", old_id=1,
                conversation_id="c1", reason="r", status="pending",
                provenance={"target_spawn_id": 1, "new_array": ["新偏好"],
                            "source_kind": "curator", "conversation_id": "c1"}))
        await s.commit()
        props = sorted((await s.execute(select(MemoryProposal))).scalars().all(),
                       key=lambda p: p.id)

    r = await client.post(f"/api/v1/brain/proposals/{props[0].id}/accept", headers=AUTH)
    assert r.status_code == 200, r.text
    async with client.db_maker() as s:
        rows = sorted((await s.execute(select(MemoryProposal))).scalars().all(),
                      key=lambda p: p.id)
        spawn = await s.get(Spawn, 1)
    assert spawn.memory_facts == ["新偏好"]
    assert [r.status for r in rows] == ["accepted", "dismissed"]


async def test_accept_does_not_collide_on_the_old_id_zero_sentinel(client, monkeypatch):
    """RememberExecutor coerces a target-less proposal's old_id to 0, so ALL such
    proposals share old_id=0. A sibling query keyed on (kind, table, old_id) would
    dismiss every unrelated one the moment any single one is accepted."""
    # append_suspect's acceptor routes through memory.save_facts, which opens the
    # PRODUCTION sessionmaker — the client's dependency override does not cover it, so
    # without this the test would write to the developer's real DB.
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)

    async with client.db_maker() as s:
        from server.db.models import UserFact

        s.add(UserFact(content="事实", source="auto", confidence=0.6))
        for cid in ("c1", "c2"):
            s.add(MemoryProposal(
                kind="append_suspect", table_name="user_facts", old_id=0,
                conversation_id=cid, reason="r", status="pending",
                provenance={"content": f"{cid} 的新事实", "source_kind": "curator"}))
        await s.commit()
        props = sorted((await s.execute(select(MemoryProposal))).scalars().all(),
                       key=lambda p: p.id)
        first_id = props[0].id

    r = await client.post(f"/api/v1/brain/proposals/{first_id}/accept", headers=AUTH)
    assert r.status_code == 200, r.text
    async with client.db_maker() as s:
        rows = sorted((await s.execute(select(MemoryProposal))).scalars().all(),
                      key=lambda p: p.id)
    assert rows[1].status == "pending", (
        "old_id=0 is a sentinel, not a target — unrelated proposals must survive")


async def test_accept_refuses_a_garbage_new_array(client):
    """An empty array would silently WIPE a spawn's memory; accept validates."""
    async with client.db_maker() as s:
        s.add(Spawn(id=1, name="S", domain_category="g", system_prompt="sp",
                    memory_facts=["保留我"]))
        s.add(MemoryProposal(kind="preference_overwrite_suspect", table_name="spawns",
                             old_id=1, reason="r", status="pending",
                             provenance={"target_spawn_id": 1, "new_array": []}))
        await s.commit()
        pid = (await s.execute(select(MemoryProposal.id))).scalar_one()

    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept", headers=AUTH)
    assert r.status_code == 422, r.text
    async with client.db_maker() as s:
        spawn = await s.get(Spawn, 1)
    assert spawn.memory_facts == ["保留我"], "a garbage proposal must not wipe memory"


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
