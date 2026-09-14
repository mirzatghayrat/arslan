import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import update

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from server.db.models import MemoryEntry, Project
from server.services import personal_context as pc
from server.services.memory_migration import migrate_legacy_sync
from server.services.memory_repository import repository


@pytest.fixture
async def memories(execution_db):
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
    async with execution_db() as db:
        db.add_all([Project(id="project-a", name="A"), Project(id="project-b", name="B"),
                    Project(id="project-other", name="Other", owner_id="other")])
        await db.commit()
    return execution_db


async def create(content, *, scope="global", scope_id=None, **kwargs):
    async with repository() as repo:
        return await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind=scope, id=scope_id),
                                             **kwargs), MemoryActor(origin="user"))


def context(**kwargs):
    return pc.TaskMemoryContext(task_id="task-test", run_id="run-test", model_is_local=True, **kwargs)


async def test_scope_filter_precedes_ranking_and_budget(memories):
    await create("Global preference")
    await create("Matched project", scope="project", scope_id="project-a")
    await create("Wrong project needle", scope="project", scope_id="project-b")
    await create("Wrong expert needle", scope="expert", scope_id="expert-b")
    await create("Matched expert", scope="expert", scope_id="expert-a")
    result = await pc.assemble("needle", context=context(project_id="project-a", expert_id="expert-a"))
    assert "Global preference" in result.text and "Matched project" in result.text
    assert "Matched expert" in result.text and "Wrong" not in result.text
    assert len(result.receipt.used) == 3
    assert result.receipt.estimated_tokens <= 1200


@pytest.mark.parametrize("field,value", [
    ("status", "proposed"), ("status", "paused"), ("status", "quarantined"),
    ("status", "deleted"), ("status", "expired"), ("status", "superseded"),
    ("confirmation_kind", None), ("confirmed_at", None), ("sensitivity", "unknown"),
    ("sensitivity", "secret"), ("use_policy", "never"), ("owner_id", "other"),
    ("valid_from", datetime.utcnow() + timedelta(days=1)),
    ("expires_at", datetime.utcnow() - timedelta(days=1)),
    ("review_at", datetime.utcnow() - timedelta(days=1)),
])
async def test_ineligible_memory_never_enters_context(memories, field, value):
    row = await create("Excluded content")
    async with memories() as db:
        await db.execute(update(MemoryEntry).where(MemoryEntry.id == row["id"]).values(**{field: value}))
        await db.commit()
    result = await pc.assemble(context=context(allow_sensitive=True))
    assert result.text == "" and result.receipt.used == ()


async def test_cloud_requires_task_and_entry_permission(memories):
    await create("Local only")
    await create("Cloud eligible", use_policy="cloud_allowed")
    ctx = replace(context(), model_is_local=False)
    assert (await pc.assemble(context=ctx)).text == ""
    result = await pc.assemble(context=replace(ctx, cloud_memory_allowed=True))
    assert "Cloud eligible" in result.text and "Local only" not in result.text
    assert result.receipt.cloud_use == "approved"


async def test_no_memory_and_temporary_are_hard_gates(memories):
    await create("Stored content")
    for ctx in (context(no_memory=True), context(temporary=True)):
        result = await pc.assemble(context=ctx)
        assert result.text == "" and not result.receipt.used
    assert await pc.assemble() is None
    # Disabling learning does not disable retrieval.
    assert "Stored content" in (await pc.assemble(context=context(no_learning=True))).text


async def test_sensitive_requires_explicit_access(memories):
    await create("Personal sensitive preference", sensitivity="sensitive", sensitive_acknowledged=True)
    assert (await pc.assemble(context=context())).text == ""
    assert "Personal sensitive" in (await pc.assemble(context=context(allow_sensitive=True))).text


async def test_archived_project_is_not_retrieved(memories):
    await create("Archived content", scope="project", scope_id="project-a")
    async with memories() as db:
        await db.execute(update(Project).where(Project.id == "project-a").values(status="archived"))
        await db.commit()
    assert (await pc.assemble(context=context(project_id="project-a"))).text == ""


async def test_budget_never_slices_fact_or_receipt(memories):
    await create("x " * 2000)
    await create("Short fact")
    result = await pc.assemble(context=context(), limit_tokens=100)
    assert "Short fact" in result.text and "x x" not in result.text
    assert len(result.receipt.used) == 1
    assert result.receipt.filter_reasons == ("budget",)


async def test_contextvars_do_not_leak_between_tasks_or_workers():
    async def run(identity):
        with pc.bind(context(project_id=identity, explicit_save_ref="message-1", allow_global_save=True, allow_sensitive=True)):
            await asyncio.sleep(0)
            assert pc.current().project_id == identity
            with pc.for_worker("expert-a"):
                assert pc.current().expert_id == "expert-a"
                assert pc.current().actor("worker").explicit_save_ref is None
                assert not pc.current().allow_global_save
                assert not pc.current().allow_sensitive
            assert pc.current().explicit_save_ref == "message-1"
            assert pc.current().allow_sensitive
        assert pc.current() is None
    await asyncio.gather(run("project-a"), run("project-b"))
