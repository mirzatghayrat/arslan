"""brain-P2 Task 5: Tier2 proposal accept — kind-branching (materialize on human
confirm). Task 4's RememberExecutor writes MemoryProposal rows for four Tier2
kinds; new_id is ALWAYS None at propose time (0033 made it nullable) because
nothing has been written yet — the to-be-written payload lives in `provenance`
JSON. This file proves EVERY kind Task 4 can emit has a real accept branch that
actually materializes the write (no dismiss-only dead end):

  - append_suspect            (table user_facts | notes)   -> this file
  - edit_high_conf_suspect    (table user_facts)            -> this file
  - delete_suspect            (table user_facts | learnings | notes | spawns)
                                                              -> this file
  - preference_overwrite_suspect (table spawns)              -> this file

Plus: dangling (410) / already-resolved (409) / bad-data (422) mapping per
kind, list_proposals not crashing on new_id=None + notes-table excerpts, and
the 🔴 dangling-superseded_by reconcile on delete_suspect (the silent-data-
loss guard: a row that was itself SOMEONE's supersede target must resurrect
its predecessor when deleted, else that predecessor's pointer dangles).

Fixture pattern mirrors tests/server/test_facts_api.py (NOT the plain
tests/server/conftest.py `client` fixture): accept_proposal's new branches
call server.orchestrator.memory.save_facts / delete_fact and
server.services.note_service.create / delete, all of which open their OWN
session via server.db.session.AsyncSessionLocal() rather than accepting an
injected session — so AsyncSessionLocal must be monkeypatched to the same
engine as the FastAPI dependency override, or the two write paths would land
in different databases.
"""
from __future__ import annotations

import importlib

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Learning, MemoryProposal, Note, Spawn, UserFact


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "p2.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))

    import server.config as config
    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p2.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # FTS5 virtual tables aren't ORM models (server/db/migrations only) —
        # note_service.create/delete and the delete_suspect learnings branch
        # touch these directly, same convention as test_memory_write_tiers.py.
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.db_maker = maker  # type: ignore[attr-defined]
        yield c
    await engine.dispose()


async def _seed_proposal(client, *, kind, table_name, old_id=0, new_id=None,
                         provenance=None, status="pending") -> int:
    async with client.db_maker() as db:
        p = MemoryProposal(kind=kind, table_name=table_name, new_id=new_id, old_id=old_id,
                           reason="test", status=status, provenance=provenance)
        db.add(p)
        await db.commit()
        await db.refresh(p)
        return p.id


async def _seed_fact(client, content="旧内容", **kw) -> int:
    async with client.db_maker() as db:
        row = UserFact(content=content, source="manual", confidence=0.6, **kw)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _seed_learning(client, content="旧心得", **kw) -> int:
    async with client.db_maker() as db:
        row = Learning(content=content, source_kind="distill", source_ref={}, **kw)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _seed_note(client, title="旧笔记", content="旧笔记内容") -> int:
    async with client.db_maker() as db:
        row = Note(title=title, content=content)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        # note_service.create also inserts an FTS row; mirror it so a
        # subsequent note_service.delete's own FTS cleanup has something to
        # delete without erroring.
        await db.execute(sa_text("INSERT INTO notes_fts (rowid, text) VALUES (:r, :t)"),
                         {"r": row.id, "t": f"{title}\n{content}"})
        await db.commit()
        return row.id


async def _seed_spawn(client, spawn_id, name, memory_facts=None) -> None:
    async with client.db_maker() as db:
        db.add(Spawn(id=spawn_id, name=name, domain_category="d", system_prompt="p",
                     memory_facts=memory_facts or []))
        await db.commit()


# --------------------------------------------------------------------- append_suspect

async def test_append_suspect_accept_materializes_global_fact(client):
    pid = await _seed_proposal(
        client, kind="append_suspect", table_name="user_facts",
        provenance={"content": "分身提议的新事实", "source_kind": "agentic", "actor": "spawn:1"})

    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"

    async with client.db_maker() as db:
        from sqlalchemy import select
        facts = (await db.execute(select(UserFact))).scalars().all()
    assert len(facts) == 1
    assert facts[0].content == "分身提议的新事实"


async def test_append_suspect_dismiss_does_not_materialize(client):
    pid = await _seed_proposal(
        client, kind="append_suspect", table_name="user_facts",
        provenance={"content": "不该落地的事实"})

    r = await client.post(f"/api/v1/brain/proposals/{pid}/dismiss")
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed"

    async with client.db_maker() as db:
        from sqlalchemy import select
        facts = (await db.execute(select(UserFact))).scalars().all()
    assert facts == []


async def test_append_suspect_accept_materializes_note(client):
    pid = await _seed_proposal(
        client, kind="append_suspect", table_name="notes",
        provenance={"content": "分身提议的新笔记内容"})

    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 200

    async with client.db_maker() as db:
        from sqlalchemy import select
        notes = (await db.execute(select(Note))).scalars().all()
    assert len(notes) == 1
    assert notes[0].content == "分身提议的新笔记内容"
    assert notes[0].title == "分身提议的新笔记内容"


async def test_append_suspect_missing_content_422(client):
    pid = await _seed_proposal(client, kind="append_suspect", table_name="user_facts",
                               provenance={})
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 422


async def test_append_suspect_bad_table_422(client):
    pid = await _seed_proposal(client, kind="append_suspect", table_name="learnings",
                               provenance={"content": "x"})
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 422


# --------------------------------------------------------------------- edit_high_conf_suspect

async def test_edit_high_conf_accept_creates_new_and_supersedes_old(client):
    old_id = await _seed_fact(client, content="用户很在意隐私")
    pid = await _seed_proposal(
        client, kind="edit_high_conf_suspect", table_name="user_facts", old_id=old_id,
        provenance={"content": "用户实际上完全不介意公开信息",
                   "source_kind": "agentic", "actor": "spawn:8"})

    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 200

    async with client.db_maker() as db:
        from sqlalchemy import select
        old = await db.get(UserFact, old_id)
        facts = (await db.execute(select(UserFact))).scalars().all()
    assert len(facts) == 2
    new_row = next(f for f in facts if f.id != old_id)
    assert new_row.content == "用户实际上完全不介意公开信息"
    assert old.superseded_by == new_row.id


async def test_edit_high_conf_dismiss_leaves_old_unchanged(client):
    old_id = await _seed_fact(client, content="待编辑的事实")
    pid = await _seed_proposal(
        client, kind="edit_high_conf_suspect", table_name="user_facts", old_id=old_id,
        provenance={"content": "编辑后的事实"})

    r = await client.post(f"/api/v1/brain/proposals/{pid}/dismiss")
    assert r.status_code == 200

    async with client.db_maker() as db:
        from sqlalchemy import select
        old = await db.get(UserFact, old_id)
        facts = (await db.execute(select(UserFact))).scalars().all()
    assert old.superseded_by is None
    assert len(facts) == 1                       # no new fact was ever created


async def test_edit_high_conf_missing_content_422(client):
    old_id = await _seed_fact(client)
    pid = await _seed_proposal(client, kind="edit_high_conf_suspect", table_name="user_facts",
                               old_id=old_id, provenance={})
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 422


async def test_edit_high_conf_unsupported_table_returns_422_no_stray_write(client):
    """Defense in depth: notes have no superseded_by column (no temporal
    concept) so an edit_high_conf_suspect proposal can only ever be
    materialized for table_name="user_facts" — RememberExecutor itself now
    refuses to CREATE this combination (see
    test_memory_scope_isolation.py::test_spawn_supersede_note_is_a_clean_error_not_a_proposal),
    but accept must still refuse cleanly (not crash, not write an orphan
    fact) for any proposal row that somehow carries table_name="notes" here
    (a stale row from before that fix, or a malformed/manually-inserted one)."""
    note_id = await _seed_note(client)
    pid = await _seed_proposal(client, kind="edit_high_conf_suspect", table_name="notes",
                               old_id=note_id, provenance={"content": "编辑笔记?"})
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 422

    async with client.db_maker() as db:
        from sqlalchemy import select
        facts = (await db.execute(select(UserFact))).scalars().all()
    assert facts == []                            # no stray user_facts row


async def test_edit_high_conf_accept_idempotent_when_save_facts_own_dedup_fires(client):
    """save_facts() runs its own exact/fuzzy dedup on every write, active-only.
    If the edit content is an EXTENSION of old_id's content, save_facts'
    internal rule-supersede may already point old_id at the freshly-created
    row before we get to our own execute_supersede call below — that must be
    treated as success (idempotent), not a spurious 409."""
    old_id = await _seed_fact(client, content="user prefers dark mode")
    pid = await _seed_proposal(
        client, kind="edit_high_conf_suspect", table_name="user_facts", old_id=old_id,
        provenance={"content": "user prefers dark mode and large fonts"})

    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 200

    async with client.db_maker() as db:
        from sqlalchemy import select
        old = await db.get(UserFact, old_id)
        facts = (await db.execute(select(UserFact))).scalars().all()
    assert old.superseded_by is not None
    new_row = next(f for f in facts if f.id != old_id)
    assert old.superseded_by == new_row.id
    assert new_row.content == "user prefers dark mode and large fonts"


async def test_edit_high_conf_old_hard_deleted_returns_410_no_orphan(client):
    """Race guard (coordinator Important): old_id was hard-deleted out-of-band
    between propose and accept. accept must 410 BEFORE materializing the new
    fact — otherwise a re-accept would leak a fresh orphan fact each time and
    fail identically forever. Assert: 410, fact count unchanged (no orphan),
    proposal still pending (dismissable)."""
    old_id = await _seed_fact(client, content="待编辑但会被删的事实")
    pid = await _seed_proposal(
        client, kind="edit_high_conf_suspect", table_name="user_facts", old_id=old_id,
        provenance={"content": "编辑内容永远不该落地"})
    async with client.db_maker() as db:
        old = await db.get(UserFact, old_id)
        await db.delete(old)
        await db.commit()

    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 410

    async with client.db_maker() as db:
        from sqlalchemy import select
        facts = (await db.execute(select(UserFact))).scalars().all()
        p = await db.get(MemoryProposal, pid)
    assert facts == []                    # NO orphan fact was materialized
    assert p.status == "pending"          # still dismissable, not stuck


async def test_edit_high_conf_old_superseded_out_of_band_returns_409_no_orphan(client):
    """Race guard (coordinator Important): old_id was superseded by a DIFFERENT
    row out-of-band between propose and accept. accept must 409 BEFORE
    materializing — no new orphan fact, proposal untouched."""
    old_id = await _seed_fact(client, content="会被别的行取代的事实")
    other_id = await _seed_fact(client, content="抢先取代的第三行")
    async with client.db_maker() as db:
        old = await db.get(UserFact, old_id)
        old.superseded_by = other_id
        await db.commit()

    pid = await _seed_proposal(
        client, kind="edit_high_conf_suspect", table_name="user_facts", old_id=old_id,
        provenance={"content": "编辑内容永远不该落地"})
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 409

    async with client.db_maker() as db:
        from sqlalchemy import select
        facts = (await db.execute(select(UserFact))).scalars().all()
        old = await db.get(UserFact, old_id)
        p = await db.get(MemoryProposal, pid)
    assert len(facts) == 2                # only the two seeded rows — no orphan
    assert old.superseded_by == other_id  # untouched (still points at the out-of-band winner)
    assert p.status == "pending"


# --------------------------------------------------------------------- delete_suspect

async def test_delete_suspect_accept_user_facts_reconciles_predecessor(client):
    """🔴 The dangling-superseded_by guard: A is superseded by B; accepting a
    delete_suspect proposal for B must both delete B AND resurrect A
    (A.superseded_by -> NULL) — else A's pointer dangles at a dead id, a
    silent-loss bug (A would look permanently "superseded" by nothing)."""
    a_id = await _seed_fact(client, content="A")
    b_id = await _seed_fact(client, content="B")
    async with client.db_maker() as db:
        a = await db.get(UserFact, a_id)
        a.superseded_by = b_id
        await db.commit()

    pid = await _seed_proposal(client, kind="delete_suspect", table_name="user_facts", old_id=b_id)
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 200

    async with client.db_maker() as db:
        a = await db.get(UserFact, a_id)
        b = await db.get(UserFact, b_id)
    assert b is None                    # B is gone
    assert a.superseded_by is None      # A is active again


async def test_delete_suspect_accept_learnings_reconciles_and_removes_fts(client):
    a_id = await _seed_learning(client, content="A心得")
    b_id = await _seed_learning(client, content="B心得")
    async with client.db_maker() as db:
        a = await db.get(Learning, a_id)
        a.superseded_by = b_id
        await db.commit()
        await db.execute(sa_text("INSERT INTO learnings_fts (rowid, text) VALUES (:r, :t)"),
                         {"r": b_id, "t": "B心得"})
        await db.commit()

    pid = await _seed_proposal(client, kind="delete_suspect", table_name="learnings", old_id=b_id)
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 200

    async with client.db_maker() as db:
        a = await db.get(Learning, a_id)
        b = await db.get(Learning, b_id)
        fts_rows = (await db.execute(
            sa_text("SELECT rowid FROM learnings_fts WHERE rowid = :r"), {"r": b_id})).all()
    assert b is None
    assert a.superseded_by is None
    assert fts_rows == []


async def test_delete_suspect_accept_notes(client):
    note_id = await _seed_note(client)
    pid = await _seed_proposal(client, kind="delete_suspect", table_name="notes", old_id=note_id)
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 200

    async with client.db_maker() as db:
        note = await db.get(Note, note_id)
        fts_rows = (await db.execute(
            sa_text("SELECT rowid FROM notes_fts WHERE rowid = :r"), {"r": note_id})).all()
    assert note is None
    assert fts_rows == []


async def test_delete_suspect_accept_spawns_clears_preferences(client):
    await _seed_spawn(client, 42, "分身42", memory_facts=["a", "b"])
    pid = await _seed_proposal(client, kind="delete_suspect", table_name="spawns", old_id=42,
                               provenance={"target_spawn_id": 42})
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 200

    async with client.db_maker() as db:
        spawn = await db.get(Spawn, 42)
    assert spawn.memory_facts == []


async def test_delete_suspect_dangling_returns_410_and_stays_pending(client):
    pid = await _seed_proposal(client, kind="delete_suspect", table_name="user_facts", old_id=999999)
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 410

    async with client.db_maker() as db:
        p = await db.get(MemoryProposal, pid)
    assert p.status == "pending"


async def test_delete_suspect_dangling_learnings_returns_410_but_reconcile_still_lands(client):
    """Reconcile runs FIRST and is committed durably, even when the delete
    itself then 410s — the predecessor fix must never depend on the delete
    succeeding (the row may already be gone by the time a human clicks accept,
    but any dangling predecessor pointer should still get cleaned up)."""
    a_id = await _seed_learning(client, content="A心得")
    async with client.db_maker() as db:
        a = await db.get(Learning, a_id)
        a.superseded_by = 999999
        await db.commit()

    pid = await _seed_proposal(client, kind="delete_suspect", table_name="learnings", old_id=999999)
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 410

    async with client.db_maker() as db:
        a = await db.get(Learning, a_id)
    assert a.superseded_by is None


async def test_delete_suspect_bad_table_returns_422(client):
    pid = await _seed_proposal(client, kind="delete_suspect", table_name="bogus", old_id=1)
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 422


# --------------------------------------------------------------------- preference_overwrite_suspect

async def test_preference_overwrite_accept_sets_new_array(client):
    await _seed_spawn(client, 10, "分身10", memory_facts=["旧偏好"])
    pid = await _seed_proposal(
        client, kind="preference_overwrite_suspect", table_name="spawns", old_id=10,
        provenance={"target_spawn_id": 10, "new_array": ["旧偏好", "host 建议的新偏好"]})

    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 200

    async with client.db_maker() as db:
        spawn = await db.get(Spawn, 10)
    assert spawn.memory_facts == ["旧偏好", "host 建议的新偏好"]


async def test_preference_overwrite_missing_target_spawn_returns_410(client):
    pid = await _seed_proposal(
        client, kind="preference_overwrite_suspect", table_name="spawns", old_id=999999,
        provenance={"target_spawn_id": 999999, "new_array": ["x"]})
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 410


async def test_preference_overwrite_missing_provenance_fields_returns_422(client):
    await _seed_spawn(client, 11, "分身11")
    pid = await _seed_proposal(
        client, kind="preference_overwrite_suspect", table_name="spawns", old_id=11,
        provenance={})
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 422


# --------------------------------------------------------------------- generic 4xx mapping

async def test_accept_already_resolved_returns_409_for_tier2_kind(client):
    pid = await _seed_proposal(client, kind="append_suspect", table_name="user_facts",
                               provenance={"content": "x"}, status="accepted")
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 409


async def test_accept_unmapped_kind_returns_422(client):
    pid = await _seed_proposal(client, kind="some_future_kind", table_name="user_facts", old_id=1)
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 422


# --------------------------------------------------------------------- list_proposals compat

async def test_list_proposals_new_id_none_does_not_crash(client):
    await _seed_proposal(client, kind="append_suspect", table_name="user_facts",
                         provenance={"content": "x"})
    r = await client.get("/api/v1/brain/proposals?status=pending")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["new_id"] is None


async def test_list_proposals_notes_excerpt_correct(client):
    note_id = await _seed_note(client, content="笔记正文用于摘要断言")
    await _seed_proposal(client, kind="delete_suspect", table_name="notes", old_id=note_id)

    r = await client.get("/api/v1/brain/proposals?status=pending")
    assert r.status_code == 200
    row = r.json()[0]
    assert row["old_excerpt"] == "笔记正文用于摘要断言"
    assert row["new_excerpt"] is None
