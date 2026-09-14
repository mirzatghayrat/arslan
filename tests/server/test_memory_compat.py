import pytest

from arslan.companion.memory import MemoryError
from server.orchestrator import memory
from server.services import personal_context as pc
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync


@pytest.fixture
async def active_memory(execution_db):
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)
    return execution_db


async def test_old_fact_crud_uses_v2_and_requires_versions(active_memory):
    fact = await memory.add_manual_fact("Use compact answers")
    assert fact.version == 1 and fact.status == "active" and fact.entry_id
    assert [f.id for f in await memory.list_facts()] == [fact.id]
    with pytest.raises(MemoryError, match="memory_version_required"):
        await memory.update_fact(fact.id, "Changed")
    edited = await memory.update_fact(fact.id, "Use detailed answers", expected_version=1)
    assert edited.version == 2 and edited.id == fact.id
    with pytest.raises(MemoryError, match="memory_version_conflict"):
        await memory.delete_fact(fact.id, expected_version=1)
    assert await memory.delete_fact(fact.id, expected_version=2)
    assert await memory.list_facts() == []


async def test_extraction_cannot_claim_manual_authority(active_memory):
    facts = [{"content": "Use examples", "source": "manual"}]
    assert await memory.save_facts(facts, provenance={"source_kind": "manual"}) == []
    with pc.bind(pc.TaskMemoryContext(task_id="task-a", run_id="run-a", model_is_local=True)):
        created = await memory.save_facts(facts, provenance={"source_kind": "manual"})
        assert created[0].status == "proposed"
        assert await memory.facts_text(include_sensitive=True) == ""
    assert await memory.list_facts() == []


async def test_legacy_prompt_helper_obeys_trusted_task_scope(active_memory):
    await memory.add_manual_fact("Use compact answers")
    assert await memory.facts_text(include_sensitive=True) == ""
    with pc.bind(pc.TaskMemoryContext(task_id="task-a", run_id="run-a", model_is_local=True, query="Answer the question")):
        assert "Use compact answers" in await memory.facts_text()
    with pc.bind(pc.TaskMemoryContext(task_id="task-a", run_id="run-a", no_memory=True)):
        assert await memory.facts_text(include_sensitive=True) == ""


async def test_extraction_honors_learning_and_secret_gates(active_memory):
    for controls in ({"no_learning": True}, {"temporary": True}):
        with pc.bind(pc.TaskMemoryContext(task_id="task-a", run_id="run-a", **controls)):
            assert await memory.save_facts([{"content": "Remember this"}], provenance={"source_kind": "router"}) == []
    with pc.bind(pc.TaskMemoryContext(task_id="task-a", run_id="run-a")):
        assert await memory.save_facts([{"content": "password=veryprivatevalue"}],
                                       provenance={"source_kind": "router"}) == []
