from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from arslan.companion.memory import MemoryActor, MemoryError, MemoryScope, MemoryWrite
from server.db.models import MemoryDeletion, MemoryProposal, MemoryRevision, Project
from server.services.memory_repository import repository

USER = MemoryActor(origin="user")


def write(content="Prefer concise reports", **kwargs):
    return MemoryWrite(content=content, scope=MemoryScope(kind="global"), **kwargs)


async def test_explicit_user_save_is_versioned_and_manual(execution_db):
    async with repository() as repo:
        result = await repo.create(write(), USER)
        assert result["status"] == "active" and result["version"] == 1
        assert result["sources"][0]["author"] == "user"
        assert result["use_policy"] == "local_only"
    async with repository() as repo:
        assert len(await repo.list_entries()) == 1
        assert (await repo.history(result["id"]))[0]["content"] == write().content


@pytest.mark.parametrize("actor", [
    MemoryActor(origin="host"), MemoryActor(origin="worker", expert_id="1"),
    MemoryActor(origin="extractor"),
])
async def test_inference_and_worker_never_confirm_global_memory(execution_db, actor):
    async with repository() as repo:
        result = await repo.create(write(use_policy="cloud_allowed"), actor)
        assert result["status"] == "proposed" and result["confirmed_at"] is None
        assert result["use_policy"] == "local_only"
    async with execution_db() as db:
        proposal = (await db.execute(select(MemoryProposal))).scalar_one()
        assert proposal.target_entry_id == result["id"] and proposal.old_id is None


async def test_host_explicit_save_never_infers_cloud_consent(execution_db):
    import hashlib
    from arslan.companion.content_policy import normalized_memory
    actor = MemoryActor(origin="host", explicit_save_ref="message:1", allow_global_save=True,
                        explicit_save_digest=hashlib.sha256(normalized_memory(write().content).encode()).hexdigest())
    async with repository() as repo:
        result = await repo.create(write(use_policy="cloud_allowed"), actor)
        assert result["status"] == "active" and result["use_policy"] == "local_only"


@pytest.mark.parametrize("actor", [
    MemoryActor(origin="host", no_learning=True), MemoryActor(origin="host", temporary=True),
])
async def test_no_learning_and_temporary_do_not_persist(execution_db, actor):
    with pytest.raises(MemoryError, match="learning_disabled"):
        async with repository() as repo:
            await repo.create(write(), actor)
    async with repository() as repo:
        assert await repo.list_entries() == []


async def test_credentials_are_rejected_without_echo(execution_db):
    secret = "sk-proj-" + "A" * 30
    with pytest.raises(MemoryError) as error:
        async with repository() as repo:
            await repo.create(write(secret), USER)
    assert str(error.value) == "credentials_not_memory" and secret not in str(error.value)


async def test_sensitive_save_requires_separate_acknowledgement(execution_db):
    async with repository() as repo:
        pending = await repo.create(write("My birthday is January 1"), USER)
        assert pending["status"] == "proposed" and pending["sensitivity"] == "sensitive"
    async with execution_db() as db:
        proposal_id = await db.scalar(select(MemoryProposal.id))
    with pytest.raises(MemoryError, match="sensitive_confirmation"):
        async with repository() as repo:
            await repo.resolve_proposal(proposal_id, accept=True, actor=USER)
    async with repository() as repo:
        result = await repo.resolve_proposal(proposal_id, accept=True, actor=USER,
                                             sensitive_acknowledged=True)
        assert result["status"] == "active" and result["use_policy"] == "local_only"


async def test_stale_update_does_not_overwrite_new_revision(execution_db):
    async with repository() as repo:
        original = await repo.create(write(), USER)
    async with repository() as repo:
        changed = await repo.revise(original["id"], 1, write("Prefer detailed reports"), USER)
        assert changed["version"] == 2
    with pytest.raises(MemoryError, match="memory_version_conflict"):
        async with repository() as repo:
            await repo.revise(original["id"], 1, write("Stale overwrite"), USER)
    async with repository() as repo:
        assert (await repo.list_entries())[0]["content"] == "Prefer detailed reports"
        assert len(await repo.history(original["id"])) == 2


async def test_implicit_edit_leaves_confirmed_content_unchanged(execution_db):
    async with repository() as repo:
        original = await repo.create(write(), USER)
    async with repository() as repo:
        result = await repo.revise(original["id"], 1, write("Inferred replacement"),
                                   MemoryActor(origin="extractor"))
        assert result["status"] == "proposed"
        assert (await repo.present(await repo.get(original["id"])))["content"] == write().content


async def test_dismissing_stale_proposal_never_pauses_newer_confirmed_content(execution_db):
    async with repository() as repo:
        pending = await repo.create(write(), MemoryActor(origin="extractor"))
    async with execution_db() as db:
        proposal_id = await db.scalar(select(MemoryProposal.id))
    async with repository() as repo:
        changed = await repo.revise(pending["id"], 1, write("Manually reviewed replacement"), USER)
        assert changed["status"] == "active"
    async with repository() as repo:
        await repo.resolve_proposal(proposal_id, accept=False, actor=USER)
        entry = await repo.present(await repo.get(pending["id"]))
        assert entry["status"] == "active" and entry["content"] == "Manually reviewed replacement"
        assert entry["version"] == changed["version"]


async def test_project_identity_and_scope_widening_are_checked(execution_db):
    async with execution_db() as db:
        db.add(Project(id="project-a", name="A", owner_id="local"))
        db.add(Project(id="project-b", name="B", owner_id="local"))
        await db.commit()
    scoped = write().model_copy(update={"scope": MemoryScope(kind="project", id="project-a")})
    async with repository() as repo:
        original = await repo.create(scoped, USER)
    with pytest.raises(MemoryError, match="memory_scope_denied"):
        async with repository() as repo:
            await repo.create(scoped, MemoryActor(origin="host", project_id="project-b"))
    with pytest.raises(MemoryError, match="scope_confirmation"):
        async with repository() as repo:
            await repo.revise(original["id"], 1, write(), USER)
    async with repository() as repo:
        moved = await repo.revise(original["id"], 1, write(), USER, confirm_scope_change=True)
        assert moved["scope"]["kind"] == "global"


async def test_pause_restore_keeps_revision_chain(execution_db):
    async with repository() as repo:
        original = await repo.create(write(), USER)
        paused = await repo.set_status(original["id"], 1, "paused", USER)
        active = await repo.set_status(original["id"], 2, "active", USER)
        assert paused["version"] == 2 and active["version"] == 3
        assert [r["version"] for r in await repo.history(original["id"])] == [3, 2, 1]


async def test_expired_memory_cannot_be_reactivated_without_review(execution_db):
    async with repository() as repo:
        result = await repo.create(write(expires_at=datetime.now(UTC) - timedelta(days=1)), USER)
    with pytest.raises(MemoryError, match="memory_expired"):
        async with repository() as repo:
            await repo.set_status(result["id"], 1, "active", USER)


async def test_delete_erases_revisions_and_blocks_automatic_resurrection(execution_db):
    async with repository() as repo:
        original = await repo.create(write(), USER)
        updated = await repo.revise(original["id"], 1, write("Prefer detailed reports"), USER)
    async with repository() as repo:
        deleted = await repo.delete_entry(original["id"], updated["version"], USER)
        assert deleted["status"] == "deleted"
        assert await repo.history(original["id"]) == []
        assert await repo.list_entries() == []
    async with execution_db() as db:
        revisions = (await db.execute(select(MemoryRevision))).scalars().all()
        assert len(revisions) == 1 and revisions[0].content is None
        assert len((await db.execute(select(MemoryDeletion))).scalars().all()) == 2
    for content in (write().content, "Prefer detailed reports"):
        with pytest.raises(MemoryError, match="previously_deleted"):
            async with repository() as repo:
                await repo.create(write(content), MemoryActor(origin="extractor"))
