import hashlib

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from arslan.companion.content_policy import normalized_memory
from arslan.companion.design import StyleReference
from arslan.companion.memory import MemoryActor, MemoryError, MemoryScope, MemoryWrite
from server.db.models import MemoryProposal, MemoryRevision, Project
from server.services import personal_context as pc
from server.services.memory_migration import migrate_legacy_sync
from server.services.memory_repository import repository

USER = MemoryActor(origin="user")


@pytest.fixture
async def projects(execution_db):
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
    async with execution_db() as db:
        db.add_all([Project(id="project-a", name="A"), Project(id="project-b", name="B")])
        await db.commit()
    return execution_db


def write(content="Keep blue headings", project="project-a", **reference):
    return MemoryWrite(content=content, kind="style_rule", scope=MemoryScope(kind="project", id=project),
                       style_reference=StyleReference(source_kind="file", source_ref="reference.png",
                           polarity="positive", rationale="Blue separates headings from body text",
                           interpretation="confirmed", **reference))


async def test_positive_negative_references_are_project_scoped_and_versioned(projects):
    async with repository() as repo:
        a = await repo.create(write(), USER)
        b_write = write("Avoid blue headings", project="project-b")
        b_write = b_write.model_copy(update={"style_reference": b_write.style_reference.model_copy(update={"polarity": "negative"})})
        b = await repo.create(b_write, USER)
        updated = await repo.revise(a["id"], 1, write("Use blue headings with more spacing"), USER)
        assert updated["version"] == 2 and b["style_reference"]["polarity"] == "negative"
        history = await repo.history(a["id"])
        assert len(history) == 2 and history[1]["style_reference"]["source_ref"] == "reference.png"
    a_context = await pc.assemble("design", context=pc.TaskMemoryContext(task_id="a", run_id="a", project_id="project-a", model_is_local=True))
    b_context = await pc.assemble("design", context=pc.TaskMemoryContext(task_id="b", run_id="b", project_id="project-b", model_is_local=True))
    global_context = await pc.assemble("design", context=pc.TaskMemoryContext(task_id="g", run_id="g", model_is_local=True))
    assert "more spacing" in a_context.text and "Avoid blue" not in a_context.text
    assert "Avoid blue" in b_context.text and "more spacing" not in b_context.text
    assert '"polarity": "negative"' in b_context.text and "reference.png" in b_context.text
    assert "blue" not in global_context.text


async def test_tentative_interpretation_is_not_used_until_user_reviews_it(projects):
    value = write().model_copy(update={"style_reference": write().style_reference.model_copy(update={"interpretation": "tentative"})})
    async with repository() as repo:
        entry = await repo.create(value, USER)
        assert entry["status"] == "proposed"
        with pytest.raises(MemoryError, match="memory_confirmation_required"):
            await repo.set_status(entry["id"], entry["version"], "active", USER)
    context = pc.TaskMemoryContext(task_id="a", run_id="a", project_id="project-a", model_is_local=True, query="design")
    assert "blue" not in (await pc.assemble(context=context)).text
    async with projects() as db:
        proposal_id = await db.scalar(select(MemoryProposal.id))
    async with repository() as repo:
        result = await repo.resolve_proposal(proposal_id, accept=True, actor=USER)
        assert result["style_reference"]["interpretation"] == "confirmed" and result["status"] == "active"
    assert "blue" in (await pc.assemble(context=context)).text


async def test_host_text_confirmation_cannot_confirm_or_remove_reference_evidence(projects):
    value = write()
    actor = MemoryActor(origin="host", project_id="project-a", explicit_save_ref="message:1",
        explicit_save_digest=hashlib.sha256(normalized_memory(value.content).encode()).hexdigest())
    async with repository() as repo:
        assert (await repo.create(value, actor))["status"] == "proposed"
    async with repository() as repo:
        existing = (await repo.list_entries())[0]
        active = await repo.revise(existing["id"], existing["version"], value, USER)
        cleared = value.model_copy(update={"style_reference": None})
        assert (await repo.revise(active["id"], active["version"], cleared, actor))["status"] == "proposed"
        assert (await repo.present(await repo.get(active["id"])))["style_reference"]


async def test_old_client_edit_preserves_evidence_and_delete_erases_it(projects):
    async with repository() as repo:
        entry = await repo.create(write(), USER)
        old_client = MemoryWrite(content="Blue remains the heading color", kind="style_rule", scope=MemoryScope(kind="project", id="project-a"))
        edited = await repo.revise(entry["id"], 1, old_client, USER)
        assert edited["style_reference"] == entry["style_reference"]
        await repo.delete_entry(entry["id"], 2, USER)
        assert (await repo.present(await repo.get(entry["id"])))["style_reference"] is None
    async with projects() as db:
        remaining = (await db.scalars(select(MemoryRevision).where(MemoryRevision.entry_id == entry["id"]))).all()
        assert len(remaining) == 1 and remaining[0].content is None and remaining[0].structured_value is None


async def test_duplicate_rule_with_changed_reference_requires_explicit_edit(projects):
    async with repository() as repo:
        await repo.create(write(), USER)
    altered = write().model_copy(update={"style_reference": write().style_reference.model_copy(update={"source_ref": "different.png"})})
    with pytest.raises(MemoryError, match="style_reference_conflict"):
        async with repository() as repo:
            await repo.create(altered, USER)


async def test_reference_cannot_smuggle_secrets_or_escape_temporary_mode(projects):
    value = write().model_copy(update={"style_reference": write().style_reference.model_copy(update={"source_ref": "sk-proj-" + "A" * 30})})
    with pytest.raises(MemoryError, match="credentials_not_memory"):
        async with repository() as repo:
            await repo.create(value, USER)
    with pytest.raises(MemoryError, match="learning_disabled"):
        async with repository() as repo:
            await repo.create(write(), MemoryActor(origin="host", project_id="project-a", temporary=True))


async def test_sensitive_reference_reason_requires_the_existing_sensitive_review(projects):
    value = write().model_copy(update={"style_reference": write().style_reference.model_copy(update={"rationale": "My medical diagnosis changes my color perception"})})
    async with repository() as repo:
        result = await repo.create(value, USER)
        assert result["status"] == "proposed" and result["sensitivity"] == "sensitive"


def test_structured_references_cannot_be_global_or_task_memory():
    for scope in (MemoryScope(kind="global"), MemoryScope(kind="task", id="once")):
        with pytest.raises(ValidationError, match="style_reference_project_required"):
            MemoryWrite(content="Try monochrome once", kind="style_rule", scope=scope, style_reference=write().style_reference)
