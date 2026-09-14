"""Actual activated SQLite FTS, not a mocked index or a live model."""
from dataclasses import replace

import pytest
from sqlalchemy import text, update

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from server.db.models import MemoryEntry, Project
from server.services import personal_context as pc
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync
from server.services.memory_repository import repository


@pytest.fixture
async def indexed(execution_db):
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)
    async with execution_db() as db:
        db.add_all([Project(id="a", name="A"), Project(id="b", name="B")])
        await db.commit()
    return execution_db


async def create(content, **kwargs):
    kwargs.setdefault("scope", MemoryScope(kind="global"))
    async with repository() as repo:
        return await repo.create(MemoryWrite(content=content, **kwargs), MemoryActor(origin="user"))


def context(**kwargs):
    return pc.TaskMemoryContext(task_id="task", run_id="run", model_is_local=True, **kwargs)


async def test_actual_index_is_used_only_for_authorized_current_rows(indexed, monkeypatch):
    allowed = await create("Annual report format")
    project = await create("Annual report project", scope=MemoryScope(kind="project", id="a"))
    await create("Annual report elsewhere", scope=MemoryScope(kind="project", id="b"))
    foreign = await create("Annual report foreign")
    await create("Annual report sensitive", sensitivity="sensitive", sensitive_acknowledged=True)
    async with indexed() as db:
        await db.execute(update(MemoryEntry).where(MemoryEntry.id == foreign["id"]).values(owner_id="other"))
        await db.commit()
    seen = []
    original = pc._indexed_matches
    async def checked(db, rows, terms):
        seen.extend(entry.id for entry, _ in rows)
        return await original(db, rows, terms)
    monkeypatch.setattr(pc, "_indexed_matches", checked)
    # Prove that real FTS hits can select memory independently of the supplement.
    monkeypatch.setattr(pc.memory_relevance, "score", lambda *args, **kwargs: 0)
    result = await pc.assemble("report", context=context(project_id="a"))
    expected = {allowed["id"], project["id"]}
    assert set(seen) == expected
    assert {ref.id for ref in result.receipt.used} == expected
    assert "foreign" not in result.text and "elsewhere" not in result.text and "sensitive" not in result.text


async def test_stale_index_cannot_restore_old_revision_or_deleted_body(indexed, monkeypatch):
    row = await create("Annual report format")
    async with repository() as repo:
        await repo.revise(row["id"], 1, MemoryWrite(content="Movie preference", scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
    monkeypatch.setattr(pc.memory_relevance, "score", lambda *args, **kwargs: 0)
    assert not (await pc.assemble("report", context=context())).receipt.used
    assert (await pc.assemble("movie", context=context())).receipt.used[0].revision == 2
    async with indexed() as db:
        await db.execute(text("UPDATE memory_entries_fts SET content='Annual report format' WHERE entry_id=:id"), {"id": row["id"]})
        await db.commit()
    assert not (await pc.assemble("report", context=context())).receipt.used
    async with repository() as repo:
        await repo.delete_entry(row["id"], 2, MemoryActor(origin="user"))
    # Even a damaged/restored index cannot bypass the authoritative deletion gate.
    async with indexed() as db:
        await db.execute(text("INSERT INTO memory_entries_fts(entry_id,content) VALUES (:id,'Annual report format')"), {"id": row["id"]})
        await db.commit()
    assert not (await pc.assemble("report", context=context())).receipt.used


async def test_missing_index_preserves_local_fallback(indexed):
    await create("Concise reports")
    async with indexed() as db:
        await db.execute(text("DROP TABLE memory_entries_fts"))
        await db.commit()
    assert "Concise reports" in (await pc.assemble("report", context=context())).text
    assert not (await pc.assemble("What is 2 + 2?", context=context())).receipt.used


@pytest.mark.parametrize("query", ["report", "报告", "レポート", "informe", "Bericht", "rapport"])
async def test_index_does_not_replace_multilingual_supplement(indexed, query):
    row = await create("Concise reports")
    result = await pc.assemble(query, context=context())
    assert [ref.id for ref in result.receipt.used] == [row["id"]]


async def test_no_memory_and_cloud_gates_do_not_search_index(indexed, monkeypatch):
    await create("Annual report format")
    async def forbidden(*args, **kwargs):
        raise AssertionError("Index search must not run")
    monkeypatch.setattr(pc, "_indexed_matches", forbidden)
    for ctx in (context(no_memory=True), context(temporary=True), replace(context(), model_is_local=False)):
        assert not (await pc.assemble("report", context=ctx)).receipt.used


async def test_unicode_index_query_treats_input_as_literal_terms(indexed, monkeypatch):
    row = await create("Café recommendations")
    monkeypatch.setattr(pc.memory_relevance, "score", lambda *args, **kwargs: 0)
    result = await pc.assemble('"CAFÉ" OR nonexistent* NEAR(secret)', context=context())
    assert [ref.id for ref in result.receipt.used] == [row["id"]]
    assert not (await pc.assemble('"nonexistent" OR secret*', context=context())).receipt.used


async def test_index_batches_ids_without_dropping_later_allowed_rows(indexed, monkeypatch):
    async with repository() as repo:
        for number in range(205):
            await repo.create(MemoryWrite(content=f"Report preference {number}", scope=MemoryScope(kind="global")),
                              MemoryActor(origin="user"))
    matches = set()
    original = pc._indexed_matches
    async def checked(db, rows, terms):
        result = await original(db, rows, terms)
        matches.update(result)
        return result
    monkeypatch.setattr(pc, "_indexed_matches", checked)
    result = await pc.assemble("report", context=context())
    assert len(matches) == 205
    assert result.receipt.estimated_tokens <= 1200
    assert len(result.receipt.used) <= 40
    assert "budget" in result.receipt.filter_reasons


async def test_empty_candidates_or_terms_never_open_index():
    class NoDatabaseAccess:
        async def scalar(self, *args, **kwargs):
            raise AssertionError("No query should run")
    assert await pc._indexed_matches(NoDatabaseAccess(), [], frozenset({"report"})) == set()
    assert await pc._indexed_matches(NoDatabaseAccess(), [object()], frozenset()) == set()
